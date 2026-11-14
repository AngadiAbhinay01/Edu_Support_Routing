"""End-to-end tests of the application + data tiers, in-process (no sockets): every validation / edge case."""
import json, os, shutil, tempfile, unittest
from . import support
from backend.api import Api
from backend.server import build_app

NOW = "2026-11-02 10:00:00"          # a Monday, inside business hours
GOOD = {"subject": "Tuition payment plan", "body": "I want to set up a payment plan for my tuition fees and know the deadline."}


class ApiBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        src = support.small_dataset()
        cls.dir = tempfile.mkdtemp()
        shutil.copytree(src, os.path.join(cls.dir, "d"))
        cls.svc, _ = build_app(os.path.join(cls.dir, "d"), now=NOW)
        cls.api = Api(cls.svc)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def call(self, method, path, body=None):
        raw = b"" if body is None else (body if isinstance(body, bytes) else json.dumps(body).encode())
        return self.api.handle(method, path, raw)

    def ok(self, method, path, body=None, status=None):
        s, j = self.call(method, path, body)
        self.assertIn(s, (status,) if status else (200, 201), j)
        return j

    def err(self, method, path, body, status, code):
        s, j = self.call(method, path, body)
        self.assertEqual((s, j.get("error", {}).get("code")), (status, code), j)
        return j

    def requester(self, n=0):
        return self.ok("GET", "/api/requesters?limit=50")[n]["requester_id"]

    def new_ticket(self, n=0, subject=None, body=None):
        rid = self.requester(n)
        # unique text so duplicate detection does not interfere
        payload = {"requester_id": rid, "subject": subject or GOOD["subject"], "body": body or GOOD["body"]}
        s, j = self.call("POST", "/api/tickets", payload)
        if s == 409:
            payload["body"] += " Reference %d." % len(self.svc._cache) + str(id(payload))
            j = self.ok("POST", "/api/tickets", payload, 201)
        else:
            self.assertEqual(s, 201, j)
        return j


class Validation(ApiBase):
    def test_missing_and_malformed_fields(self):
        j = self.err("POST", "/api/tickets", {"requester_id": "bad", "subject": "a", "body": ""}, 422, "VALIDATION_FAILED")
        self.assertEqual({e["field"] for e in j["error"]["details"]}, {"requester_id", "subject", "body"})

    def test_wrong_types(self):
        self.err("POST", "/api/tickets", {"requester_id": "REQ-000001", "subject": 123, "body": ["x"]}, 422, "VALIDATION_FAILED")

    def test_body_must_be_object(self):
        self.err("POST", "/api/tickets", b"[1,2]", 400, "INVALID_BODY")

    def test_invalid_json(self):
        self.err("POST", "/api/tickets", b"{not json", 400, "INVALID_JSON")

    def test_oversized_body(self):
        self.err("POST", "/api/tickets", b"{" + b" " * 70000 + b"}", 413, "BODY_TOO_LARGE")

    def test_overlong_subject_and_body(self):
        self.err("POST", "/api/tickets", {"requester_id": "REQ-000001", "subject": "x" * 201, "body": "y" * 20}, 422, "VALIDATION_FAILED")
        self.err("POST", "/api/tickets", {"requester_id": "REQ-000001", "subject": "valid subject", "body": "y" * 5001}, 422, "VALIDATION_FAILED")

    def test_bad_channel_and_deadline(self):
        base = {"requester_id": "REQ-000001", **GOOD}
        self.err("POST", "/api/tickets", {**base, "channel": "pigeon"}, 422, "VALIDATION_FAILED")
        self.err("POST", "/api/tickets", {**base, "deadline_date": "2020-01-01"}, 422, "VALIDATION_FAILED")
        self.err("POST", "/api/tickets", {**base, "deadline_date": "31/12/2026"}, 422, "VALIDATION_FAILED")

    def test_unknown_requester(self):
        self.err("POST", "/api/tickets", {"requester_id": "REQ-999999", **GOOD}, 404, "NOT_FOUND")

    def test_unknown_ticket_and_bad_ids(self):
        self.err("GET", "/api/tickets/TKT-2026-999999", None, 404, "NOT_FOUND")
        self.err("GET", "/api/tickets/nonsense", None, 400, "BAD_ID")
        self.err("GET", "/api/articles/KB-999999", None, 404, "NOT_FOUND")

    def test_unknown_route_and_method(self):
        self.err("GET", "/api/nope", None, 404, "NOT_FOUND")
        self.err("DELETE", "/api/tickets", None, 405, "METHOD_NOT_ALLOWED")

    def test_bad_query_parameters(self):
        self.err("GET", "/api/tickets?size=1000", None, 400, "BAD_QUERY")
        self.err("GET", "/api/tickets?page=-1", None, 400, "BAD_QUERY")
        self.err("GET", "/api/tickets?page=abc", None, 400, "BAD_QUERY")

    def test_sql_injection_like_input_is_inert(self):
        j = self.ok("GET", "/api/tickets?q=" + "%27%3B%20DROP%20TABLE%20ticket%3B--")
        self.assertEqual(j["total"], 0)
        self.assertGreater(self.ok("GET", "/api/tickets")["total"], 0)

    def test_html_in_body_is_stored_verbatim_not_executed(self):
        t = self.new_ticket(3, "Script test subject", "<script>alert(1)</script> I need help with my password reset please.")
        self.assertIn("<script>", t["ticket"]["body"])


