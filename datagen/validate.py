"""Validation of an exported dataset.

    python -m datagen.validate --data data/full

Checks: primary-key uniqueness, foreign-key integrity, allowed enums, types/ranges/patterns, date ordering,
arithmetic reconciliation of derived values, life-cycle transitions, duplicates, ID conventions, ground-truth
leakage - plus an evaluation of the rule engine/auditor against the separate ground truth.
Writes VALIDATION_SUMMARY.json / .md next to the data and exits non-zero when an integrity check fails.
"""
import argparse
import csv
import json
import os
import re
import sys
import tempfile
from collections import defaultdict, Counter
from datetime import timedelta

from edu_support import config as C
from edu_support import dictionary, rules, db, evaluation
from edu_support.bizhours import business_hours_between


class Check:
    def __init__(self, group, name, description):
        self.group, self.name, self.description = group, name, description
        self.checked = 0
        self.bad = []

    def ok(self, cond, msg=""):
        self.checked += 1
        if not cond:
            self.bad.append(msg)

    def to_dict(self):
        return {"group": self.group, "name": self.name, "description": self.description, "checked": self.checked,
                "violations": len(self.bad), "status": "PASS" if not self.bad else "FAIL", "examples": self.bad[:5]}


def load(csv_dir):
    t = {}
    for name in dictionary.TABLES:
        with open(os.path.join(csv_dir, name + ".csv"), newline="", encoding="utf-8") as fh:
            rd = csv.DictReader(fh)
            t[name] = (rd.fieldnames, list(rd))
    return t


def parse_dt(s):
    return C.parse_dt(s) if s else None


def parse_d(s):
    return C.parse_d(s) if s else None


