"""Exporters: CSV (canonical), JSON, SQL seed, ground truth, manifests (with checksums)."""
import csv
import hashlib
import json
import os
from datetime import datetime, date

from edu_support import config as C
from edu_support import dictionary

GT_COLUMNS = ["ticket_id", "scenario", "kind", "true_domain", "true_topic_key", "expected_initial_category_id", "expected_initial_team_id",
              "expected_priority", "true_ambiguous", "expected_article_id", "expected_escalation", "expected_escalation_reasons",
              "issue_type", "issue_entity_id"]
ANOM_COLUMNS = ["issue_id", "ticket_id", "issue_type", "entity_type", "entity_id", "expected_value", "observed_value", "description"]


def _ser(field, v):
    if v is None:
        return ""
    t = field["type"]
    if t == "datetime":
        return C.fmt_dt(v.replace(microsecond=0)) if isinstance(v, datetime) else v
    if t == "date":
        return C.fmt_d(v) if isinstance(v, (date, datetime)) else v
    if t == "json":
        return json.dumps(v, sort_keys=True, separators=(",", ":"), default=str) if v else ""
    if t == "real":
        return repr(round(float(v), 2))
    if t in ("int", "bool"):
        return str(int(v))
    return str(v)


def _typed(field, v):
    s = _ser(field, v)
    if s == "":
        return None
    t = field["type"]
    if t in ("int", "bool"):
        return int(s)
    if t == "real":
        return float(s)
    if t == "json":
        return json.loads(s)
    return s


def _sql(v):
    if v is None:
        return "NULL"
    if isinstance(v, (int, float)):
        return repr(v)
    return "'" + str(v).replace("'", "''") + "'"


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_all(out, tables, gt, anomalies, meta):
    for sub in ("csv", "json", "sql", "ground_truth"):
        os.makedirs(os.path.join(out, sub), exist_ok=True)
    counts = {}
    sql_lines = ["-- Seed data (generated). Load with:  sqlite3 app.db < seed.sql", "BEGIN TRANSACTION;"]
    for name, t in dictionary.TABLES.items():
        fields = t["fields"]
        rows = tables[name]
        counts[name] = len(rows)
        cols = [f["name"] for f in fields]
        with open(os.path.join(out, "csv", name + ".csv"), "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh, lineterminator="\n")
            w.writerow(cols)
            for r in rows:
                w.writerow([_ser(f, r.get(f["name"])) for f in fields])
        typed = [{f["name"]: _typed(f, r.get(f["name"])) for f in fields} for r in rows]
        with open(os.path.join(out, "json", name + ".json"), "w", encoding="utf-8") as fh:
            json.dump(typed, fh, separators=(",", ":"), ensure_ascii=False)
        for r in typed:
            sql_lines.append("INSERT INTO %s (%s) VALUES (%s);" % (name, ",".join(cols), ",".join(_sql(json.dumps(r[c], sort_keys=True, separators=(",", ":")) if isinstance(r[c], (dict, list)) else r[c]) for c in cols)))
    sql_lines.append("COMMIT;")
    with open(os.path.join(out, "sql", "schema.sql"), "w", encoding="utf-8") as fh:
        fh.write(dictionary.ddl())
    with open(os.path.join(out, "sql", "seed.sql"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(sql_lines) + "\n")
    # ---- ground truth (kept in its own folder; never read by the app's input pipeline) -----------------
    with open(os.path.join(out, "ground_truth", "ground_truth.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(GT_COLUMNS)
        for r in gt:
            w.writerow([r[c] for c in GT_COLUMNS])
    with open(os.path.join(out, "ground_truth", "ground_truth_anomalies.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(ANOM_COLUMNS)
        for r in anomalies:
            w.writerow([r[c] for c in ANOM_COLUMNS])
    with open(os.path.join(out, "ground_truth", "ground_truth_anomalies.json"), "w", encoding="utf-8") as fh:
        json.dump(anomalies, fh, indent=1)
    # ---- manifests --------------------------------------------------------------------------------------
    files = {}
    for root, _, names in os.walk(out):
        for n in sorted(names):
            if n in ("manifest.json", "source_manifest.json"):
                continue
            p = os.path.join(root, n)
            files[os.path.relpath(p, out).replace(os.sep, "/")] = sha256_file(p)
    manifest = {**meta, "as_of": C.fmt_dt(C.AS_OF), "row_counts": counts,
                "ground_truth_rows": len(gt), "labelled_anomalies": len(anomalies),
                "anomalies_by_type": {k: sum(1 for a in anomalies if a["issue_type"] == k) for k in C.ISSUE_TYPES},
                "sha256": dict(sorted(files.items()))}
    with open(os.path.join(out, "manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=1, sort_keys=True)
    source = {
        "dataset": "Student & Faculty Support Routing - synthetic",
        "external_data_used": False,
        "sources": [],
        "provenance": "100% synthetic. All persons, e-mails (reserved example.edu domain), policies, articles and tickets are generated by "
                      "datagen/generate.py from templates written for this exercise with a fixed pseudo-random seed.",
        "licence": "Generated content is released under the repository licence (MIT).",
        "personal_data": "None. No real individuals, no scraped or confidential data.",
        "public_reference_used_for_schema_inspiration": "General knowledge of ticketing / service-desk (ITIL-style) concepts; no dataset was downloaded.",
        "fields_discarded": [], "transformations": [],
    }
    with open(os.path.join(out, "source_manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(source, fh, indent=1)
    return manifest