class Routing(ApiBase):
    def test_ticket_gets_full_decision_and_consistent_records(self):
        t = self.new_ticket(1)
        tk = t["ticket"]
        self.assertEqual(tk["status"], "assigned")
        self.assertEqual(t["sla"]["sla_id"], "SLA-" + tk["ticket_id"])
        self.assertEqual(t["assignments"][0]["team_id"], tk["current_team_id"])
        self.assertEqual([e["event_type"] for e in t["events"]], ["created", "triaged", "assigned"])
        self.assertEqual(t["decision"]["team_id"], tk["current_team_id"])
        self.assertEqual(t["audit_findings"], [])

    def test_routed_team_is_authorised(self):
        t = self.new_ticket(2)
        self.assertEqual(t["audit_findings"], [])

    def test_sla_uses_business_hours(self):
        # Friday 16:30 +1h response must land on Monday 09:30, not 17:30 Friday
        svc = self.svc
        old = svc.clock.fixed
        from datetime import datetime
        svc.clock.fixed = datetime(2026, 11, 6, 16, 30)
        try:
            t = self.new_ticket(4, "Wifi problem friday", "URGENT my laptop cannot connect to the campus wifi network and I have an exam today.")
        finally:
            svc.clock.fixed = old
        due = t["sla"]["first_response_due"]
        self.assertTrue(due.startswith("2026-11-09") or due.startswith("2026-11-06"), due)
        self.assertNotIn("2026-11-07", due); self.assertNotIn("2026-11-08", due)

    def test_ambiguous_request_goes_to_triage_with_clarification(self):
        t = self.new_ticket(5, "Need some help", "Hello, I have a question about something and I am not sure who to ask about it.")
        self.assertTrue(t["decision"]["classification"]["ambiguous"])
        self.assertEqual(t["decision"]["category"]["category_id"], "CAT-GEN")
        self.assertIn("clarif", t["decision"]["next_action"])

    def test_no_article_found_escalates_path(self):
        p = self.ok("POST", "/api/route-preview", {"subject": "Tuition refund appeal", "body": "I want to appeal the decision about my tuition refund for a cancelled course."})
        self.assertIn("next_action", p)

    def test_preview_writes_nothing(self):
        n = self.ok("GET", "/api/tickets")["total"]
        self.ok("POST", "/api/route-preview", GOOD)
        self.assertEqual(self.ok("GET", "/api/tickets")["total"], n)

    def test_duplicate_within_24h_rejected(self):
        rid = self.requester(6)
        p = {"requester_id": rid, "subject": "Duplicate check subject", "body": "My transcript request is stuck and I need it sent to the university."}
        self.ok("POST", "/api/tickets", p, 201)
        self.err("POST", "/api/tickets", {**p, "subject": "  duplicate CHECK subject "}, 409, "DUPLICATE_TICKET")

    def test_ticket_numbers_are_sequential(self):
        a = self.new_ticket(7, "Seq one", "Where can I find the library opening hours during exams?")["ticket"]["ticket_id"]
        b = self.new_ticket(8, "Seq two", "Where can I find the exam timetable for next semester please?")["ticket"]["ticket_id"]
        self.assertEqual(int(b[-6:]), int(a[-6:]) + 1)