def validate(data_dir, run_evaluation=True):
    csv_dir = os.path.join(data_dir, "csv")
    raw = load(csv_dir)
    rows = {k: v[1] for k, v in raw.items()}
    checks = []

    def chk(group, name, desc):
        c = Check(group, name, desc)
        checks.append(c)
        return c

    # =================================================================================================
    # A. generic dictionary-driven checks
    # =================================================================================================
    c_hdr = chk("schema", "csv_headers_match_dictionary", "CSV header == data-dictionary column list (names and order)")
    c_req = chk("schema", "required_fields_present", "Every field marked R in the dictionary is non-empty")
    c_type = chk("schema", "types_parse", "int / real / bool(0,1) / date / datetime values parse")
    c_enum = chk("domain", "allowed_enums", "Enumerated fields contain only allowed values")
    c_rng = chk("domain", "numeric_ranges", "Numeric fields lie inside the documented RANGE")
    c_pat = chk("domain", "id_and_format_patterns", "PATTERN constraints (ID conventions, e-mail format) hold")
    c_len = chk("domain", "text_lengths", "Text fields respect the documented LEN bounds")
    c_pk = chk("keys", "primary_key_uniqueness", "Primary keys are unique (single and composite)")
    c_uq = chk("keys", "unique_constraints", "UNIQUE fields / composite unique sets contain no duplicates")
    c_fk = chk("keys", "foreign_key_integrity", "Every FK value exists in its parent table (join validation)")
    pk_sets = {}
    for tname, tdef in dictionary.TABLES.items():
        fields = tdef["fields"]
        cols = [f["name"] for f in fields]
        c_hdr.ok(raw[tname][0] == cols, "%s: %s" % (tname, raw[tname][0]))
        pkcols = tdef["pk"] or [f["name"] for f in fields if f["pk"]]
        seen = set()
        uniq = {f["name"]: set() for f in fields if f["unique"] and not f["pk"]}
        comp = [set() for _ in tdef["unique"]]
        for r in rows[tname]:
            for f in fields:
                v = r[f["name"]]
                where = "%s.%s=%r" % (tname, f["name"], v)
                if f["required"]:
                    c_req.ok(v != "", where + " empty")
                if v == "":
                    continue
                try:
                    if f["type"] == "int":
                        x = int(v)
                    elif f["type"] == "real":
                        x = float(v)
                    elif f["type"] == "bool":
                        x = int(v)
                        assert x in (0, 1)
                    elif f["type"] == "date":
                        C.parse_d(v)
                        x = None
                    elif f["type"] == "datetime":
                        C.parse_dt(v)
                        x = None
                    elif f["type"] == "json":
                        json.loads(v)
                        x = None
                    else:
                        x = None
                    c_type.ok(True)
                except Exception:
                    c_type.ok(False, where + " bad %s" % f["type"])
                    continue
                if f["enum"]:
                    c_enum.ok(v in f["enum"], where + " not in %s" % f["enum"])
                if f["range"] and x is not None:
                    c_rng.ok(f["range"][0] <= x <= f["range"][1], where + " outside %s" % (f["range"],))
                if f["pattern"]:
                    c_pat.ok(re.match(f["pattern"], v) is not None, where + " !~ " + f["pattern"])
                if f["len"]:
                    c_len.ok(f["len"][0] <= len(v) <= f["len"][1], where + " length %d" % len(v))
            key = tuple(r[c] for c in pkcols)
            c_pk.ok(key not in seen, "%s duplicate PK %s" % (tname, key))
            seen.add(key)
            for fname, s in uniq.items():
                v = r[fname]
                if v != "":
                    c_uq.ok(v not in s, "%s.%s duplicate %r" % (tname, fname, v))
                    s.add(v)
            for i, u in enumerate(tdef["unique"]):
                k = tuple(r[c] for c in u)
                c_uq.ok(k not in comp[i], "%s duplicate %s=%s" % (tname, u, k))
                comp[i].add(k)
        pk_sets[tname] = {(k if len(k) > 1 else k[0]) for k in seen}
        if len(pkcols) == 1:
            pk_sets[tname] = {k[0] if isinstance(k, tuple) else k for k in seen}
    for tname, tdef in dictionary.TABLES.items():
        for f in tdef["fields"]:
            if f["fk"]:
                pt, pc = f["fk"].split(".")
                parent = {r[pc] for r in rows[pt]}
                for r in rows[tname]:
                    v = r[f["name"]]
                    if v != "":
                        c_fk.ok(v in parent, "%s.%s=%s missing in %s.%s" % (tname, f["name"], v, pt, pc))

    # =================================================================================================
    # B. indexes
    # =================================================================================================
    tickets = {r["ticket_id"]: r for r in rows["ticket"]}
    by = lambda tbl: _group(rows[tbl], "ticket_id")
    msgs, evs, asg = by("message"), by("ticket_event"), by("assignment")
    slas = {r["ticket_id"]: r for r in rows["sla"]}
    fbs = {r["ticket_id"]: r for r in rows["resolution_feedback"]}
    links = _group(rows["message_article_link"], "message_id")
    cats = {r["category_id"]: r for r in rows["category"]}
    staff = {r["staff_id"]: r for r in rows["staff"]}
    reqs = {r["requester_id"]: r for r in rows["requester"]}
    roles = {r["role_id"]: r for r in rows["role"]}
    arts = {r["article_id"]: r for r in rows["knowledge_article"]}
    pols = {r["policy_id"]: r for r in rows["policy_document"]}
    terms = {r["term_id"]: r for r in rows["term"]}
    sla_pol = {r["priority"]: r for r in rows["sla_policy"]}
    prepared = rules.prepare_categories([{**r, "level": int(r["level"])} for r in rows["category"]])
    as_of = C.AS_OF

    # =================================================================================================
    # C. dates
    # =================================================================================================
    c = chk("dates", "term_dates_ordered", "registration_opens < start_date < end_date; add/drop and aid deadlines inside the term")
    for t in rows["term"]:
        s, e, ro = parse_d(t["start_date"]), parse_d(t["end_date"]), parse_d(t["registration_opens"])
        c.ok(ro < s < e and s <= parse_d(t["add_drop_deadline"]) <= e and s <= parse_d(t["aid_deadline"]) <= e, t["term_id"])
    c = chk("dates", "policy_windows", "policy effective_from <= effective_to; superseded policies have an end date; status matches as-of date")
    for p in rows["policy_document"]:
        f, t_ = parse_d(p["effective_from"]), parse_d(p["effective_to"])
        c.ok(t_ is None or f <= t_, p["policy_id"])
        want = "draft" if f > as_of.date() else "superseded" if (t_ and t_ < as_of.date()) else "active"
        c.ok(p["status"] == want, "%s status %s expected %s" % (p["policy_id"], p["status"], want))
    c = chk("dates", "article_version_chain", "Versions per topic are gap-free (1..k), windows contiguous & non-overlapping, only the last is open-ended, "
                                              "status matches as-of date, window lies inside the source policy window")
    topics = _group(rows["knowledge_article"], "topic_key")
    for tk, vs in topics.items():
        vs = sorted(vs, key=lambda r: int(r["version_no"]))
        c.ok([int(v["version_no"]) for v in vs] == list(range(1, len(vs) + 1)), "%s version numbers" % tk)
        for a, b in zip(vs, vs[1:]):
            c.ok(parse_d(a["effective_to"]) == parse_d(b["effective_from"]) - timedelta(days=1), "%s gap/overlap v%s->v%s" % (tk, a["version_no"], b["version_no"]))
            c.ok(b["supersedes_article_id"] == a["article_id"], "%s supersedes link" % b["article_id"])
        c.ok(vs[-1]["effective_to"] == "", "%s last version must be open" % tk)
        c.ok(vs[0]["supersedes_article_id"] == "", "%s v1 supersedes nothing" % tk)
        for v in vs:
            f, t_ = parse_d(v["effective_from"]), parse_d(v["effective_to"])
            want = "draft" if f > as_of.date() else "superseded" if (t_ and t_ < as_of.date()) else "current"
            c.ok(v["status"] == want, "%s status" % v["article_id"])
            p = pols[v["policy_id"]]
            pf, pt = parse_d(p["effective_from"]), parse_d(p["effective_to"])
            c.ok(f >= pf and (pt is None or (t_ is not None and t_ <= pt)), "%s window outside policy %s" % (v["article_id"], v["policy_id"]))
            c.ok(p["category_id"] == v["category_id"], "%s category differs from policy" % v["article_id"])
    c = chk("dates", "person_active_windows", "requester/staff active_from <= active_to; requester.status consistent with active_to")
    for r in rows["requester"]:
        c.ok(parse_d(r["active_to"]) is None or parse_d(r["active_from"]) <= parse_d(r["active_to"]), r["requester_id"])
        c.ok((r["status"] == "active") == (r["active_to"] == ""), r["requester_id"] + " status")
    for r in rows["staff"]:
        c.ok(parse_d(r["active_to"]) is None or parse_d(r["active_from"]) <= parse_d(r["active_to"]), r["staff_id"])
    c_tk = chk("dates", "ticket_dates", "created_at <= updated_at; deadline >= created date; requester active at creation; term window covers creation")
    c_msg = chk("dates", "message_order", "Message seq_no contiguous 1..n, created_at non-decreasing, first message = ticket body at created_at, none before ticket")
    c_ev = chk("dates", "event_order", "Event seq_no contiguous, event_at non-decreasing and >= ticket.created_at")
    c_as = chk("dates", "assignment_windows", "assigned_at <= unassigned_at; assigned_at >= ticket creation; consecutive assignments do not overlap")
    c_sla = chk("dates", "sla_times", "sla.clock_start = ticket.created_at; due >= start; response / resolution >= start")
    c_fb = chk("dates", "feedback_times", "resolved_at >= created_at; feedback_at >= resolved_at")
    for tid, t in tickets.items():
        cr, up = parse_dt(t["created_at"]), parse_dt(t["updated_at"])
        r = reqs[t["requester_id"]]
        c_tk.ok(cr <= up, tid + " updated < created")
        c_tk.ok(not t["deadline_date"] or parse_d(t["deadline_date"]) >= cr.date(), tid + " deadline before creation")
        c_tk.ok(parse_d(r["active_from"]) <= cr.date() and (r["active_to"] == "" or cr.date() <= parse_d(r["active_to"])), tid + " requester inactive")
        tm = terms[t["term_id"]]
        c_tk.ok(parse_d(tm["start_date"]) - timedelta(days=30) <= cr.date() <= parse_d(tm["end_date"]), tid + " term window")
        ms = sorted(msgs[tid], key=lambda m: int(m["seq_no"]))
        c_msg.ok([int(m["seq_no"]) for m in ms] == list(range(1, len(ms) + 1)), tid + " seq gaps")
        c_msg.ok(all(parse_dt(a["created_at"]) <= parse_dt(b["created_at"]) for a, b in zip(ms, ms[1:])), tid + " msg time order")
        c_msg.ok(len(ms) >= 1 and ms[0]["message_type"] == "question" and ms[0]["body"] == t["body"] and parse_dt(ms[0]["created_at"]) == cr, tid + " first message")
        for m in ms:
            c_msg.ok(m["message_id"] == "MSG-%s-%03d" % (tid, int(m["seq_no"])), m["message_id"] + " id/seq")
            c_msg.ok((m["sender_type"] == "requester") == (m["requester_id"] != "") and (m["sender_type"] == "staff") == (m["staff_id"] != ""), m["message_id"] + " sender columns")
            if m["sender_type"] == "requester":
                c_msg.ok(m["requester_id"] == t["requester_id"], m["message_id"] + " other requester")
        es = sorted(evs[tid], key=lambda e: int(e["seq_no"]))
        c_ev.ok([int(e["seq_no"]) for e in es] == list(range(1, len(es) + 1)), tid + " event seq")
        c_ev.ok(all(parse_dt(a["event_at"]) <= parse_dt(b["event_at"]) for a, b in zip(es, es[1:])) and parse_dt(es[0]["event_at"]) >= cr, tid + " event time order")
        asgs = sorted(asg[tid], key=lambda a: a["assignment_id"])
        for a in asgs:
            c_as.ok(parse_dt(a["assigned_at"]) >= cr and (a["unassigned_at"] == "" or parse_dt(a["assigned_at"]) <= parse_dt(a["unassigned_at"])), a["assignment_id"])
        for a, b in zip(asgs, asgs[1:]):
            c_as.ok(a["unassigned_at"] != "" and parse_dt(a["unassigned_at"]) <= parse_dt(b["assigned_at"]), a["assignment_id"] + " overlap")
        s = slas[tid]
        c_sla.ok(s["clock_start"] == t["created_at"], tid + " clock_start")
        c_sla.ok(parse_dt(s["first_response_due"]) >= cr and parse_dt(s["resolution_due"]) >= parse_dt(s["first_response_due"]) - timedelta(days=60), tid + " due")
        c_sla.ok(s["first_response_at"] == "" or parse_dt(s["first_response_at"]) >= cr, tid + " fr_at")
        c_sla.ok(s["resolved_at"] == "" or parse_dt(s["resolved_at"]) >= cr, tid + " resolved_at")
        if tid in fbs:
            f = fbs[tid]
            c_fb.ok(parse_dt(f["resolved_at"]) >= cr and (f["feedback_at"] == "" or parse_dt(f["feedback_at"]) >= parse_dt(f["resolved_at"])), tid)

    # =================================================================================================
    # D. life-cycle
    # =================================================================================================
    c1 = chk("lifecycle", "event_chain_and_transitions", "First event is 'created'; each from_status = previous to_status; every transition is in the allowed table")
    c2 = chk("lifecycle", "ticket_state_matches_history", "ticket.status = last event.to_status; updated_at = last event_at; category = last (re)categorisation; current_team = last assignment")
    c3 = chk("lifecycle", "closed_after_resolved_and_feedback", "'closed' only after 'resolved'; feedback exists iff the ticket currently is resolved/closed")
    c4 = chk("lifecycle", "escalation_consistency", "Every 'escalated' event has a matching 'escalation' assignment (same instant) and vice versa; escalate at most once")
    c5 = chk("lifecycle", "assignment_actors_valid", "Assigned staff belong to the team, hold a handling role and are active (with a 45-day horizon)")
    c6 = chk("lifecycle", "single_open_assignment", "At most one open assignment per ticket and none after 'closed'")
    for tid, t in tickets.items():
        es = sorted(evs[tid], key=lambda e: int(e["seq_no"]))
        ok = es[0]["event_type"] == "created" and es[0]["from_status"] == ""
        for a, b in zip(es, es[1:]):
            same = b["event_type"] in ("recategorized", "reassigned") and b["from_status"] == b["to_status"] == a["to_status"]
            ok = ok and b["from_status"] == a["to_status"] and (same or b["to_status"] in C.TRANSITIONS[a["to_status"]])
        c1.ok(ok, tid)
        cat = None
        for e in es:
            d = json.loads(e["details"]) if e["details"] else {}
            if e["event_type"] == "triaged":
                cat = d["category"]
            elif e["event_type"] == "recategorized":
                cat = d["to_category"]
        asgs = sorted(asg[tid], key=lambda a: a["assignment_id"])
        c2.ok(t["status"] == es[-1]["to_status"] and t["updated_at"] == es[-1]["event_at"] and t["category_id"] == cat
              and t["current_team_id"] == asgs[-1]["team_id"], tid)
        types = [e["event_type"] for e in es]
        if "closed" in types:
            c3.ok("resolved" in types[:types.index("closed")], tid + " closed w/o resolved")
        c3.ok((tid in fbs) == (t["status"] in ("resolved", "closed")), tid + " feedback vs status")
        esc_ev = [e for e in es if e["event_type"] == "escalated"]
        esc_as = [a for a in asgs if a["assignment_type"] == "escalation"]
        c4.ok(len(esc_ev) == len(esc_as) <= 1 and all(a["assigned_at"] == e["event_at"] for a, e in zip(esc_as, esc_ev)), tid)
        for a in asgs:
            s_ = staff[a["staff_id"]]
            day = parse_dt(a["assigned_at"]).date()
            c5.ok(s_["team_id"] == a["team_id"] and roles[s_["role_id"]]["can_handle_ticket"] == "1" and parse_d(s_["active_from"]) <= day
                  and (s_["active_to"] == "" or parse_d(s_["active_to"]) >= day + timedelta(days=45)), a["assignment_id"])
        open_ = [a for a in asgs if a["unassigned_at"] == ""]
        c6.ok(len(open_) <= 1 and (t["status"] != "closed" or not open_), tid)
    c = chk("lifecycle", "requester_roles_can_raise", "Ticket requesters hold a role that may raise tickets")
    for t in tickets.values():
        c.ok(roles[reqs[t["requester_id"]]["role_id"]]["can_raise_ticket"] == "1", t["ticket_id"])
    c = chk("lifecycle", "staff_message_authors_assigned", "Staff authors of public/internal messages belong to a team that held the ticket at that time")
    for tid in tickets:
        asgs = asg[tid]
        for m in msgs[tid]:
            if m["sender_type"] != "staff":
                continue
            at = parse_dt(m["created_at"])
            held = any(a["staff_id"] == m["staff_id"] and parse_dt(a["assigned_at"]) <= at and (a["unassigned_at"] == "" or at <= parse_dt(a["unassigned_at"])) for a in asgs)
            c.ok(held, m["message_id"])

    # =================================================================================================
    # E. arithmetic / derived values
    # =================================================================================================
    a1 = chk("arithmetic", "sla_status_reconciles", "first_response_status / resolution_status recomputed from stored due, response / resolution times and the as-of date")
    a2 = chk("arithmetic", "sla_hours_reconcile", "first_response_business_hours / resolution_business_hours = business hours between created_at and the event")
    a3 = chk("arithmetic", "sla_sources_reconcile", "sla.first_response_at = first public staff response; sla.resolved_at = feedback.resolved_at; sla.priority = ticket.priority")
    a4 = chk("arithmetic", "feedback_derived_fields", "resolution_calendar/business hours and reopen_count recomputed from events; resolution_code equals the last 'resolved' event")
    a5 = chk("arithmetic", "priority_follows_rule", "ticket.priority = derive_priority(category default, deadline, urgency words)")
    a6 = chk("arithmetic", "routing_follows_rule", "Triage decision (category, ambiguity) = classify(subject + body); initial team = routing rule of the category (unless staff override)")
    a7 = chk("arithmetic", "citation_version_recorded", "message_article_link.cited_version_no = article.version_no; links only on public staff 'answer' messages")
    a8 = chk("arithmetic", "volume_totals", "Every ticket has >= 1 message (the request) and exactly one SLA row")
    for tid, t in tickets.items():
        s = slas[tid]
        cr = parse_dt(t["created_at"])
        due_f, due_r = parse_dt(s["first_response_due"]), parse_dt(s["resolution_due"])
        fr, rs = parse_dt(s["first_response_at"]), parse_dt(s["resolved_at"])

        def st(at, due):
            return ("met" if at <= due else "breached") if at else ("breached" if as_of > due else "pending")
        a1.ok(s["first_response_status"] == st(fr, due_f) and s["resolution_status"] == st(rs, due_r), tid)
        a2.ok((s["first_response_business_hours"] == "" and fr is None or abs(float(s["first_response_business_hours"]) - business_hours_between(cr, fr)) < 0.011)
              and (s["resolution_business_hours"] == "" and rs is None or abs(float(s["resolution_business_hours"]) - business_hours_between(cr, rs)) < 0.011), tid)
        first_resp = next((parse_dt(m["created_at"]) for m in sorted(msgs[tid], key=lambda m: int(m["seq_no"]))
                           if m["sender_type"] == "staff" and m["is_internal"] == "0" and m["message_type"] in ("clarification_request", "answer")), None)
        a3.ok(first_resp == fr and s["priority"] == t["priority"] and ((tid in fbs and fbs[tid]["resolved_at"] == s["resolved_at"]) or (tid not in fbs and rs is None)), tid)
        if tid in fbs:
            f = fbs[tid]
            es = sorted(evs[tid], key=lambda e: int(e["seq_no"]))
            last_res = [e for e in es if e["event_type"] == "resolved"][-1]
            a4.ok(abs(float(f["resolution_calendar_hours"]) - round((parse_dt(f["resolved_at"]) - cr).total_seconds() / 3600, 2)) < 0.011
                  and abs(float(f["resolution_business_hours"]) - business_hours_between(cr, parse_dt(f["resolved_at"]))) < 0.011
                  and int(f["reopen_count"]) == sum(1 for e in es if e["event_type"] == "reopened")
                  and f["resolution_code"] == json.loads(last_res["details"])["resolution_code"] and f["resolved_at"] == last_res["event_at"], tid)
        es = sorted(evs[tid], key=lambda e: int(e["seq_no"]))
        tri = json.loads([e for e in es if e["event_type"] == "triaged"][0]["details"])
        text = t["subject"] + " " + t["body"]
        cls = rules.classify(text, prepared)
        a6.ok(tri["category"] == cls["category_id"] and tri["ambiguous"] == cls["ambiguous"], tid + " triage")
        first_cat = tri["category"]
        pr = rules.derive_priority(cats[first_cat]["default_priority"], cr, parse_d(t["deadline_date"]), text)[0]
        a5.ok(pr == t["priority"], "%s priority %s expected %s" % (tid, t["priority"], pr))
        init = sorted(asg[tid], key=lambda a: a["assignment_id"])[0]
        if init["assigned_by"] == "system":
            rule = next(r for r in rows["routing_rule"] if r["rule_id"] == init["routing_rule_id"])
            a6.ok(rule["category_id"] == first_cat and rule["team_id"] == init["team_id"] and rule["rule_type"] == "initial", tid + " rule")
        a8.ok(len(msgs[tid]) >= 1 and tid in slas, tid)
    for m in rows["message"]:
        for l in links.get(m["message_id"], []):
            a7.ok(int(l["cited_version_no"]) == int(arts[l["article_id"]]["version_no"]) and m["sender_type"] == "staff" and m["message_type"] == "answer" and m["is_internal"] == "0",
                  m["message_id"])
    a8.ok(len(rows["sla"]) == len(rows["ticket"]), "sla/ticket count")

    # =================================================================================================
    # F. duplicates, IDs, leakage
    # =================================================================================================
    d1 = chk("duplicates", "duplicate_tickets", "No two tickets share (requester, subject, body, created_at)")
    seen = set()
    for t in rows["ticket"]:
        k = (t["requester_id"], t["subject"], t["body"], t["created_at"])
        d1.ok(k not in seen, t["ticket_id"])
        seen.add(k)
    d2 = chk("duplicates", "duplicate_articles", "No two article versions of a topic share the same key fact value consecutively unless intended; no duplicate (topic, version)")
    for tk, vs in topics.items():
        vs = sorted(vs, key=lambda r: int(r["version_no"]))
        d2.ok(len({v["version_no"] for v in vs}) == len(vs), tk)
    d3 = chk("duplicates", "duplicate_messages", "No duplicate (ticket, sender, type, created_at, body)")
    seen = set()
    for m in rows["message"]:
        k = (m["ticket_id"], m["sender_type"], m["staff_id"], m["message_type"], m["created_at"], m["body"])
        d3.ok(k not in seen, m["message_id"])
        seen.add(k)
    i1 = chk("ids", "ticket_ids_contiguous", "TKT-2026-000001..N has no gaps; KB-000001..N has no gaps; REQ / STF contiguous")
    n = len(rows["ticket"])
    i1.ok(sorted(tickets) == ["TKT-2026-%06d" % i for i in range(1, n + 1)], "ticket id gaps")
    i1.ok(sorted(arts) == ["KB-%06d" % i for i in range(1, len(arts) + 1)], "KB gaps")
    i1.ok(sorted(reqs) == ["REQ-%06d" % i for i in range(1, len(reqs) + 1)], "REQ gaps")
    i1.ok(sorted(staff) == ["STF-%04d" % i for i in range(1, len(staff) + 1)], "STF gaps")
    i1.ok(all(s["sla_id"] == "SLA-" + s["ticket_id"] for s in rows["sla"]), "SLA ids")
    i2 = chk("ids", "policy_ids_follow_convention", "POL-<domain>-2026-NNN with the domain matching the policy domain and gap-free counters per domain")
    per = defaultdict(list)
    for p in rows["policy_document"]:
        i2.ok(p["policy_id"].split("-")[1] == p["domain"], p["policy_id"])
        per[p["domain"]].append(int(p["policy_id"][-3:]))
    for dom, nums in per.items():
        i2.ok(sorted(nums) == list(range(1, len(nums) + 1)), dom + " counters")
    l1 = chk("leakage", "ground_truth_not_in_input_tables", "No input column carries ground-truth labels (issue_type, expected_*, true_*, scenario, kind, is_ambiguous ...)")
    banned = re.compile(r"^(issue_type|issue_entity_id|expected_.*|true_.*|.*ground_truth.*|scenario|kind|is_ambiguous|anomal.*|label)$", re.I)
    for tname, (cols, _) in raw.items():
        for col in cols:
            l1.ok(not banned.search(col), "%s.%s" % (tname, col))
    gt_path = os.path.join(data_dir, "ground_truth", "ground_truth.csv")
    l2 = chk("leakage", "ground_truth_is_separate_and_joinable", "ground_truth.csv lives in its own folder and every ticket_id joins to ticket (1:1)")
    with open(gt_path, newline="", encoding="utf-8") as fh:
        gt_ids = [r["ticket_id"] for r in csv.DictReader(fh)]
    l2.ok(sorted(gt_ids) == sorted(tickets), "ticket id set differs")
    l2.ok(os.path.dirname(gt_path) != csv_dir, "ground truth inside input folder")

    # =================================================================================================
    # G. SQL load (FK + CHECK enforcement by the DB engine) + evaluation vs ground truth
    # =================================================================================================
    ev_block = None
    with tempfile.TemporaryDirectory() as tmp:
        c = chk("database", "loads_into_sqlite_with_constraints", "CSV loads into SQLite with PRIMARY KEY / FOREIGN KEY / CHECK constraints enforced")
        try:
            dbp = os.path.join(tmp, "v.db")
            db.build_database(dbp, csv_dir)
            c.ok(True)
            if run_evaluation:
                conn = db.connect(dbp)
                ev_block = evaluation.evaluate(conn, os.path.join(data_dir, "ground_truth"))
                conn.close()
        except Exception as ex:  # noqa
            c.ok(False, repr(ex))
    summary = {"data_dir": data_dir, "as_of": C.fmt_dt(as_of), "row_counts": {k: len(v) for k, v in rows.items()},
               "checks": [c.to_dict() for c in checks],
               "checks_passed": sum(1 for c in checks if not c.bad), "checks_failed": sum(1 for c in checks if c.bad),
               "evaluation": ev_block}
    return summary


