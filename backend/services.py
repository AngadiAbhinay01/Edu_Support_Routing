"""APPLICATION TIER: business rules, validation and workflow.

Everything that decides something (classify, prioritise, route, answer from the knowledge base, escalate, enforce the
life-cycle) lives here and is expressed through the shared pure rules in `edu_support`.  HTTP concerns are in api.py,
SQL is in repository.py.
"""
import json
import re
import threading
from datetime import datetime, date, timedelta

from edu_support import config as C
from edu_support import audit, rules, evaluation
from edu_support.bizhours import add_business_hours, business_hours_between
from . import repository as repo
from .errors import ApiError, bad, conflict, not_found, forbidden

REQ_ID = re.compile(r"^REQ-\d{6}$")
STF_ID = re.compile(r"^STF-\d{4}$")
TKT_ID = re.compile(r"^TKT-2026-\d{6}$")
CHANNELS = ("portal", "email", "phone", "walk_in")
RESOLUTION_CODES = ("answered_from_kb", "resolved_by_staff", "resolved_by_escalation", "no_response_closed")
STAFF_MSG_TYPES = ("answer", "clarification_request", "internal_note")
REQUESTER_MSG_TYPES = ("followup", "confirmation", "clarification_reply")


class Clock:
    """Injectable clock (tests and demos can freeze time with APP_NOW='YYYY-MM-DD HH:MM:SS')."""

    def __init__(self, fixed=None):
        self.fixed = fixed

    def now(self):
        return (self.fixed or datetime.now()).replace(microsecond=0)


# ---------------------------------------------------------------------------------------------------------
# validation helpers
# ---------------------------------------------------------------------------------------------------------
def need_dict(payload):
    if not isinstance(payload, dict):
        raise ApiError(400, "INVALID_BODY", "request body must be a JSON object")
    return payload


def clean_text(payload, field, lo, hi, errors, required=True):
    v = payload.get(field)
    if v is None:
        if required:
            errors.append({"field": field, "message": "is required"})
        return None
    if not isinstance(v, str):
        errors.append({"field": field, "message": "must be a string"})
        return None
    v = v.replace("\x00", "").strip()
    if len(v) < lo or len(v) > hi:
        errors.append({"field": field, "message": "length must be between %d and %d characters (got %d)" % (lo, hi, len(v))})
        return None
    return v


def norm_text(s):
    return " ".join((s or "").lower().split())


def parse_date_field(v, field, errors):
    if v in (None, ""):
        return None
    if not isinstance(v, str):
        errors.append({"field": field, "message": "must be an ISO date string YYYY-MM-DD"})
        return None
    try:
        return datetime.strptime(v, C.FMT_D).date()
    except ValueError:
        errors.append({"field": field, "message": "must be a valid ISO date YYYY-MM-DD"})
        return None