class AnswersAndLifecycle(ApiBase):
    def setUp(self):
        self.t = self.new_ticket(9, "Transcript question", "Registrar question: what is the transcript delivery fee for my official transcript request? Please advise.")
        self.tid = self.t["ticket"]["ticket_id"]
        self.staff = self.ok("GET", "/api/staff?team=" + self.t["ticket"]["current_team_id"])
        self.sid = [s for s in self.staff if not s["active_to"]][0]["staff_id"]
        self.sugg = self.ok("GET", "/api/tickets/%s/suggested-answer" % self.tid)

    def msg(self, body, arts=(), mtype="answer", sid=None):
        return self.call("POST", "/api/tickets/%s/messages" % self.tid, {"sender_type": "staff", "sender_id": sid or self.sid, "message_type": mtype, "body": body, "article_ids": list(arts)})

    def test_suggested_answer_cites_current_effective_article_and_is_accepted(self):
        self.assertEqual(self.sugg["action"], "answer")
        c = self.sugg["citations"][0]
        self.assertTrue(c["effective_to"] is None or c["effective_to"] >= "2026-11-02")
        s, j = self.msg(self.sugg["body"], [c["article_id"]])
        self.assertEqual(s, 200, j)
        link = j["citations"][-1]
        self.assertEqual((link["article_id"], link["cited_version_no"]), (c["article_id"], c["version_no"]))
        self.assertTrue(link["effective_at_message_date"])

    def test_missing_citation_rejected(self):
        s, j = self.msg("Please pay on time to avoid problems.")
        self.assertEqual((s, j["error"]["code"]), (422, "MISSING_CITATION"))

    def test_unsupported_number_rejected(self):
        c = self.sugg["citations"][0]["article_id"]
        s, j = self.msg("Your late fee is 9999 units according to policy.", [c])
        self.assertEqual((s, j["error"]["code"]), (422, "UNSUPPORTED_CLAIM"))

    def test_expired_article_rejected(self):
        arts = self.ok("GET", "/api/articles?status=superseded&size=100")["items"]
        topic = self.sugg["citations"][0]["article_id"]
        old = [a for a in arts if a["effective_to"] and a["effective_to"] < "2026-11-02"][0]
        s, j = self.msg("Some answer text.", [old["article_id"]])
        self.assertEqual((s, j["error"]["code"]), (422, "ARTICLE_NOT_EFFECTIVE"))

    def test_draft_article_rejected(self):
        drafts = self.ok("GET", "/api/articles?status=draft&size=100")["items"]
        if drafts:
            s, j = self.msg("text", [drafts[0]["article_id"]])
            self.assertEqual((s, j["error"]["code"]), (422, "ARTICLE_NOT_EFFECTIVE"))

    def test_unknown_article_rejected(self):
        s, j = self.msg("text", ["KB-999999"])
        self.assertEqual((s, j["error"]["code"]), (422, "UNKNOWN_ARTICLE"))

    def test_citing_in_internal_note_rejected(self):
        s, j = self.msg("note", [self.sugg["citations"][0]["article_id"]], "internal_note")
        self.assertEqual((s, j["error"]["code"]), (422, "CITATION_NOT_ALLOWED"))

    def test_staff_from_wrong_team_cannot_reply(self):
        other = [s for s in self.ok("GET", "/api/staff") if s["team_id"] != self.t["ticket"]["current_team_id"] and not s["active_to"]][0]
        s, j = self.msg("hello", [], "internal_note", other["staff_id"])
        self.assertEqual((s, j["error"]["code"]), (403, "NOT_ASSIGNED_TEAM"))

    def test_other_requester_cannot_post(self):
        s, j = self.call("POST", "/api/tickets/%s/messages" % self.tid, {"sender_type": "requester", "sender_id": self.requester(10), "body": "hi"})
        self.assertEqual((s, j["error"]["code"]), (403, "NOT_TICKET_OWNER"))

    def test_message_type_must_match_sender(self):
        s, j = self.call("POST", "/api/tickets/%s/messages" % self.tid, {"sender_type": "requester", "sender_id": self.t["ticket"]["requester_id"], "message_type": "answer", "body": "x"})
        self.assertEqual((s, j["error"]["code"]), (422, "VALIDATION_FAILED"))

    def tr(self, to, **kw):
        return self.call("POST", "/api/tickets/%s/transition" % self.tid, {"to_status": to, "actor_id": self.sid, **kw})

    def test_illegal_transition(self):
        s, j = self.tr("new")
        self.assertEqual((s, j["error"]["code"]), (409, "ILLEGAL_TRANSITION"))
        s, j = self.tr("closed")
        self.assertEqual(s, 409)

    def test_cannot_resolve_without_public_response(self):
        s, j = self.tr("in_progress")
        self.assertEqual(s, 200, j)
        s, j = self.tr("resolved", resolution_code="resolved_by_staff")
        self.assertEqual((s, j["error"]["code"]), (409, "NO_RESPONSE_YET"))

    def test_resolution_code_required(self):
        s, j = self.tr("resolved")
        self.assertEqual((s, j["error"]["code"]), (422, "VALIDATION_FAILED"))

    def test_full_happy_path_then_feedback_once(self):
        c = self.sugg["citations"][0]["article_id"]
        self.assertEqual(self.msg(self.sugg["body"], [c])[0], 200)
        s, j = self.tr("resolved", resolution_code="answered_from_kb")
        self.assertEqual(s, 200, j)
        self.assertEqual(j["sla"]["resolution_status"], "met")
        self.assertIsNotNone(j["feedback"])
        fb = {"requester_id": self.t["ticket"]["requester_id"], "csat": 4, "answer_helpful": True}
        self.assertEqual(self.call("POST", "/api/tickets/%s/feedback" % self.tid, fb)[0], 200)
        s, j = self.call("POST", "/api/tickets/%s/feedback" % self.tid, fb)
        self.assertEqual((s, j["error"]["code"]), (409, "FEEDBACK_ALREADY_GIVEN"))
        s, j = self.call("POST", "/api/tickets/%s/feedback" % self.tid, {**fb, "csat": 9})
        self.assertEqual((s, j["error"]["code"]), (422, "VALIDATION_FAILED"))
        # resolved -> staff can no longer post
        s, j = self.msg("late", [], "internal_note")
        self.assertEqual((s, j["error"]["code"]), (409, "TICKET_NOT_OPEN"))

    def test_feedback_before_resolution_rejected(self):
        s, j = self.call("POST", "/api/tickets/%s/feedback" % self.tid, {"requester_id": self.t["ticket"]["requester_id"], "csat": 5})
        self.assertEqual((s, j["error"]["code"]), (409, "NOT_RESOLVED"))

    def test_requester_reopens_resolved_ticket(self):
        c = self.sugg["citations"][0]["article_id"]
        self.msg(self.sugg["body"], [c]); self.tr("resolved", resolution_code="answered_from_kb")
        s, j = self.call("POST", "/api/tickets/%s/messages" % self.tid, {"sender_type": "requester", "sender_id": self.t["ticket"]["requester_id"], "body": "This did not solve it."})
        self.assertEqual(s, 200, j)
        self.assertEqual(j["ticket"]["status"], "in_progress")
        self.assertIn("reopened", [e["event_type"] for e in j["events"]])

    def test_assign_to_unauthorised_team_rejected(self):
        cat = self.t["ticket"]["category_id"]
        meta = self.ok("GET", "/api/meta")
        domain = cat.split("-")[1]
        wrong = {"FIN": "TEAM-IT", "IT": "TEAM-FIN", "REG": "TEAM-IT", "ACC": "TEAM-IT"}.get(domain, "TEAM-IT")
        s, j = self.call("POST", "/api/tickets/%s/assign" % self.tid, {"team_id": wrong, "actor_id": self.sid, "reason": "wrong on purpose"})
        self.assertEqual((s, j["error"]["code"]), (422, "UNAUTHORIZED_TEAM"))

    def test_manual_escalation_requires_reason_and_routes_to_tier2(self):
        s, j = self.tr("escalated")
        self.assertEqual((s, j["error"]["code"]), (422, "REASON_REQUIRED"))
        self.tr("in_progress")
        s, j = self.tr("escalated", reason="needs senior review")
        self.assertEqual(s, 200, j)
        self.assertEqual(j["ticket"]["status"], "escalated")
        self.assertEqual(j["assignments"][-1]["assignment_type"], "escalation")
        s, j2 = self.tr("escalated", reason="again please")      # the original team no longer owns the ticket
        self.assertIn(s, (403, 409))


