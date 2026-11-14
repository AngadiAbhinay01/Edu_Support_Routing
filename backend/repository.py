"""DATA TIER access layer: every SQL statement of the application lives here.

Services never build SQL strings; they call these functions.  Values leaving this module are plain dicts with the
text representation stored in SQLite (dates as 'YYYY-MM-DD', datetimes as 'YYYY-MM-DD HH:MM:SS').
"""
import json

from edu_support import config as C
from edu_support import dictionary


def _d(row):
    return dict(row) if row is not None else None


def _ds(rows):
    return [dict(r) for r in rows]


def ser(v):
    if hasattr(v, "hour"):
        return C.fmt_dt(v.replace(microsecond=0))
    if hasattr(v, "year"):
        return C.fmt_d(v)
    if isinstance(v, (dict, list)):
        return json.dumps(v, sort_keys=True, separators=(",", ":"))
    return v


def insert(conn, table, row):
    cols = dictionary.columns(table)
    vals = [ser(row.get(c)) for c in cols]
    conn.execute("INSERT INTO %s (%s) VALUES (%s)" % (table, ",".join(cols), ",".join("?" * len(cols))), vals)


def update(conn, table, key_col, key, changes):
    sets = ",".join("%s=?" % c for c in changes)
    conn.execute("UPDATE %s SET %s WHERE %s=?" % (table, sets, key_col), [ser(v) for v in changes.values()] + [key])


# ---- reference ----------------------------------------------------------------------------------------
def all_rows(conn, table, order=None):
    return _ds(conn.execute("SELECT * FROM %s%s" % (table, " ORDER BY " + order if order else "")))


def get(conn, table, key_col, key):
    return _d(conn.execute("SELECT * FROM %s WHERE %s=?" % (table, key_col), (key,)).fetchone())


def term_for(conn, d):
    """Term the request concerns: latest-starting term whose [start-30d, end] window contains the date."""
    best = None
    for t in _ds(conn.execute("SELECT * FROM term ORDER BY start_date")):
        s, e = C.parse_d(t["start_date"]), C.parse_d(t["end_date"])
        if s.toordinal() - 30 <= d.toordinal() <= e.toordinal():
            best = t
    if best is None:
        best = _d(conn.execute("SELECT * FROM term ORDER BY start_date DESC LIMIT 1").fetchone())
    return best


def routing_rule(conn, category_id, rule_type, on_date):
    return _d(conn.execute(
        "SELECT * FROM routing_rule WHERE category_id=? AND rule_type=? AND effective_from<=? AND (effective_to IS NULL OR effective_to>=?) "
        "ORDER BY effective_from DESC LIMIT 1", (category_id, rule_type, C.fmt_d(on_date), C.fmt_d(on_date))).fetchone())


def authorization(conn, team_id, category_id):
    r = conn.execute("SELECT access_level FROM team_category_authorization WHERE team_id=? AND category_id=?", (team_id, category_id)).fetchone()
    return r[0] if r else None


def active_staff(conn, team_id, on_date):
    return _ds(conn.execute(
        "SELECT s.*, (SELECT COUNT(*) FROM assignment a WHERE a.staff_id=s.staff_id AND a.unassigned_at IS NULL) AS open_load "
        "FROM staff s WHERE s.team_id=? AND s.active_from<=? AND (s.active_to IS NULL OR s.active_to>=?) ORDER BY open_load, s.staff_id",
        (team_id, C.fmt_d(on_date), C.fmt_d(on_date))))


# ---- tickets ---------------------------------------------------------------------------------------------
def next_ticket_id(conn):
    r = conn.execute("SELECT MAX(ticket_id) FROM ticket").fetchone()[0]
    n = int(r[-6:]) + 1 if r else 1
    return "TKT-2026-%06d" % n


def next_seq(conn, table, tid):
    r = conn.execute("SELECT COALESCE(MAX(seq_no),0) FROM %s WHERE ticket_id=?" % table, (tid,)).fetchone()[0]
    return r + 1


def next_assignment_no(conn, tid):
    return conn.execute("SELECT COUNT(*) FROM assignment WHERE ticket_id=?", (tid,)).fetchone()[0] + 1


def recent_tickets_of(conn, requester_id, since):
    return _ds(conn.execute("SELECT ticket_id, subject, body FROM ticket WHERE requester_id=? AND created_at>=?", (requester_id, since)))


