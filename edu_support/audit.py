"""Rule-based auditor.

Re-derives, from stored records only (never from ground truth), what the documented rules require and flags
records that violate them.  The same `expected_escalation()` function is used by the generator to label
expected decisions, by the backend to trigger escalations and by the auditor to detect missed ones.
"""
from collections import defaultdict
from datetime import datetime, date

from . import config as C
from . import dictionary
from . import rules
from .bizhours import add_business_hours

_TYPE = {f["name"]: f["type"] for t in dictionary.TABLES.values() for f in t["fields"]}


def to_py(row, table):
    """sqlite Row / dict (strings) -> dict with date / datetime objects."""
    out = {}
    for f in dictionary.TABLES[table]["fields"]:
        v = row[f["name"]]
        if v is not None and isinstance(v, str):
            if f["type"] == "datetime":
                v = C.parse_dt(v)
            elif f["type"] == "date":
                v = C.parse_d(v)
        out[f["name"]] = v
    return out


class Reference:
    """Reference data needed by the rules: categories, KB articles, SLA hours, authorization matrix."""

    def __init__(self, categories, articles, sla_policies, auth_rows):
        self.cats = {c["category_id"]: c for c in categories}
        self.prepared = rules.prepare_categories(categories)
        self.articles = {a["article_id"]: a for a in articles}
        self.art_by_topic = defaultdict(list)
        for a in sorted(articles, key=lambda a: (a["topic_key"], a["version_no"])):
            self.art_by_topic[a["topic_key"]].append(a)
        seen, topics = set(), []
        for a in sorted(articles, key=lambda a: a["article_id"]):
            if a["topic_key"] not in seen:
                seen.add(a["topic_key"])
                topics.append({"topic_key": a["topic_key"], "domain": a["topic_key"].split("-")[0], "title": a["title"],
                               "category_id": a["category_id"]})
        self.topics = rules.prepare_topics(topics)
        self.sla_hours = {s["priority"]: (s["first_response_hours"], s["resolution_hours"]) for s in sla_policies}
        self.auth = {(a["team_id"], a["category_id"]): a["access_level"] for a in auth_rows}

    @classmethod
    def from_master(cls, G):
        return cls(G.rows["category"], G.rows["knowledge_article"], G.rows["sla_policy"], G.rows["team_category_authorization"])

    @classmethod
    def from_db(cls, conn):
        def q(table):
            return [to_py(r, table) for r in conn.execute("SELECT * FROM %s" % table)]
        return cls(q("category"), q("knowledge_article"), q("sla_policy"), q("team_category_authorization"))

    def article_at(self, topic_key, at):
        return rules.effective_article(self.art_by_topic[topic_key], at)


# --------------------------------------------------------------------------------------------------
def public_staff_responses(messages):
    return [m for m in messages if m["sender_type"] == "staff" and not m["is_internal"]
            and m["message_type"] in ("clarification_request", "answer")]


def requester_text(ticket, messages):
    return ticket["subject"] + " " + " ".join(m["body"] for m in messages if m["sender_type"] == "requester")


def expected_escalation(ref, ticket, messages, sla, now):
    """Escalation reasons required by rules E1-E5 given the records at instant `now`."""
    reasons = []
    grace = C.ESC_GRACE
    msgs = sorted(messages, key=lambda m: (m["created_at"], m.get("seq_no", 0)))
    resp = public_staff_responses(msgs)
    first_resp = resp[0]["created_at"] if resp else None
    cls = rules.classify(requester_text(ticket, msgs), ref.prepared)
    cat = ref.cats[ticket["category_id"]]
    # E3 - category needs a human decision
    if cat["requires_human_review"] and first_resp and first_resp + grace <= now:
        reasons.append("E3_HUMAN_DECISION_REQUIRED")
    if cls["ambiguous"]:
        # E1 - still ambiguous after clarification, or clarification unanswered for 2 business days
        clar = [m for m in msgs if m["message_type"] == "clarification_request"]
        if clar:
            c = clar[0]["created_at"]
            replies = [m for m in msgs if m["message_type"] == "clarification_reply" and m["created_at"] > c]
            if replies:
                if replies[0]["created_at"] + grace <= now:
                    reasons.append("E1_AMBIGUOUS_UNRESOLVED")
            elif add_business_hours(c, C.CLARIFICATION_WAIT_BH) + grace <= now:
                reasons.append("E1_AMBIGUOUS_UNRESOLVED")
    else:
        # E2 - no applicable KB article
        mt = rules.match_topic(requester_text(ticket, msgs), ref.topics, cls["domain"])
        if not mt["found"] and first_resp and first_resp + grace <= now:
            reasons.append("E2_NO_POLICY_SOURCE")
    # E4 - urgent ticket missed its first-response SLA (judged on the business-hours clock)
    if ticket["priority"] == "urgent":
        due = add_business_hours(ticket["created_at"], ref.sla_hours["urgent"][0])
        if due + grace <= now and (first_resp is None or first_resp > due):
            reasons.append("E4_URGENT_SLA_BREACH")
    # E5 - repeated follow-ups
    fu = [m for m in msgs if m["message_type"] == "followup"]
    if len(fu) >= C.FOLLOWUPS_FOR_ESCALATION and fu[C.FOLLOWUPS_FOR_ESCALATION - 1]["created_at"] + grace <= now:
        reasons.append("E5_REPEATED_FOLLOWUPS")
    return reasons