def _group(rows, key):
    d = defaultdict(list)
    for r in rows:
        d[r[key]].append(r)
    return d


def to_markdown(s):
    L = ["# Validation summary", "", "Data set: `%s`  |  as-of: %s  |  checks passed: **%d / %d**" % (s["data_dir"], s["as_of"], s["checks_passed"], s["checks_passed"] + s["checks_failed"]), "",
         "## Row counts", "", "| table | rows |", "|---|---:|"]
    L += ["| %s | %d |" % (k, v) for k, v in s["row_counts"].items()]
    L += ["", "## Integrity checks", "", "| group | check | what is verified | items checked | violations | result |", "|---|---|---|---:|---:|---|"]
    for c in s["checks"]:
        L.append("| %s | `%s` | %s | %d | %d | %s |" % (c["group"], c["name"], c["description"], c["checked"], c["violations"], c["status"]))
    ev = s.get("evaluation")
    if ev:
        L += ["", "## Rule engine / auditor vs. separate ground truth", "",
              "Ground truth is read only by the evaluator; the auditor works from the input tables alone.", "",
              "| anomaly type | TP | FP | FN | precision | recall |", "|---|---:|---:|---:|---:|---:|"]
        for k, v in ev["anomaly_detection"]["by_type"].items():
            L.append("| %s | %d | %d | %d | %.3f | %.3f |" % (k, v["tp"], v["fp"], v["fn"], v["precision"], v["recall"]))
        o = ev["anomaly_detection"]["overall"]
        L.append("| **overall** | %d | %d | %d | %.3f | %.3f |" % (o["tp"], o["fp"], o["fn"], o["precision"], o["recall"]))
        r = ev["router"]
        L += ["", "| metric | value |", "|---|---:|",
              "| router category accuracy | %.4f |" % r["category_accuracy"],
              "| router domain accuracy (non-ambiguous) | %.4f |" % r["domain_accuracy_non_ambiguous"],
              "| ambiguity detection precision / recall | %.3f / %.3f |" % (r["ambiguity_detection"]["precision"], r["ambiguity_detection"]["recall"]),
              "| priority accuracy | %.4f |" % ev["priority_accuracy"],
              "| initial team accuracy | %.4f |" % ev["initial_team_accuracy"],
              "| escalation precision / recall vs expected | %.3f / %.3f |" % (ev["escalation_vs_expected"]["precision"], ev["escalation_vs_expected"]["recall"]),
              "| first cited article accuracy | %.4f |" % ev["first_cited_article_accuracy"], "",
              "### Acceptance criteria", "", "| criterion | measured |", "|---|---|"]
        for k, v in ev["acceptance"].items():
            L.append("| %s | %s |" % (k.replace("_", " "), ", ".join("%s=%s" % (a, b) for a, b in v.items())))
    failed = [c for c in s["checks"] if c["status"] == "FAIL"]
    if failed:
        L += ["", "## Failures", ""]
        for c in failed:
            L += ["* `%s`: %s" % (c["name"], "; ".join(c["examples"]))]
    return "\n".join(L) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/full")
    ap.add_argument("--no-eval", action="store_true")
    a = ap.parse_args(argv)
    s = validate(a.data, not a.no_eval)
    with open(os.path.join(a.data, "VALIDATION_SUMMARY.json"), "w", encoding="utf-8") as fh:
        json.dump(s, fh, indent=1)
    with open(os.path.join(a.data, "VALIDATION_SUMMARY.md"), "w", encoding="utf-8") as fh:
        fh.write(to_markdown(s))
    print("checks passed %d / %d" % (s["checks_passed"], s["checks_passed"] + s["checks_failed"]))
    for c in s["checks"]:
        if c["status"] == "FAIL":
            print("FAIL", c["name"], c["violations"], c["examples"][:3])
    if s.get("evaluation"):
        ev = s["evaluation"]
        print("anomaly detection overall:", ev["anomaly_detection"]["overall"])
        for k, v in ev["anomaly_detection"]["by_type"].items():
            print("  ", k, v)
    return 1 if s["checks_failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