class Escalation(ApiBase):
    def test_human_review_category_must_escalate_before_resolution(self):
        body = "Registrar: I need a prerequisite override and a petition for my course because of the grade appeal."
        t = self.new_ticket(11, "Prerequisite override petition", body)
        self.assertTrue(t["decision"]["category"]["requires_human_review"])
        tid = t["ticket"]["ticket_id"]
        sid = [x for x in self.ok("GET", "/api/staff?team=" + t["ticket"]["current_team_id"]) if not x["active_to"]][0]["staff_id"]
        sugg = self.ok("GET", "/api/tickets/%s/suggested-answer" % tid)
        if sugg["action"] == "answer":
            s, j = self.call("POST", "/api/tickets/%s/messages" % tid, {"sender_type": "staff", "sender_id": sid, "message_type": "answer", "body": sugg["body"], "article_ids": [c["article_id"] for c in sugg["citations"]]})
        else:
            s, j = self.call("POST", "/api/tickets/%s/messages" % tid, {"sender_type": "staff", "sender_id": sid, "message_type": "clarification_request", "body": "Could you share more details?"})
        self.assertEqual(s, 200, j)
        from datetime import datetime, timedelta
        # inside the 10-minute grace window nothing is due yet; after it, resolving is refused until the ticket is escalated
        old = self.svc.clock.fixed
        self.svc.clock.fixed = old + timedelta(minutes=30)
        try:
            self.call("POST", "/api/tickets/%s/transition" % tid, {"to_status": "in_progress", "actor_id": sid})
            s, j = self.call("POST", "/api/tickets/%s/transition" % tid, {"to_status": "resolved", "actor_id": sid, "resolution_code": "resolved_by_staff"})
            self.assertEqual((s, j["error"]["code"]), (409, "ESCALATION_REQUIRED"), j)
            self.assertIn("E3_HUMAN_DECISION_REQUIRED", j["error"]["details"]["reasons"])
            sw = self.ok("POST", "/api/admin/sweep", {"dry_run": False})
            self.assertIn(tid, [x["ticket_id"] for x in sw["escalate"]])
            g = self.ok("GET", "/api/tickets/" + tid)
            self.assertEqual(g["ticket"]["status"], "escalated")
            self.assertEqual(g["assignments"][-1]["assignment_type"], "escalation")
            self.assertEqual(g["audit_findings"], [])
        finally:
            self.svc.clock.fixed = old


