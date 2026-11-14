"""Data-tier helpers: build / open the SQLite database from the exported CSV files."""
import csv
import hashlib
import os
import sqlite3

from . import dictionary


def connect(path, check_same_thread=True):
    conn = sqlite3.connect(path, timeout=15, check_same_thread=check_same_thread)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _convert(field, raw):
    if raw == "" or raw is None:
        return None
    t = field["type"]
    if t in ("int", "bool"):
        return int(raw)
    if t == "real":
        return float(raw)
    return raw


def data_fingerprint(data_dir):
    h = hashlib.sha256()
    for name in dictionary.TABLES:
        p = os.path.join(data_dir, name + ".csv")
        h.update(name.encode())
        with open(p, "rb") as f:
            h.update(f.read())
    return h.hexdigest()


def build_database(db_path, data_dir):
    """(Re)create `db_path` from schema + CSVs in `data_dir`. Foreign keys are enforced while loading."""
    if os.path.exists(db_path):
        os.remove(db_path)
    conn = connect(db_path)
    conn.executescript(dictionary.ddl())
    for name, t in dictionary.TABLES.items():
        fields = t["fields"]
        cols = [f["name"] for f in fields]
        with open(os.path.join(data_dir, name + ".csv"), newline="", encoding="utf-8") as fh:
            rd = csv.DictReader(fh)
            if rd.fieldnames != cols:
                raise ValueError("CSV header mismatch for %s: %s" % (name, rd.fieldnames))
            rows = [[_convert(f, r[f["name"]]) for f in fields] for r in rd]
        conn.executemany("INSERT INTO %s (%s) VALUES (%s)" % (name, ",".join(cols), ",".join("?" * len(cols))), rows)
    conn.execute("CREATE TABLE _meta (k TEXT PRIMARY KEY, v TEXT)")
    conn.execute("INSERT INTO _meta VALUES ('fingerprint', ?)", (data_fingerprint(data_dir),))
    conn.commit()
    conn.close()


def ensure_database(db_path, data_dir):
    """Build the DB when missing or when the CSV data changed. Returns True when (re)built."""
    fp = data_fingerprint(data_dir)
    if os.path.exists(db_path):
        try:
            c = connect(db_path)
            row = c.execute("SELECT v FROM _meta WHERE k='fingerprint'").fetchone()
            c.close()
            if row and row[0] == fp:
                return False
        except sqlite3.Error:
            pass
    build_database(db_path, data_dir)
    return True
