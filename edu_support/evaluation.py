"""Evaluation of the rule engine / auditor against the SEPARATE ground-truth files.

Ground truth is read from disk only here (never joined into the application's input tables).
"""
import csv
import json
import os
from collections import Counter, defaultdict

from . import audit
from . import config as C


def _prf(tp, fp, fn):
    p = tp / (tp + fp) if tp + fp else 1.0
    r = tp / (tp + fn) if tp + fn else 1.0
    f = 2 * p * r / (p + r) if p + r else 0.0
    return {"tp": tp, "fp": fp, "fn": fn, "precision": round(p, 4), "recall": round(r, 4), "f1": round(f, 4)}


def load_ground_truth(gt_dir):
    with open(os.path.join(gt_dir, "ground_truth.csv"), newline="", encoding="utf-8") as fh:
        gt = list(csv.DictReader(fh))
    with open(os.path.join(gt_dir, "ground_truth_anomalies.csv"), newline="", encoding="utf-8") as fh:
        an = list(csv.DictReader(fh))
    return gt, an


def evaluate(conn, gt_dir, now=C.AS_OF):
    gt, anomalies = load_ground_truth(gt_dir)
    gt_by = {g["ticket_id"]: g for g in gt}
    ref = audit.Reference.from_db(conn)
    findings = audit.audit_database(conn, now, ref)
    found = {(f["issue_type"], f["entity_id"]) for f in findings}
    labelled = {(a["issue_type"], a["entity_id"]) for a in anomalies}
    per_type = {}
    for it in C.ISSUE_TYPES:
        f = {x for x in found if x[0] == it}
        l = {x for x in labelled if x[0] == it}
        per_type[it] = _prf(len(f & l), len(f - l), len(l - f))
    overall = _prf(len(found & labelled), len(found - labelled), len(labelled - found))

    # ---- router vs ground truth ------------------------------------------------------------------------
    triage = {}
    for r in conn.execute("SELECT ticket_id, details FROM ticket_event WHERE event_type='triaged'"):
        triage[r["ticket_id"]] = json.loads(r["details"])
    leaf_ok = dom_ok = n_dom = 0
    tp = fp = fn = 0
    for tid, g in gt_by.items():
        d = triage[tid]
        leaf_ok += d["category"] == g["expected_initial_category_id"]
        true_amb = g["true_ambiguous"] == "1"
        if not true_amb:
            n_dom += 1
            dom_ok += d["domain"] == g["true_domain"]
        tp += d["ambiguous"] and true_amb
        fp += d["ambiguous"] and not true_amb
        fn += (not d["ambiguous"]) and true_amb
    router = {"category_accuracy": round(leaf_ok / len(gt_by), 4), "domain_accuracy_non_ambiguous": round(dom_ok / max(1, n_dom), 4),
              "ambiguity_detection": _prf(tp, fp, fn)}

    # ---- priority / team routing -----------------------------------------------------------------------
    prio_ok = sum(1 for r in conn.execute("SELECT ticket_id, priority FROM ticket") if r["ticket_id"] in gt_by and r["priority"] == gt_by[r["ticket_id"]]["expected_priority"])
    team_ok = n_init = 0
    for r in conn.execute("SELECT ticket_id, team_id FROM assignment WHERE assignment_type='initial'"):
        if r["ticket_id"] not in gt_by:
            continue
        n_init += 1
        team_ok += r["team_id"] == gt_by[r["ticket_id"]]["expected_initial_team_id"]

    # ---- escalation: expected (rules / ground truth) vs actual ---------------------------------------------
    escalated = {r[0] for r in conn.execute("SELECT DISTINCT ticket_id FROM ticket_event WHERE event_type='escalated'")}
    etp = efp = efn = 0
    for tid, g in gt_by.items():
        exp = g["expected_escalation"] == "1"
        act = tid in escalated
        etp += exp and act
        efp += act and not exp
        efn += exp and not act
    escalation = _prf(etp, efp, efn)

    # ---- citations -------------------------------------------------------------------------------------------
    total_cited = conn.execute("SELECT COUNT(DISTINCT message_id) FROM message_article_link").fetchone()[0]
    expired = len({f["entity_id"] for f in findings if f["issue_type"] == "EXPIRED_POLICY_CITATION"})
    versions_recorded = conn.execute("SELECT COUNT(*) FROM message_article_link l JOIN knowledge_article a ON a.article_id=l.article_id "
                                     "WHERE l.cited_version_no = a.version_no").fetchone()[0]
    total_links = conn.execute("SELECT COUNT(*) FROM message_article_link").fetchone()[0]
    exp_art_ok = n_exp = 0
    first_cited = {}
    for r in conn.execute("SELECT m.ticket_id, l.article_id FROM message_article_link l JOIN message m ON m.message_id=l.message_id "
                          "ORDER BY m.ticket_id, m.seq_no"):
        first_cited.setdefault(r["ticket_id"], r["article_id"])
    for tid, art in first_cited.items():
        if tid in gt_by and gt_by[tid]["expected_article_id"]:
            n_exp += 1
            exp_art_ok += art == gt_by[tid]["expected_article_id"]

    n_tickets = len(gt_by)
    sla = {r["k"]: r["n"] for r in conn.execute("SELECT 'fr_' || first_response_status AS k, COUNT(*) n FROM sla GROUP BY 1 "
                                                "UNION ALL SELECT 'res_' || resolution_status, COUNT(*) FROM sla GROUP BY 1")}
    acceptance = {
        "answers_cite_current_sources": {"cited_answers": total_cited, "citing_expired_version": expired,
                                         "rate_current": round(1 - expired / max(1, total_cited), 4)},
        "routing_is_consistent": {"initial_assignments": n_init, "to_authorised_team_rate": round(1 - len([f for f in findings if f["issue_type"] == "UNAUTHORIZED_ROUTING"]) / max(1, n_init), 4)},
        "unresolved_or_ambiguous_cases_escalate": {"expected_escalations": etp + efn, "escalated": etp, "rate": round(etp / max(1, etp + efn), 4)},
        "article_version_recorded": {"links": total_links, "version_recorded_correctly": versions_recorded,
                                     "rate": round(versions_recorded / max(1, total_links), 4)},
    }
    return {
        "as_of": C.fmt_dt(now), "tickets": n_tickets,
        "anomaly_detection": {"overall": overall, "by_type": per_type},
        "router": router,
        "priority_accuracy": round(prio_ok / n_tickets, 4),
        "initial_team_accuracy": round(team_ok / max(1, n_init), 4),
        "escalation_vs_expected": escalation,
        "first_cited_article_accuracy": round(exp_art_ok / max(1, n_exp), 4),
        "sla_status_counts": sla,
        "acceptance": acceptance,
        "findings_total": len(findings),
        "labelled_total": len(labelled),
        "scenario_counts": dict(Counter(g["scenario"] for g in gt)),
    }