def list_tickets(conn, f, page, size):
    where, p = [], []
    if f.get("status"):
        where.append("t.status=?"); p.append(f["status"])
    if f.get("priority"):
        where.append("t.priority=?"); p.append(f["priority"])
    if f.get("category"):
        where.append("t.category_id=?"); p.append(f["category"])
    if f.get("domain"):
        where.append("c.domain=?"); p.append(f["domain"])
    if f.get("team"):
        where.append("t.current_team_id=?"); p.append(f["team"])
    if f.get("requester_id"):
        where.append("t.requester_id=?"); p.append(f["requester_id"])
    if f.get("escalated") in ("1", "true", True):
        where.append("EXISTS (SELECT 1 FROM ticket_event e WHERE e.ticket_id=t.ticket_id AND e.event_type='escalated')")
    if f.get("sla_breached") in ("1", "true", True):
        where.append("(s.first_response_status='breached' OR s.resolution_status='breached')")
    if f.get("q"):
        where.append("(t.subject LIKE ? OR t.body LIKE ? OR t.ticket_id LIKE ?)")
        like = "%" + f["q"].replace("%", "").replace("_", "") + "%"
        p += [like, like, like]
    w = (" WHERE " + " AND ".join(where)) if where else ""
    base = "FROM ticket t JOIN category c ON c.category_id=t.category_id JOIN sla s ON s.ticket_id=t.ticket_id JOIN requester r ON r.requester_id=t.requester_id" + w
    total = conn.execute("SELECT COUNT(*) " + base, p).fetchone()[0]
    rows = _ds(conn.execute(
        "SELECT t.ticket_id, t.subject, t.status, t.priority, t.category_id, c.name AS category_name, c.domain, t.current_team_id, t.created_at, "
        "t.updated_at, t.requester_id, r.full_name AS requester_name, s.first_response_status, s.resolution_status, "
        "(SELECT COUNT(*) FROM ticket_event e WHERE e.ticket_id=t.ticket_id AND e.event_type='escalated') AS escalated "
        + base + " ORDER BY t.created_at DESC, t.ticket_id DESC LIMIT ? OFFSET ?", p + [size, (page - 1) * size]))
    return rows, total


def ticket_graph(conn, tid):
    t = get(conn, "ticket", "ticket_id", tid)
    if not t:
        return None
    msgs = _ds(conn.execute(
        "SELECT m.*, COALESCE(r.full_name, s.full_name) AS sender_name FROM message m LEFT JOIN requester r ON r.requester_id=m.requester_id "
        "LEFT JOIN staff s ON s.staff_id=m.staff_id WHERE m.ticket_id=? ORDER BY m.seq_no", (tid,)))
    links = _ds(conn.execute(
        "SELECT l.*, a.title, a.effective_from, a.effective_to, a.status AS article_status, a.topic_key, a.key_fact_value, a.key_fact_unit "
        "FROM message_article_link l JOIN knowledge_article a ON a.article_id=l.article_id JOIN message m ON m.message_id=l.message_id "
        "WHERE m.ticket_id=?", (tid,)))
    events = _ds(conn.execute("SELECT * FROM ticket_event WHERE ticket_id=? ORDER BY seq_no", (tid,)))
    for e in events:
        e["details"] = json.loads(e["details"]) if e["details"] else {}
    asg = _ds(conn.execute(
        "SELECT a.*, tm.team_name, s.full_name AS staff_name FROM assignment a JOIN team tm ON tm.team_id=a.team_id "
        "JOIN staff s ON s.staff_id=a.staff_id WHERE a.ticket_id=? ORDER BY a.assignment_id", (tid,)))
    return {"ticket": t, "messages": msgs, "citations": links, "events": events, "assignments": asg,
            "sla": get(conn, "sla", "ticket_id", tid), "feedback": get(conn, "resolution_feedback", "ticket_id", tid),
            "requester": get(conn, "requester", "requester_id", t["requester_id"]),
            "category": get(conn, "category", "category_id", t["category_id"])}


# ---- knowledge base --------------------------------------------------------------------------------------
def list_articles(conn, f, page, size):
    where, p = [], []
    if f.get("domain"):
        where.append("a.topic_key LIKE ?"); p.append(f["domain"] + "-%")
    if f.get("status"):
        where.append("a.status=?"); p.append(f["status"])
    if f.get("q"):
        where.append("(a.title LIKE ? OR a.body LIKE ? OR a.article_id LIKE ?)")
        like = "%" + f["q"].replace("%", "").replace("_", "") + "%"
        p += [like, like, like]
    w = (" WHERE " + " AND ".join(where)) if where else ""
    total = conn.execute("SELECT COUNT(*) FROM knowledge_article a" + w, p).fetchone()[0]
    rows = _ds(conn.execute("SELECT a.article_id, a.topic_key, a.version_no, a.title, a.status, a.effective_from, a.effective_to, a.policy_id, "
                            "a.key_fact_value, a.key_fact_unit FROM knowledge_article a" + w +
                            " ORDER BY a.topic_key, a.version_no LIMIT ? OFFSET ?", p + [size, (page - 1) * size]))
    return rows, total


def article_versions(conn, topic_key):
    return _ds(conn.execute("SELECT a.*, p.title AS policy_title FROM knowledge_article a JOIN policy_document p ON p.policy_id=a.policy_id "
                            "WHERE a.topic_key=? ORDER BY a.version_no", (topic_key,)))


# ---- metrics -----------------------------------------------------------------------------------------------
def one(conn, sql, p=()):
    r = conn.execute(sql, p).fetchone()
    return r[0] if r else None


def rows(conn, sql, p=()):
    return _ds(conn.execute(sql, p))
