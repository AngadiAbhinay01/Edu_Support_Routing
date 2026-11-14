"""Generate docs/DATA_DICTIONARY.md and edu_support/schema.sql from the single-source dictionary.

    python -m edu_support.docgen
"""
import os
from . import dictionary as D

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def cons(f):
    c, out = f["constraints"] if "constraints" in f else f, []
    if c.get("pk"): out.append("PK")
    if c.get("unique"): out.append("unique")
    if c.get("fk"): out.append("FK → " + c["fk"])
    if c.get("enum"): out.append("one of: " + ", ".join(c["enum"]))
    if c.get("range"): out.append("range %g..%g" % c["range"])
    if c.get("pattern"): out.append("pattern `%s`" % c["pattern"])
    if c.get("len"): out.append("length %s..%s" % tuple(c["len"]))
    return "; ".join(out)


def main():
    lines = ["# Data dictionary", "", "_Generated from `edu_support/dictionary.py` (the single source of truth) by `python -m edu_support.docgen`. "
             "The same definitions create the SQL schema and drive the validator, so this document cannot drift from the code._", "",
             "All data is **synthetic**. Required = `R`, optional = `O`.", "", "| Table | Fields | Purpose |", "|---|---|---|"]
    for name, t in D.TABLES.items():
        lines.append("| [%s](#%s) | %d | %s |" % (name, name, len(t["fields"]), t["title"]))
    for name, t in D.TABLES.items():
        lines += ["", "## %s" % name, "", "**%s.** %s" % (t["title"], t["description"]), "", "*Cardinality:* %s" % t["cardinality"], "",
                  "| Field | Type | Req | Constraints | Unit | Description |", "|---|---|---|---|---|---|"]
        for f in t["fields"]:
            lines.append("| `%s` | %s | %s | %s | %s | %s |" % (f["name"], f["type"], "R" if f["required"] else "O", cons(f), f.get("unit") or "", f["description"].replace("|", "/")))
    os.makedirs(os.path.join(ROOT, "docs"), exist_ok=True)
    with open(os.path.join(ROOT, "docs", "DATA_DICTIONARY.md"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines) + "\n")
    with open(os.path.join(ROOT, "edu_support", "schema.sql"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(D.ddl())
    print("wrote docs/DATA_DICTIONARY.md and edu_support/schema.sql")


if __name__ == "__main__":
    main()
