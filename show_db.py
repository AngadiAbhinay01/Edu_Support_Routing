"""Print any table of data/full/app.db as an aligned text table.   python show_db.py ticket 5"""
import sqlite3, sys

DB = "data/full/app.db"
table = sys.argv[1] if len(sys.argv) > 1 else "ticket"
limit = int(sys.argv[2]) if len(sys.argv) > 2 else 5
if not table.replace("_", "").isalnum():
    sys.exit("bad table name")
order = {"ticket": "created_at", "message": "created_at", "ticket_event": "event_at",
         "assignment": "assigned_at", "sla": "clock_start"}.get(table)
conn = sqlite3.connect(DB)
sql = "SELECT * FROM %s" % table + (" ORDER BY %s DESC" % order if order else "")
cur = conn.execute(sql + " LIMIT ?", (limit,))
cols = [d[0] for d in cur.description]
rows = [[str(v)[:30] if v is not None else "" for v in r] for r in cur.fetchall()]
widths = [max([len(c)] + [len(r[i]) for r in rows]) for i, c in enumerate(cols)]
print(" | ".join(c.ljust(w) for c, w in zip(cols, widths)))
print("-+-".join("-" * w for w in widths))
for r in rows:
    print(" | ".join(v.ljust(w) for v, w in zip(r, widths)))