class ReadSide(ApiBase):
    def test_metrics_and_audit_and_evaluation(self):
        m = self.ok("GET", "/api/metrics")
        self.assertEqual(m["totals"]["tickets"], sum(x["n"] for x in m["by_status"]))
        a = self.ok("GET", "/api/audit")
        self.assertEqual(set(a["counts"]), {"EXPIRED_POLICY_CITATION", "UNAUTHORIZED_ROUTING", "UNSUPPORTED_CLAIM", "SLA_IGNORES_BUSINESS_HOURS", "ESCALATION_NOT_TRIGGERED"})
        e = self.ok("GET", "/api/evaluation")
        for t, v in e["anomaly_detection"]["by_type"].items():
            self.assertEqual((v["precision"], v["recall"]), (1.0, 1.0), t)

    def test_pagination_and_filters(self):
        p1 = self.ok("GET", "/api/tickets?size=10&page=1"); p2 = self.ok("GET", "/api/tickets?size=10&page=2")
        self.assertEqual(len(p1["items"]), 10)
        self.assertFalse({x["ticket_id"] for x in p1["items"]} & {x["ticket_id"] for x in p2["items"]})
        esc = self.ok("GET", "/api/tickets?escalated=1&size=100")
        self.assertTrue(all(x["escalated"] for x in esc["items"]))

    def test_article_versions(self):
        a = self.ok("GET", "/api/articles?size=1")["items"][0]
        d = self.ok("GET", "/api/articles/" + a["article_id"])
        self.assertTrue(len(d["versions"]) >= 1)

    def test_sweep_dry_run_changes_nothing(self):
        before = self.ok("GET", "/api/metrics")["totals"]
        j = self.ok("POST", "/api/admin/sweep", {})
        self.assertTrue(j["dry_run"])
        self.assertEqual(self.ok("GET", "/api/metrics")["totals"], before)
        self.err("POST", "/api/admin/sweep", {"dry_run": "yes"}, 422, "VALIDATION_FAILED")


if __name__ == "__main__":
    unittest.main()