def findings_for_ticket(ref, ticket, messages, links, events, assignments, sla, now):
    """Run the five detectors on one ticket. `links` = message_article_link rows of this ticket's messages."""
    out = []
    tid = ticket["ticket_id"]
    msg_by_id = {m["message_id"]: m for m in messages}
    links_by_msg = defaultdict(list)
    for l in links:
        links_by_msg[l["message_id"]].append(l)
    # 1) answer cites an article that was not in force when the message was sent
    for l in links:
        art = ref.articles[l["article_id"]]
        d = msg_by_id[l["message_id"]]["created_at"].date()
        if d < art["effective_from"] or (art["effective_to"] is not None and d > art["effective_to"]):
            out.append({"issue_type": "EXPIRED_POLICY_CITATION", "ticket_id": tid, "entity_type": "message", "entity_id": l["message_id"],
                        "detail": "cites %s (v%s, valid %s..%s) on %s" % (art["article_id"], art["version_no"], art["effective_from"],
                                                                         art["effective_to"] or "open", d)})
    # 2) assignment to a team that is not authorised for the category (at that time)
    for a in assignments:
        level = ref.auth.get((a["team_id"], a["category_id_at_assignment"]))
        ok = level == "handle" if a["assignment_type"] in ("initial", "reassignment") else level in ("handle", "escalation")
        if not ok:
            out.append({"issue_type": "UNAUTHORIZED_ROUTING", "ticket_id": tid, "entity_type": "assignment", "entity_id": a["assignment_id"],
                        "detail": "%s is not authorised (%s) for %s" % (a["team_id"], a["assignment_type"], a["category_id_at_assignment"])})
    # 3) numeric claim in an answer that no cited article supports
    for m in messages:
        if m["sender_type"] == "staff" and not m["is_internal"] and m["message_type"] == "answer":
            srcs = [ref.articles[l["article_id"]]["title"] + " " + ref.articles[l["article_id"]]["body"] for l in links_by_msg[m["message_id"]]]
            bad = rules.unsupported_numbers(m["body"], srcs)
            if bad:
                out.append({"issue_type": "UNSUPPORTED_CLAIM", "ticket_id": tid, "entity_type": "message", "entity_id": m["message_id"],
                            "detail": "numbers not found in cited sources: %s" % ", ".join(bad)})
    # 4) SLA clock must follow business hours
    fr_h, res_h = ref.sla_hours[sla["priority"]]
    fr_due = add_business_hours(sla["clock_start"], fr_h)
    res_due = add_business_hours(sla["clock_start"], res_h)
    if fr_due != sla["first_response_due"] or res_due != sla["resolution_due"]:
        out.append({"issue_type": "SLA_IGNORES_BUSINESS_HOURS", "ticket_id": tid, "entity_type": "sla", "entity_id": sla["sla_id"],
                    "detail": "stored first_response_due=%s, business-hours due=%s" % (sla["first_response_due"], fr_due)})
    # 5) an escalation rule fired but the ticket was never escalated
    reasons = expected_escalation(ref, ticket, messages, sla, now)
    if reasons and not any(e["event_type"] == "escalated" for e in events):
        out.append({"issue_type": "ESCALATION_NOT_TRIGGERED", "ticket_id": tid, "entity_type": "ticket", "entity_id": tid,
                    "detail": "required by " + ", ".join(reasons)})
    return out


def load_ticket_graph(conn, ticket_ids=None):
    """Load tickets with all their children as python-typed dicts (optionally for specific ticket ids)."""
    def fetch(table, where="", params=()):
        return [to_py(r, table) for r in conn.execute("SELECT * FROM %s %s" % (table, where), params)]
    if ticket_ids is None:
        w, p = "", ()
    else:
        marks = ",".join("?" * len(ticket_ids))
        w, p = "WHERE ticket_id IN (%s)" % marks, tuple(ticket_ids)
    tickets = fetch("ticket", w, p)
    msgs, evs, asg, slas = fetch("message", w, p), fetch("ticket_event", w, p), fetch("assignment", w, p), fetch("sla", w, p)
    mids = {m["message_id"] for m in msgs}
    links = [l for l in fetch("message_article_link") if l["message_id"] in mids] if ticket_ids is not None else fetch("message_article_link")
    by = lambda rows: _group(rows, "ticket_id")
    links_by_ticket = defaultdict(list)
    m2t = {m["message_id"]: m["ticket_id"] for m in msgs}
    for l in links:
        links_by_ticket[m2t[l["message_id"]]].append(l)
    return tickets, by(msgs), links_by_ticket, by(evs), by(asg), {s["ticket_id"]: s for s in slas}


def _group(rows, key):
    d = defaultdict(list)
    for r in rows:
        d[r[key]].append(r)
    return d


def audit_database(conn, now, ref=None, ticket_ids=None):
    ref = ref or Reference.from_db(conn)
    tickets, msgs, links, evs, asg, slas = load_ticket_graph(conn, ticket_ids)
    findings = []
    for t in tickets:
        tid = t["ticket_id"]
        findings += findings_for_ticket(ref, t, msgs[tid], links[tid], evs[tid], asg[tid], slas[tid], now)
    return findings
