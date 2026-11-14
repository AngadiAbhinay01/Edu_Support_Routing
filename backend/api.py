"""APPLICATION TIER (HTTP): routing table, JSON parsing, error mapping. No business rules here."""
import json
import re
from urllib.parse import urlparse, parse_qs

from .errors import ApiError

MAX_BODY = 64 * 1024


def _int(q, name, default, lo, hi):
    v = q.get(name, [None])[0]
    if v is None:
        return default
    if not re.fullmatch(r"\d{1,6}", v) or not lo <= int(v) <= hi:
        raise ApiError(400, "BAD_QUERY", "%s must be an integer between %d and %d" % (name, lo, hi))
    return int(v)


def _one(q, name):
    v = q.get(name, [None])[0]
    if v is not None and len(v) > 200:
        raise ApiError(400, "BAD_QUERY", "%s is too long" % name)
    return v or None


class Api:
    def __init__(self, svc):
        s = self.s = svc
        T = r"(TKT-2026-\d{6}|[^/]+)"
        self.routes = [
            ("GET", r"/api/health", lambda m, q, b: {"status": "ok"}),
            ("GET", r"/api/meta", lambda m, q, b: s.meta()),
            ("GET", r"/api/requesters", lambda m, q, b: s.search_requesters(_one(q, "q"), _int(q, "limit", 20, 1, 100))),
            ("GET", r"/api/staff", lambda m, q, b: s.list_staff(_one(q, "team"))),
            ("GET", r"/api/tickets", self.tickets),
            ("POST", r"/api/tickets", lambda m, q, b: s.create_ticket(b)),
            ("GET", r"/api/tickets/" + T, lambda m, q, b: s.get_ticket(m[0])),
            ("POST", r"/api/tickets/" + T + r"/messages", lambda m, q, b: s.add_message(m[0], b)),
            ("POST", r"/api/tickets/" + T + r"/transition", lambda m, q, b: s.transition(m[0], b)),
            ("POST", r"/api/tickets/" + T + r"/assign", lambda m, q, b: s.assign(m[0], b)),
            ("POST", r"/api/tickets/" + T + r"/feedback", lambda m, q, b: s.feedback(m[0], b)),
            ("GET", r"/api/tickets/" + T + r"/suggested-answer", lambda m, q, b: s.suggested_answer(m[0])),
            ("GET", r"/api/articles", self.articles),
            ("GET", r"/api/articles/([A-Za-z0-9\-]+)", lambda m, q, b: s.get_article(m[0])),
            ("POST", r"/api/route-preview", lambda m, q, b: s.route_preview(b)),
            ("GET", r"/api/metrics", lambda m, q, b: s.metrics()),
            ("GET", r"/api/audit", lambda m, q, b: s.audit(_one(q, "as_of") == "now", _one(q, "issue_type"), _int(q, "limit", 100, 1, 1000))),
            ("GET", r"/api/evaluation", lambda m, q, b: s.evaluation()),
            ("POST", r"/api/admin/sweep", lambda m, q, b: s.sweep(b)),
        ]
        self.routes = [(meth, re.compile("^" + pat + "$"), fn) for meth, pat, fn in self.routes]

    def tickets(self, m, q, b):
        f = {k: _one(q, k) for k in ("status", "priority", "category", "domain", "team", "requester_id", "escalated", "sla_breached", "q")}
        page, size = _int(q, "page", 1, 1, 100000), _int(q, "size", 25, 1, 100)
        rows, total = self.s.list_tickets(f, page, size)
        return {"items": rows, "total": total, "page": page, "size": size, "pages": (total + size - 1) // size}

    def articles(self, m, q, b):
        f = {k: _one(q, k) for k in ("domain", "status", "q")}
        page, size = _int(q, "page", 1, 1, 100000), _int(q, "size", 25, 1, 100)
        rows, total = self.s.list_articles(f, page, size)
        return {"items": rows, "total": total, "page": page, "size": size, "pages": (total + size - 1) // size}

    def handle(self, method, raw_path, body_bytes):
        """Returns (status, payload_dict). Never raises."""
        try:
            u = urlparse(raw_path)
            path = u.path.rstrip("/") or "/"
            q = parse_qs(u.query, keep_blank_values=False)
            allowed = []
            for meth, rx, fn in self.routes:
                m = rx.match(path)
                if not m:
                    continue
                allowed.append(meth)
                if meth != method:
                    continue
                body = None
                if method == "POST":
                    if len(body_bytes) > MAX_BODY:
                        raise ApiError(413, "BODY_TOO_LARGE", "request body exceeds %d bytes" % MAX_BODY)
                    if body_bytes.strip():
                        try:
                            body = json.loads(body_bytes.decode("utf-8"))
                        except (ValueError, UnicodeDecodeError):
                            raise ApiError(400, "INVALID_JSON", "request body is not valid UTF-8 JSON")
                    else:
                        body = {}
                return 200 if method == "GET" else (201 if path == "/api/tickets" else 200), fn(m.groups(), q, body)
            if allowed:
                raise ApiError(405, "METHOD_NOT_ALLOWED", "allowed: %s" % ", ".join(sorted(set(allowed))))
            raise ApiError(404, "NOT_FOUND", "no such endpoint: %s" % path)
        except ApiError as e:
            return e.status, e.to_dict()
        except Exception as e:  # never leak a stack trace to the client
            import traceback, sys
            traceback.print_exc(file=sys.stderr)
            return 500, {"error": {"code": "INTERNAL_ERROR", "message": "unexpected server error"}}