class Services:
    def __init__(self, db_path, gt_dir=None, clock=None):
        from edu_support import db
        self.db_path = db_path
        self.gt_dir = gt_dir
        self.clock = clock or Clock()
        self.lock = threading.Lock()
        self._db = db
        self._ref = None
        self._version = 0
        self._cache = {}

    # ---- plumbing ------------------------------------------------------------------------------------------
    def conn(self):
        return self._db.connect(self.db_path, check_same_thread=False)

    def ref(self, conn):
        if self._ref is None:
            self._ref = audit.Reference.from_db(conn)
        return self._ref

    def _mutated(self):
        self._version += 1
        self._cache.clear()

    def _write(self, fn):
        """Run fn(conn) in one transaction under the global write lock."""
        with self.lock:
            conn = self.conn()
            try:
                conn.execute("BEGIN IMMEDIATE")
                out = fn(conn)
                conn.commit()
                self._mutated()
                return out
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

    def _read(self, fn):
        conn = self.conn()
        try:
            return fn(conn)
        finally:
            conn.close()

    # =====================================================================================================
    # reference / meta
    # =====================================================================================================
    def meta(self):
        def f(conn):
            return {
                "now": C.fmt_dt(self.clock.now()), "dataset_as_of": C.fmt_dt(C.AS_OF),
                "categories": repo.all_rows(conn, "category", "category_id"),
                "teams": repo.all_rows(conn, "team", "team_id"),
                "roles": repo.all_rows(conn, "role", "role_id"),
                "sla_policies": repo.all_rows(conn, "sla_policy", "sla_policy_id"),
                "statuses": C.STATUSES, "priorities": C.PRIORITIES, "channels": list(CHANNELS),
                "resolution_codes": list(RESOLUTION_CODES), "transitions": {str(k): sorted(v) for k, v in C.TRANSITIONS.items()},
                "escalation_reasons": C.ESCALATION_REASONS, "issue_types": C.ISSUE_TYPES,
                "counts": {t: repo.one(conn, "SELECT COUNT(*) FROM %s" % t) for t in ("ticket", "message", "knowledge_article", "requester", "staff")},
            }
        return self._read(f)

    def search_requesters(self, q, limit):
        def f(conn):
            like = "%" + (q or "").replace("%", "").replace("_", "") + "%"
            return repo.rows(conn, "SELECT requester_id, full_name, email, department, status, role_id FROM requester "
                                   "WHERE (requester_id LIKE ? OR full_name LIKE ? OR email LIKE ?) ORDER BY requester_id LIMIT ?",
                             (like, like, like, limit))
        return self._read(f)

    def list_staff(self, team_id):
        def f(conn):
            if team_id:
                return repo.rows(conn, "SELECT staff_id, full_name, team_id, role_id, active_to FROM staff WHERE team_id=? ORDER BY staff_id", (team_id,))
            return repo.rows(conn, "SELECT staff_id, full_name, team_id, role_id, active_to FROM staff ORDER BY staff_id")
        return self._read(f)

    # =====================================================================================================
    # routing preview (pure) and decision helpers
    # =====================================================================================================
    def decide(self, conn, subject, body, deadline, now):
        """Classification -> priority -> routing -> retrieval, without writing anything."""
        ref = self.ref(conn)
        text = subject + " " + body
        cls = rules.classify(text, ref.prepared)
        cat = ref.cats[cls["category_id"]]
        prio, reasons = rules.derive_priority(cat["default_priority"], now, deadline, text)
        rule = repo.routing_rule(conn, cat["category_id"], "initial", now.date())
        team_id = rule["team_id"] if rule else cat["default_team_id"]
        if repo.authorization(conn, team_id, cat["category_id"]) != "handle":
            raise ApiError(500, "ROUTING_CONFIG_ERROR", "routing rule targets a team that is not authorised for %s" % cat["category_id"])
        pol = conn.execute("SELECT * FROM sla_policy WHERE priority=?", (prio,)).fetchone()
        fr_due = add_business_hours(now, pol["first_response_hours"])
        res_due = add_business_hours(now, pol["resolution_hours"])
        mt = None if cls["ambiguous"] else rules.match_topic(text, ref.topics, cls["domain"])
        art = None
        if mt and mt["found"]:
            art = ref.article_at(mt["topic_key"], now)
        return {"classification": {k: cls[k] for k in ("ambiguous", "reason", "domain", "category_id", "confidence", "top_score", "margin", "domain_scores")},
                "category": {"category_id": cat["category_id"], "name": cat["name"], "requires_human_review": bool(cat["requires_human_review"])},
                "priority": prio, "priority_reasons": reasons, "team_id": team_id, "rule_id": rule["rule_id"] if rule else None,
                "sla": {"policy": pol["sla_policy_id"], "first_response_due": C.fmt_dt(fr_due), "resolution_due": C.fmt_dt(res_due),
                        "first_response_hours": pol["first_response_hours"], "resolution_hours": pol["resolution_hours"]},
                "retrieval": None if mt is None else {"found": mt["found"], "topic_key": mt["topic_key"], "coverage": mt["coverage"],
                                                      "article_id": art["article_id"] if art else None,
                                                      "version_no": art["version_no"] if art else None},
                "next_action": ("clarify (ambiguous request)" if cls["ambiguous"] else
                                "escalate (no applicable policy article)" if not (mt and mt["found"]) else
                                "answer from knowledge base" + (" then escalate for a human decision" if cat["requires_human_review"] else ""))}

    def route_preview(self, payload):
        payload = need_dict(payload)
        errors = []
        subject = clean_text(payload, "subject", 5, 200, errors)
        body = clean_text(payload, "body", 10, 5000, errors)
        now = self.clock.now()
        deadline = parse_date_field(payload.get("deadline_date"), "deadline_date", errors)
        self._check_deadline(deadline, now, errors)
        if errors:
            raise bad("VALIDATION_FAILED", "request is invalid", errors)
        return self._read(lambda conn: self.decide(conn, subject, body, deadline, now))

    @staticmethod
    def _check_deadline(deadline, now, errors):
        if deadline is not None:
            if deadline < now.date():
                errors.append({"field": "deadline_date", "message": "must not be in the past"})
            elif deadline > now.date() + timedelta(days=365):
                errors.append({"field": "deadline_date", "message": "must be within one year"})

    # =====================================================================================================
    # create ticket
    # =====================================================================================================
    def create_ticket(self, payload):
        payload = need_dict(payload)
        errors = []
        rid = payload.get("requester_id")
        if not isinstance(rid, str) or not REQ_ID.match(rid):
            errors.append({"field": "requester_id", "message": "must look like REQ-000123"})
        subject = clean_text(payload, "subject", 5, 200, errors)
        body = clean_text(payload, "body", 10, 5000, errors)
        channel = payload.get("channel", "portal")
        if channel not in CHANNELS:
            errors.append({"field": "channel", "message": "must be one of %s" % ", ".join(CHANNELS)})
        now = self.clock.now()
        deadline = parse_date_field(payload.get("deadline_date"), "deadline_date", errors)
        self._check_deadline(deadline, now, errors)
        if errors:
            raise bad("VALIDATION_FAILED", "request is invalid", errors)

        def f(conn):
            req = repo.get(conn, "requester", "requester_id", rid)
            if not req:
                raise not_found("requester", rid)
            role = repo.get(conn, "role", "role_id", req["role_id"])
            if not role["can_raise_ticket"]:
                raise forbidden("ROLE_CANNOT_RAISE", "role %s may not raise tickets" % req["role_id"])
            today = now.date()
            if C.parse_d(req["active_from"]) > today or (req["active_to"] and C.parse_d(req["active_to"]) < today):
                raise forbidden("REQUESTER_INACTIVE", "requester %s is not active on %s" % (rid, today))
            since = C.fmt_dt(now - timedelta(hours=24))
            for old in repo.recent_tickets_of(conn, rid, since):
                if norm_text(old["subject"]) == norm_text(subject) and norm_text(old["body"]) == norm_text(body):
                    raise conflict("DUPLICATE_TICKET", "an identical ticket was already submitted in the last 24 hours", {"ticket_id": old["ticket_id"]})
            d = self.decide(conn, subject, body, deadline, now)
            tid = repo.next_ticket_id(conn)
            term = repo.term_for(conn, today)
            team_id = d["team_id"]
            staff = repo.active_staff(conn, team_id, today)
            if not staff:
                raise ApiError(503, "NO_STAFF_AVAILABLE", "no active staff in team %s" % team_id)
            st = staff[0]
            cat_id = d["category"]["category_id"]
            repo.insert(conn, "ticket", {"ticket_id": tid, "requester_id": rid, "term_id": term["term_id"], "category_id": cat_id,
                                         "priority": d["priority"], "status": "assigned", "channel": channel, "subject": subject, "body": body,
                                         "deadline_date": deadline, "created_at": now, "updated_at": now, "current_team_id": team_id})
            self._event(conn, tid, "created", None, "new", now, "requester", rid)
            self._event(conn, tid, "triaged", "new", "triaged", now, "system", None,
                        {"rule": "KEYWORD-ROUTER-v1", "category": cat_id, "domain": d["classification"]["domain"], "ambiguous": d["classification"]["ambiguous"],
                         "reason": d["classification"]["reason"], "confidence": d["classification"]["confidence"],
                         "domain_scores": d["classification"]["domain_scores"], "priority": d["priority"], "priority_reasons": d["priority_reasons"]})
            self._assignment(conn, tid, team_id, st["staff_id"], "initial", cat_id, d["rule_id"], now, "system")
            self._event(conn, tid, "assigned", "triaged", "assigned", now, "system", None, {"team": team_id, "staff": st["staff_id"], "rule": d["rule_id"]})
            self._message(conn, tid, "question", now, ("requester", rid), body)
            if channel == "portal":
                self._message(conn, tid, "acknowledgement", now, ("system", None),
                              "Thanks for contacting Student & Faculty Support. Request %s was received, categorised as '%s' with %s priority. "
                              "First response expected within %g business hours." % (tid, d["category"]["name"], d["priority"], d["sla"]["first_response_hours"]))
            repo.insert(conn, "sla", {"sla_id": "SLA-" + tid, "ticket_id": tid, "sla_policy_id": d["sla"]["policy"], "priority": d["priority"],
                                      "clock_mode": "business", "clock_start": now, "first_response_due": d["sla"]["first_response_due"],
                                      "resolution_due": d["sla"]["resolution_due"], "first_response_at": None, "resolved_at": None,
                                      "first_response_status": "pending", "resolution_status": "pending",
                                      "first_response_business_hours": None, "resolution_business_hours": None})
            return tid, d
        tid, decision = self._write(f)
        out = self.get_ticket(tid)
        out["decision"] = decision
        return out

    # ---- row writers -------------------------------------------------------------------------------------
    def _event(self, conn, tid, etype, frm, to, at, actor_type, actor_id, details=None):
        seq = repo.next_seq(conn, "ticket_event", tid)
        repo.insert(conn, "ticket_event", {"event_id": "EVT-%s-%03d" % (tid, seq), "ticket_id": tid, "seq_no": seq, "event_type": etype,
                                           "from_status": frm, "to_status": to, "event_at": at, "actor_type": actor_type, "actor_id": actor_id,
                                           "details": details or None})
        if frm != to or etype in ("recategorized", "reassigned"):
            pass
        conn.execute("UPDATE ticket SET status=?, updated_at=? WHERE ticket_id=?", (to, C.fmt_dt(at), tid))

    def _message(self, conn, tid, mtype, at, sender, body, internal=False, cites=None):
        seq = repo.next_seq(conn, "message", tid)
        mid = "MSG-%s-%03d" % (tid, seq)
        st, sid = sender
        repo.insert(conn, "message", {"message_id": mid, "ticket_id": tid, "seq_no": seq, "sender_type": st,
                                      "requester_id": sid if st == "requester" else None, "staff_id": sid if st == "staff" else None,
                                      "message_type": mtype, "is_internal": 1 if internal else 0, "body": body, "created_at": at})
        for art, score in (cites or []):
            repo.insert(conn, "message_article_link", {"message_id": mid, "article_id": art["article_id"], "cited_version_no": art["version_no"],
                                                       "relevance_score": round(score, 2), "citation_role": "primary"})
        return mid

    def _assignment(self, conn, tid, team_id, staff_id, atype, cat_id, rule_id, at, by):
        conn.execute("UPDATE assignment SET unassigned_at=? WHERE ticket_id=? AND unassigned_at IS NULL", (C.fmt_dt(at), tid))
        n = repo.next_assignment_no(conn, tid)
        repo.insert(conn, "assignment", {"assignment_id": "ASG-%s-%02d" % (tid, n), "ticket_id": tid, "team_id": team_id, "staff_id": staff_id,
                                         "assignment_type": atype, "category_id_at_assignment": cat_id, "routing_rule_id": rule_id,
                                         "assigned_at": at, "unassigned_at": None, "assigned_by": by})
        conn.execute("UPDATE ticket SET current_team_id=? WHERE ticket_id=?", (team_id, tid))

    # =====================================================================================================
    # read side
    # =====================================================================================================
    def list_tickets(self, f, page, size):
        return self._read(lambda conn: repo.list_tickets(conn, f, page, size))

    def get_ticket(self, tid):
        def f(conn):
            if not TKT_ID.match(tid):
                raise ApiError(400, "BAD_ID", "ticket id must look like TKT-2026-000123")
            g = repo.ticket_graph(conn, tid)
            if g is None:
                raise not_found("ticket", tid)
            now = self.clock.now()
            ref = self.ref(conn)
            tick, msgs = self._py("ticket", g["ticket"]), [self._py("message", m) for m in g["messages"]]
            sla = self._py("sla", g["sla"])
            g["expected_escalation"] = audit.expected_escalation(ref, tick, msgs, sla, now)
            links = [self._py("message_article_link", {k: l[k] for k in ("message_id", "article_id", "cited_version_no", "relevance_score", "citation_role")}) for l in g["citations"]]
            events = [self._py("ticket_event", {**e, "details": json.dumps(e["details"]) if e["details"] else None}) for e in g["events"]]
            asgs = [self._py("assignment", {k: a[k] for k in dictionary_cols("assignment")}) for a in g["assignments"]]
            g["audit_findings"] = audit.findings_for_ticket(ref, tick, msgs, links, events, asgs, sla, now)
            for fnd in g["audit_findings"]:
                fnd["detail"] = str(fnd["detail"])
            # per-citation effectiveness at the message date (what a reviewer needs to see)
            by_msg = {m["message_id"]: m for m in g["messages"]}
            for c in g["citations"]:
                d = C.parse_dt(by_msg[c["message_id"]]["created_at"]).date()
                ef, et = C.parse_d(c["effective_from"]), C.parse_d(c["effective_to"]) if c["effective_to"] else None
                c["effective_at_message_date"] = ef <= d and (et is None or d <= et)
            return g
        return self._read(f)

    @staticmethod
    def _py(table, row):
        return audit.to_py(row, table)

    def suggested_answer(self, tid):
        def f(conn):
            g = repo.ticket_graph(conn, tid)
            if g is None:
                raise not_found("ticket", tid)
            ref = self.ref(conn)
            now = self.clock.now()
            text = g["ticket"]["subject"] + " " + " ".join(m["body"] for m in g["messages"] if m["sender_type"] == "requester")
            cls = rules.classify(text, ref.prepared)
            req = g["requester"]
            first = req["full_name"].split()[0]
            if cls["ambiguous"]:
                return {"action": "clarify", "message_type": "clarification_request", "citations": [],
                        "body": "Hello %s, thank you for contacting us. Could you tell us exactly what you need help with and which office or system it relates to?" % first}
            mt = rules.match_topic(text, ref.topics, cls["domain"])
            if not mt["found"]:
                return {"action": "escalate", "message_type": "answer", "citations": [], "retrieval": mt,
                        "body": "Hello %s, thank you for your request. We could not find a published policy article that covers your situation, so we are asking a senior colleague to review it." % first}
            art = ref.article_at(mt["topic_key"], now)
            if art is None:
                raise conflict("NO_EFFECTIVE_ARTICLE", "no version of topic %s is in force on %s" % (mt["topic_key"], now.date()))
            pol = repo.get(conn, "policy_document", "policy_id", art["policy_id"])
            fact = art["body"].split(": ", 1)[1]
            body = ("Hello %s,\n\nThanks for your question about %s. According to %s (%s): %s\n\nSource: %s (version %d)."
                    % (first, art["title"].lower(), pol["title"], art["policy_id"], fact, art["article_id"], art["version_no"]))
            return {"action": "answer", "message_type": "answer", "body": body, "retrieval": mt,
                    "citations": [{"article_id": art["article_id"], "version_no": art["version_no"], "title": art["title"],
                                   "effective_from": C.fmt_d(art["effective_from"]), "effective_to": C.fmt_d(art["effective_to"]) if art["effective_to"] else None}]}
        return self._read(f)

    # =====================================================================================================
    # messages
    # =====================================================================================================
    def add_message(self, tid, payload):
        payload = need_dict(payload)
        errors = []
        stype = payload.get("sender_type")
        if stype not in ("requester", "staff"):
            errors.append({"field": "sender_type", "message": "must be 'requester' or 'staff'"})
        sid = payload.get("sender_id")
        if stype == "requester" and not (isinstance(sid, str) and REQ_ID.match(sid)):
            errors.append({"field": "sender_id", "message": "must look like REQ-000123"})
        if stype == "staff" and not (isinstance(sid, str) and STF_ID.match(sid)):
            errors.append({"field": "sender_id", "message": "must look like STF-0001"})
        body = clean_text(payload, "body", 1, 5000, errors)
        mtype = payload.get("message_type")
        allowed = STAFF_MSG_TYPES if stype == "staff" else REQUESTER_MSG_TYPES
        if stype in ("requester", "staff") and mtype is not None and mtype not in allowed:
            errors.append({"field": "message_type", "message": "must be one of %s for a %s" % (", ".join(allowed), stype)})
        arts = payload.get("article_ids", [])
        if not isinstance(arts, list) or len(arts) > 5 or not all(isinstance(a, str) for a in arts):
            errors.append({"field": "article_ids", "message": "must be a list of at most 5 article ids"})
            arts = []
        if errors:
            raise bad("VALIDATION_FAILED", "request is invalid", errors)
        if TKT_ID.match(tid) is None:
            raise ApiError(400, "BAD_ID", "ticket id must look like TKT-2026-000123")
        now = self.clock.now()

        def f(conn):
            t = repo.get(conn, "ticket", "ticket_id", tid)
            if not t:
                raise not_found("ticket", tid)
            ref = self.ref(conn)
            if stype == "requester":
                self._requester_message(conn, t, sid, mtype, body, now)
            else:
                self._staff_message(conn, t, sid, mtype or "answer", body, arts, payload, now, ref)
            self._auto_escalate(conn, tid, now)
        self._write(f)
        return self.get_ticket(tid)

    def _requester_message(self, conn, t, rid, mtype, body, now):
        if rid != t["requester_id"]:
            raise forbidden("NOT_TICKET_OWNER", "only the requester of the ticket may post requester messages")
        status, tid = t["status"], t["ticket_id"]
        if status == "closed":
            last = conn.execute("SELECT MAX(event_at) FROM ticket_event WHERE ticket_id=? AND event_type='closed'", (tid,)).fetchone()[0]
            if C.parse_dt(last) + timedelta(days=C.REOPEN_WINDOW_DAYS) < now:
                raise conflict("REOPEN_WINDOW_EXPIRED", "ticket was closed more than %d days ago; please open a new ticket" % C.REOPEN_WINDOW_DAYS)
        if status in ("resolved", "closed"):
            self._event(conn, tid, "reopened", status, "in_progress", now, "requester", rid)
            self._message(conn, tid, "reopen_request", now, ("requester", rid), body)
            return
        if mtype == "confirmation" and not conn.execute("SELECT 1 FROM message WHERE ticket_id=? AND message_type='answer'", (tid,)).fetchone():
            raise conflict("NOTHING_TO_CONFIRM", "there is no answer to confirm yet")
        last_pub = conn.execute("SELECT message_type FROM message WHERE ticket_id=? AND sender_type='staff' AND is_internal=0 ORDER BY seq_no DESC LIMIT 1", (tid,)).fetchone()
        if mtype is None:
            mtype = "clarification_reply" if last_pub and last_pub[0] == "clarification_request" and status == "awaiting_requester" else "followup"
        if mtype == "clarification_reply" and not conn.execute("SELECT 1 FROM message WHERE ticket_id=? AND message_type='clarification_request'", (tid,)).fetchone():
            raise conflict("NO_CLARIFICATION_REQUESTED", "no clarification was requested on this ticket")
        self._message(conn, tid, mtype, now, ("requester", rid), body)
        if status == "awaiting_requester":
            self._event(conn, tid, "requester_replied", status, "in_progress", now, "requester", rid)
        if mtype == "clarification_reply":
            self._reclassify(conn, t, now)

    def _reclassify(self, conn, t, now):
        """After a clarification reply: re-run the router on all requester text; re-route when it became unambiguous."""
        tid = t["ticket_id"]
        ref = self.ref(conn)
        cur = repo.get(conn, "ticket", "ticket_id", tid)
        text = cur["subject"] + " " + " ".join(r[0] for r in conn.execute("SELECT body FROM message WHERE ticket_id=? AND sender_type='requester' ORDER BY seq_no", (tid,)))
        cls = rules.classify(text, ref.prepared)
        if cls["ambiguous"] or cls["category_id"] == cur["category_id"]:
            return
        old = cur["category_id"]
        conn.execute("UPDATE ticket SET category_id=? WHERE ticket_id=?", (cls["category_id"], tid))
        status = repo.get(conn, "ticket", "ticket_id", tid)["status"]
        self._event(conn, tid, "recategorized", status, status, now, "system", None, {"from_category": old, "to_category": cls["category_id"], "domain_scores": cls["domain_scores"]})
        if conn.execute("SELECT 1 FROM ticket_event WHERE ticket_id=? AND event_type='escalated'", (tid,)).fetchone():
            return
        rule = repo.routing_rule(conn, cls["category_id"], "initial", now.date())
        team = rule["team_id"]
        staff = repo.active_staff(conn, team, now.date())[0]
        self._assignment(conn, tid, team, staff["staff_id"], "reassignment", cls["category_id"], rule["rule_id"], now, "system")
        self._event(conn, tid, "reassigned", status, status, now, "system", None, {"team": team, "staff": staff["staff_id"]})

    def _check_staff(self, conn, t, sid, now, need_team=True):
        s = repo.get(conn, "staff", "staff_id", sid)
        if not s:
            raise not_found("staff", sid)
        today = now.date()
        if C.parse_d(s["active_from"]) > today or (s["active_to"] and C.parse_d(s["active_to"]) < today):
            raise forbidden("STAFF_INACTIVE", "staff member %s is not active" % sid)
        if need_team and s["team_id"] != t["current_team_id"]:
            raise forbidden("NOT_ASSIGNED_TEAM", "staff %s (team %s) does not belong to the team currently handling the ticket (%s)" % (sid, s["team_id"], t["current_team_id"]))
        return s

    def _staff_message(self, conn, t, sid, mtype, body, article_ids, payload, now, ref):
        tid, status = t["ticket_id"], t["status"]
        self._check_staff(conn, t, sid, now)
        if status in ("resolved", "closed"):
            raise conflict("TICKET_NOT_OPEN", "ticket is %s; staff cannot post new messages" % status)
        internal = mtype == "internal_note"
        if payload.get("is_internal") not in (None, internal):
            raise bad("INTERNAL_FLAG_MISMATCH", "only internal_note messages may be internal, and they must be internal")
        cites = []
        if mtype == "answer":
            cites = self._validate_answer(conn, t, body, article_ids, now, ref)
        elif article_ids:
            raise bad("CITATION_NOT_ALLOWED", "only 'answer' messages may cite knowledge articles")
        if status in ("assigned", "escalated"):
            self._event(conn, tid, "started", status, "in_progress", now, "staff", sid)
        self._message(conn, tid, mtype, now, ("staff", sid), body, internal, cites)
        public = not internal
        sla = repo.get(conn, "sla", "ticket_id", tid)
        if public and sla["first_response_at"] is None and mtype in ("answer", "clarification_request"):
            due = C.parse_dt(sla["first_response_due"])
            conn.execute("UPDATE sla SET first_response_at=?, first_response_status=?, first_response_business_hours=? WHERE ticket_id=?",
                         (C.fmt_dt(now), "met" if now <= due else "breached", business_hours_between(C.parse_dt(t["created_at"]), now), tid))
        cur = repo.get(conn, "ticket", "ticket_id", tid)["status"]
        if mtype == "clarification_request" or (mtype == "answer" and payload.get("awaiting_requester", True) and cur == "in_progress"):
            if cur == "in_progress":
                self._event(conn, tid, "awaiting_requester", "in_progress", "awaiting_requester", now, "staff", sid)

    def _validate_answer(self, conn, t, body, article_ids, now, ref):
        """The three controls that prevent the injected anomalies from happening in the live system."""
        cites, texts = [], []
        for aid in article_ids:
            a = ref.articles.get(aid)
            if not a:
                raise bad("UNKNOWN_ARTICLE", "article %s does not exist" % aid)
            d = now.date()
            if a["effective_from"] > d or (a["effective_to"] is not None and a["effective_to"] < d):
                cur = ref.article_at(a["topic_key"], now)
                raise bad("ARTICLE_NOT_EFFECTIVE", "article %s (version %d) is not in force on %s" % (aid, a["version_no"], d),
                          {"in_force": cur["article_id"] if cur else None, "valid_from": C.fmt_d(a["effective_from"]),
                           "valid_to": C.fmt_d(a["effective_to"]) if a["effective_to"] else None})
            cites.append((a, 1.0))
            texts.append(a["title"] + " " + a["body"])
        if not cites:
            text = t["subject"] + " " + " ".join(r[0] for r in conn.execute("SELECT body FROM message WHERE ticket_id=? AND sender_type='requester'", (t["ticket_id"],)))
            cls = rules.classify(text, ref.prepared)
            if not cls["ambiguous"]:
                mt = rules.match_topic(text, ref.topics, cls["domain"])
                if mt["found"]:
                    art = ref.article_at(mt["topic_key"], now)
                    raise bad("MISSING_CITATION", "an applicable policy article exists; cite it", {"article_id": art["article_id"] if art else None})
        bad_numbers = rules.unsupported_numbers(body, texts)
        if bad_numbers:
            raise bad("UNSUPPORTED_CLAIM", "the answer states numeric facts that no cited source supports", {"numbers": bad_numbers})
        # citations must support the right ticket domain (an IT answer may not cite a financial-aid article)
        cat = ref.cats[t["category_id"]]
        for a, _ in cites:
            if cat["domain"] not in ("GEN",) and a["topic_key"].split("-")[0] != cat["domain"]:
                raise bad("CITATION_DOMAIN_MISMATCH", "article %s belongs to domain %s but the ticket is %s" % (a["article_id"], a["topic_key"].split("-")[0], cat["domain"]))
        return cites

    # =====================================================================================================
    # transitions, assignment, escalation, feedback
    # =====================================================================================================
    def transition(self, tid, payload):
        payload = need_dict(payload)
        errors = []
        to = payload.get("to_status")
        if to not in C.STATUSES:
            errors.append({"field": "to_status", "message": "must be one of %s" % ", ".join(C.STATUSES)})
        sid = payload.get("actor_id")
        if not (isinstance(sid, str) and STF_ID.match(sid)):
            errors.append({"field": "actor_id", "message": "must be a staff id like STF-0001"})
        code = payload.get("resolution_code")
        if to == "resolved" and code not in RESOLUTION_CODES:
            errors.append({"field": "resolution_code", "message": "required when resolving; one of %s" % ", ".join(RESOLUTION_CODES)})
        note = clean_text(payload, "reason", 3, 500, errors, required=False)
        if errors:
            raise bad("VALIDATION_FAILED", "request is invalid", errors)
        now = self.clock.now()

        def f(conn):
            t = repo.get(conn, "ticket", "ticket_id", tid)
            if not t:
                raise not_found("ticket", tid)
            frm = t["status"]
            self._check_staff(conn, t, sid, now)
            if to == frm or to not in C.TRANSITIONS[frm]:
                raise conflict("ILLEGAL_TRANSITION", "cannot move a ticket from %s to %s" % (frm, to), {"allowed": sorted(C.TRANSITIONS[frm])})
            if frm in ("resolved", "closed") and to == "in_progress":
                raise conflict("REOPEN_VIA_REQUESTER", "only the requester can reopen a resolved or closed ticket")
            if to == "closed" and frm != "resolved":
                raise conflict("RESOLVE_FIRST", "only resolved tickets can be closed")
            if to == "escalated":
                if not note:
                    raise bad("REASON_REQUIRED", "a reason is required for a manual escalation")
                self._do_escalation(conn, t, ["MANUAL_REQUEST"], now, actor=sid, note=note)
                return
            if to == "resolved":
                n_resp = conn.execute("SELECT COUNT(*) FROM message WHERE ticket_id=? AND sender_type='staff' AND is_internal=0 AND message_type IN ('answer','clarification_request')", (tid,)).fetchone()[0]
                if n_resp == 0:
                    raise conflict("NO_RESPONSE_YET", "a ticket cannot be resolved before a public staff response was sent")
                self._auto_escalate_check_only(conn, t, now)
                self._event(conn, tid, "resolved", frm, "resolved", now, "staff", sid, {"resolution_code": code})
                self._record_resolution(conn, t, code, now)
                return
            if to == "closed":
                self._event(conn, tid, "closed", frm, "closed", now, "staff", sid, {"reason": note} if note else None)
                conn.execute("UPDATE assignment SET unassigned_at=? WHERE ticket_id=? AND unassigned_at IS NULL", (C.fmt_dt(now), tid))
                return
            self._event(conn, tid, "started" if frm in ("escalated", "assigned") else ("awaiting_requester" if to == "awaiting_requester" else "requester_replied"),
                        frm, to, now, "staff", sid, {"reason": note} if note else None)
        self._write(f)
        return self.get_ticket(tid)

    def _auto_escalate_check_only(self, conn, t, now):
        """Resolution guard: refuse to resolve a ticket whose escalation rules fired but which was never escalated."""
        g = repo.ticket_graph(conn, t["ticket_id"])
        reasons = audit.expected_escalation(self.ref(conn), self._py("ticket", g["ticket"]), [self._py("message", m) for m in g["messages"]], self._py("sla", g["sla"]), now)
        if reasons and not any(e["event_type"] == "escalated" for e in g["events"]):
            raise conflict("ESCALATION_REQUIRED", "escalation rules fired (%s); escalate before resolving" % ", ".join(reasons), {"reasons": reasons})

    def _record_resolution(self, conn, t, code, now):
        tid = t["ticket_id"]
        created = C.parse_dt(t["created_at"])
        reopen = conn.execute("SELECT COUNT(*) FROM ticket_event WHERE ticket_id=? AND event_type='reopened'", (tid,)).fetchone()[0]
        existing = repo.get(conn, "resolution_feedback", "ticket_id", tid)
        row = {"resolution_code": code, "resolved_at": now, "resolution_calendar_hours": round((now - created).total_seconds() / 3600, 2),
               "resolution_business_hours": business_hours_between(created, now), "reopen_count": reopen}
        if existing:
            repo.update(conn, "resolution_feedback", "ticket_id", tid, {**row, "csat": None, "answer_helpful": None, "comment": None, "feedback_at": None})
        else:
            repo.insert(conn, "resolution_feedback", {"feedback_id": "FB-" + tid, "ticket_id": tid, **row})
        sla = repo.get(conn, "sla", "ticket_id", tid)
        due = C.parse_dt(sla["resolution_due"])
        conn.execute("UPDATE sla SET resolved_at=?, resolution_status=?, resolution_business_hours=? WHERE ticket_id=?",
                     (C.fmt_dt(now), "met" if now <= due else "breached", row["resolution_business_hours"], tid))

    def _do_escalation(self, conn, t, reasons, now, actor=None, note=None):
        tid = t["ticket_id"]
        cur = repo.get(conn, "ticket", "ticket_id", tid)
        if conn.execute("SELECT 1 FROM ticket_event WHERE ticket_id=? AND event_type='escalated'", (tid,)).fetchone():
            raise conflict("ALREADY_ESCALATED", "ticket was already escalated")
        if cur["status"] in ("resolved", "closed", "escalated", "new", "triaged"):
            raise conflict("ILLEGAL_TRANSITION", "cannot escalate a ticket in status %s" % cur["status"])
        rule = repo.routing_rule(conn, cur["category_id"], "escalation", now.date())
        team = rule["team_id"]
        if repo.authorization(conn, team, cur["category_id"]) not in ("escalation", "handle"):
            raise ApiError(500, "ROUTING_CONFIG_ERROR", "escalation team %s is not authorised for %s" % (team, cur["category_id"]))
        staff = repo.active_staff(conn, team, now.date())
        if not staff:
            raise ApiError(503, "NO_STAFF_AVAILABLE", "no active staff in escalation team %s" % team)
        self._assignment(conn, tid, team, staff[0]["staff_id"], "escalation", cur["category_id"], rule["rule_id"], now, "system" if actor is None else "staff")
        self._event(conn, tid, "escalated", cur["status"], "escalated", now, "system" if actor is None else "staff", actor,
                    {"reasons": reasons, "to_team": team, "category": cur["category_id"], **({"note": note} if note else {})})
        labels = "; ".join(C.ESCALATION_REASONS.get(r, "Escalated on request of the handling team") for r in reasons)
        team_name = repo.get(conn, "team", "team_id", team)["team_name"]
        self._message(conn, tid, "escalation_notice", now, ("system", None), "Your request %s has been escalated to %s for further review. Reason: %s." % (tid, team_name, labels))

    def _auto_escalate(self, conn, tid, now):
        g = repo.ticket_graph(conn, tid)
        t = g["ticket"]
        if t["status"] in ("resolved", "closed", "escalated", "new", "triaged"):
            return None
        if any(e["event_type"] == "escalated" for e in g["events"]):
            return None
        reasons = audit.expected_escalation(self.ref(conn), self._py("ticket", t), [self._py("message", m) for m in g["messages"]], self._py("sla", g["sla"]), now)
        if reasons:
            self._do_escalation(conn, t, reasons, now)
        return reasons

    def assign(self, tid, payload):
        payload = need_dict(payload)
        errors = []
        team = payload.get("team_id")
        if not isinstance(team, str) or not re.match(r"^TEAM-[A-Z]+$", team):
            errors.append({"field": "team_id", "message": "must look like TEAM-IT"})
        actor = payload.get("actor_id")
        if not (isinstance(actor, str) and STF_ID.match(actor)):
            errors.append({"field": "actor_id", "message": "must be a staff id like STF-0001"})
        sid = payload.get("staff_id")
        if sid is not None and not (isinstance(sid, str) and STF_ID.match(sid)):
            errors.append({"field": "staff_id", "message": "must be a staff id like STF-0001"})
        reason = clean_text(payload, "reason", 3, 500, errors)
        if errors:
            raise bad("VALIDATION_FAILED", "request is invalid", errors)
        now = self.clock.now()

        def f(conn):
            t = repo.get(conn, "ticket", "ticket_id", tid)
            if not t:
                raise not_found("ticket", tid)
            self._check_staff(conn, t, actor, now)
            if t["status"] in ("resolved", "closed"):
                raise conflict("TICKET_NOT_OPEN", "ticket is %s" % t["status"])
            if not repo.get(conn, "team", "team_id", team):
                raise not_found("team", team)
            level = repo.authorization(conn, team, t["category_id"])
            if level is None:
                raise bad("UNAUTHORIZED_TEAM", "team %s is not authorised to handle category %s" % (team, t["category_id"]))
            if level != "handle":
                raise bad("ESCALATION_ONLY_TEAM", "team %s only receives escalations for %s; use the escalate transition" % (team, t["category_id"]))
            if team == t["current_team_id"] and not sid:
                raise conflict("ALREADY_ASSIGNED", "ticket is already handled by %s" % team)
            if sid:
                s = repo.get(conn, "staff", "staff_id", sid)
                if not s or s["team_id"] != team:
                    raise bad("STAFF_TEAM_MISMATCH", "staff %s is not a member of %s" % (sid, team))
                self._check_staff(conn, t, sid, now, need_team=False)
                chosen = sid
            else:
                cands = repo.active_staff(conn, team, now.date())
                if not cands:
                    raise ApiError(503, "NO_STAFF_AVAILABLE", "no active staff in %s" % team)
                chosen = cands[0]["staff_id"]
            self._assignment(conn, tid, team, chosen, "reassignment", t["category_id"], None, now, "staff")
            self._event(conn, tid, "reassigned", t["status"], t["status"], now, "staff", actor, {"team": team, "staff": chosen, "reason": reason})
        self._write(f)
        return self.get_ticket(tid)

    def feedback(self, tid, payload):
        payload = need_dict(payload)
        errors = []
        rid = payload.get("requester_id")
        if not (isinstance(rid, str) and REQ_ID.match(rid)):
            errors.append({"field": "requester_id", "message": "must look like REQ-000123"})
        csat = payload.get("csat")
        if isinstance(csat, bool) or not isinstance(csat, int) or not 1 <= csat <= 5:
            errors.append({"field": "csat", "message": "must be an integer from 1 to 5"})
        helpful = payload.get("answer_helpful")
        if helpful is not None and not isinstance(helpful, bool):
            errors.append({"field": "answer_helpful", "message": "must be true or false"})
        comment = clean_text(payload, "comment", 0, 1000, errors, required=False)
        if errors:
            raise bad("VALIDATION_FAILED", "request is invalid", errors)
        now = self.clock.now()

        def f(conn):
            t = repo.get(conn, "ticket", "ticket_id", tid)
            if not t:
                raise not_found("ticket", tid)
            if rid != t["requester_id"]:
                raise forbidden("NOT_TICKET_OWNER", "only the requester may rate the resolution")
            fb = repo.get(conn, "resolution_feedback", "ticket_id", tid)
            if t["status"] not in ("resolved", "closed") or not fb:
                raise conflict("NOT_RESOLVED", "feedback can only be given after the ticket was resolved")
            if fb["csat"] is not None:
                raise conflict("FEEDBACK_ALREADY_GIVEN", "feedback was already recorded for this ticket")
            repo.update(conn, "resolution_feedback", "ticket_id", tid, {"csat": csat, "answer_helpful": None if helpful is None else int(helpful),
                                                                      "comment": comment or None, "feedback_at": now})
        self._write(f)
        return self.get_ticket(tid)

    def sweep(self, payload):
        """Time-based rules: escalate overdue tickets (E1/E4/...), close resolved tickets after 7 days. dry_run by default."""
        payload = payload if isinstance(payload, dict) else {}
        dry = payload.get("dry_run", True)
        if not isinstance(dry, bool):
            raise bad("VALIDATION_FAILED", "dry_run must be true or false", [{"field": "dry_run", "message": "must be boolean"}])
        now = self.clock.now()

        def f(conn):
            ref = self.ref(conn)
            tickets, msgs, links, evs, asg, slas = audit.load_ticket_graph(conn)
            would_escalate, would_close = [], []
            for t in tickets:
                tid = t["ticket_id"]
                if t["status"] in ("new", "triaged", "resolved", "closed", "escalated"):
                    if t["status"] == "resolved":
                        res = [e for e in evs[tid] if e["event_type"] == "resolved"][-1]["event_at"]
                        if res + timedelta(days=C.AUTO_CLOSE_DAYS) <= now:
                            would_close.append(tid)
                    continue
                if any(e["event_type"] == "escalated" for e in evs[tid]):
                    continue
                reasons = audit.expected_escalation(ref, t, msgs[tid], slas[tid], now)
                if reasons:
                    would_escalate.append({"ticket_id": tid, "reasons": reasons})
            if not dry:
                for item in would_escalate:
                    t = repo.get(conn, "ticket", "ticket_id", item["ticket_id"])
                    self._do_escalation(conn, t, item["reasons"], now)
                for tid in would_close:
                    t = repo.get(conn, "ticket", "ticket_id", tid)
                    self._event(conn, tid, "closed", "resolved", "closed", now, "system", None)
                    conn.execute("UPDATE assignment SET unassigned_at=? WHERE ticket_id=? AND unassigned_at IS NULL", (C.fmt_dt(now), tid))
            return {"dry_run": dry, "now": C.fmt_dt(now), "escalate": would_escalate[:200], "escalate_count": len(would_escalate), "close_count": len(would_close)}
        return self._read(f) if dry else self._write(f)

    # =====================================================================================================
    # knowledge base / metrics / audit / evaluation
    # =====================================================================================================
    def list_articles(self, f, page, size):
        return self._read(lambda conn: repo.list_articles(conn, f, page, size))

    def get_article(self, article_id):
        def f(conn):
            a = repo.get(conn, "knowledge_article", "article_id", article_id)
            if not a:
                raise not_found("article", article_id)
            versions = repo.article_versions(conn, a["topic_key"])
            used = repo.rows(conn, "SELECT COUNT(DISTINCT message_id) AS n FROM message_article_link WHERE article_id=?", (article_id,))[0]["n"]
            return {"article": a, "versions": versions, "cited_by_messages": used}
        return self._read(f)

    def metrics(self):
        def f(conn):
            if "metrics" in self._cache:
                return self._cache["metrics"]
            q = lambda sql, p=(): repo.rows(conn, sql, p)
            one = lambda sql, p=(): repo.one(conn, sql, p)
            total = one("SELECT COUNT(*) FROM ticket")
            out = {
                "totals": {"tickets": total, "messages": one("SELECT COUNT(*) FROM message"), "articles": one("SELECT COUNT(*) FROM knowledge_article"),
                           "open_tickets": one("SELECT COUNT(*) FROM ticket WHERE status NOT IN ('resolved','closed')")},
                "by_status": q("SELECT status AS k, COUNT(*) AS n FROM ticket GROUP BY status ORDER BY n DESC"),
                "by_priority": q("SELECT priority AS k, COUNT(*) AS n FROM ticket GROUP BY priority"),
                "by_domain": q("SELECT c.domain AS k, COUNT(*) AS n FROM ticket t JOIN category c ON c.category_id=t.category_id GROUP BY c.domain ORDER BY n DESC"),
                "by_month": q("SELECT substr(created_at,1,7) AS k, COUNT(*) AS n FROM ticket GROUP BY 1 ORDER BY 1"),
                "by_team": q("SELECT tm.team_name AS k, COUNT(*) AS n FROM ticket t JOIN team tm ON tm.team_id=t.current_team_id GROUP BY tm.team_name ORDER BY n DESC"),
                "escalation": {"escalated_tickets": one("SELECT COUNT(DISTINCT ticket_id) FROM ticket_event WHERE event_type='escalated'"),
                               "reasons": q("SELECT je.value AS k, COUNT(*) AS n FROM ticket_event e, json_each(json_extract(e.details,'$.reasons')) je "
                                            "WHERE e.event_type='escalated' GROUP BY je.value ORDER BY n DESC")},
                "sla": {"first_response": q("SELECT first_response_status AS k, COUNT(*) AS n FROM sla GROUP BY 1"),
                        "resolution": q("SELECT resolution_status AS k, COUNT(*) AS n FROM sla GROUP BY 1"),
                        "avg_first_response_business_hours": one("SELECT ROUND(AVG(first_response_business_hours),2) FROM sla"),
                        "avg_resolution_business_hours": one("SELECT ROUND(AVG(resolution_business_hours),2) FROM sla"),
                        "by_priority": q("SELECT priority AS k, COUNT(*) AS n, ROUND(100.0*SUM(first_response_status='breached')/COUNT(*),1) AS fr_breach_pct, "
                                         "ROUND(100.0*SUM(resolution_status='breached')/COUNT(*),1) AS res_breach_pct FROM sla GROUP BY priority")},
                "feedback": {"avg_csat": one("SELECT ROUND(AVG(csat),2) FROM resolution_feedback"), "rated": one("SELECT COUNT(csat) FROM resolution_feedback"),
                             "by_code": q("SELECT resolution_code AS k, COUNT(*) AS n FROM resolution_feedback GROUP BY 1 ORDER BY n DESC"),
                             "csat_by_escalated": q("SELECT CASE WHEN EXISTS (SELECT 1 FROM ticket_event e WHERE e.ticket_id=f.ticket_id AND e.event_type='escalated') "
                                                    "THEN 'escalated' ELSE 'not escalated' END AS k, ROUND(AVG(csat),2) AS n FROM resolution_feedback f WHERE csat IS NOT NULL GROUP BY 1")},
                "knowledge": {"cited_answers": one("SELECT COUNT(DISTINCT message_id) FROM message_article_link"),
                              "by_article_status": q("SELECT a.status AS k, COUNT(*) AS n FROM message_article_link l JOIN knowledge_article a ON a.article_id=l.article_id GROUP BY 1")},
            }
            self._cache["metrics"] = out
            return out
        return self._read(f)

    def audit(self, as_of_now, issue_type, limit):
        def f(conn):
            now = self.clock.now() if as_of_now else C.AS_OF
            key = ("audit", now)
            if key not in self._cache:
                self._cache[key] = audit.audit_database(conn, now, self.ref(conn))
            fnd = self._cache[key]
            counts = {}
            for x in fnd:
                counts[x["issue_type"]] = counts.get(x["issue_type"], 0) + 1
            if issue_type:
                fnd = [x for x in fnd if x["issue_type"] == issue_type]
            return {"as_of": C.fmt_dt(now), "total": len(fnd), "counts": counts, "findings": [{**x, "detail": str(x["detail"])} for x in fnd[:limit]]}
        return self._read(f)

    def evaluation(self):
        if not self.gt_dir:
            raise ApiError(404, "NO_GROUND_TRUTH", "ground truth folder is not configured")

        def f(conn):
            if "evaluation" not in self._cache:
                self._cache["evaluation"] = evaluation.evaluate(conn, self.gt_dir)
            return self._cache["evaluation"]
        return self._read(f)


def dictionary_cols(table):
    from edu_support import dictionary
    return dictionary.columns(table)
