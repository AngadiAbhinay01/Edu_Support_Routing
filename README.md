# Student & Faculty Support Routing

Route student and faculty requests, retrieve **policy-grounded answers**, and track **resolution and escalation** — a three-tier web app over a deterministic synthetic dataset with labelled, injected defects and an independent auditor.

* **No installs, no admin rights.** Python 3.10+ standard library only (`http.server`, `sqlite3`, `unittest`) and a plain-JS frontend. Everything lives in this one folder, which is what the `candidateworkspace` rule needs.
* **All data is synthetic** (`example.edu` addresses, invented policies). Nothing external is used.

## Run it (Windows / macOS / Linux)

```
python -m backend.server            # opens on http://127.0.0.1:8000  (data/full is loaded; app.db is built on first start, ~10 s)
python -m unittest discover -s tests -t .      # 68 tests
```

On Windows use `py` instead of `python` if needed. Other ports: `python -m backend.server --port 8080`. Freeze the app clock for demos: `--now "2026-11-02 10:00:00"`.

## Regenerate the data (fixed seed 20261022)

```
python -m datagen.generate --out data/full --tickets 5000 --articles 200 --messages 20000 --seed 20261022
python -m datagen.validate --data data/full            # 44 checks + audit vs ground truth -> VALIDATION_SUMMARY.md/.json
python -m datagen.reproducibility                      # regenerates twice (different PYTHONHASHSEED) and compares row counts + SHA-256
python -m edu_support.docgen                           # rebuilds docs/DATA_DICTIONARY.md and schema.sql
```

Scale is parameterised (`--tickets N --articles N --messages N`, articles ≥ 40). A small dataset ships in `data/sample`.

## The three tiers

| Tier | Folder | Responsibility |
|---|---|---|
| Presentation | `frontend/` | HTML/JS/CSS single-page app: dashboard, tickets, new-ticket with routing preview, ticket detail, knowledge base with versions, audit & evaluation |
| Application | `backend/` + `edu_support/` | HTTP API, validation, workflow rules (classify → prioritise → route → answer → escalate), lifecycle enforcement |
| Data | `backend/repository.py`, `edu_support/db.py`, `data/` | SQLite built from the CSV export; **all SQL lives in the repository**; the schema is generated from the data dictionary |

Read [docs/UNDERSTANDING_THE_PROJECT.md](docs/UNDERSTANDING_THE_PROJECT.md) first — it explains everything in plain language. Then [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), [docs/RULES.md](docs/RULES.md), [docs/EDGE_CASES.md](docs/EDGE_CASES.md), [docs/GENERATOR.md](docs/GENERATOR.md), [docs/DATA_DICTIONARY.md](docs/DATA_DICTIONARY.md), [docs/PROMPTS.md](docs/PROMPTS.md) (the stage-by-stage AI prompt plan).

## What is in `data/full`

`csv/` (19 tables) · `json/` · `sql/` (schema.sql + seed.sql) · `ground_truth/` (**separate**, never read by the app's decision logic) · `manifest.json` (row counts + SHA-256) · `source_manifest.json` · `VALIDATION_SUMMARY.md` · `REPRODUCIBILITY.md`.

## Honest notes

* The five injected defect types are detected with precision = recall = 1.0 by `edu_support/audit.py`. That is because the generator produces *clean* data apart from the labelled defects and the auditor uses the same published rules; it demonstrates the pipeline works, **not** that real-world detection would be perfect.
* The router is a transparent keyword scorer (explainable, deterministic), not a machine-learning model.
* `app.db` is a build artefact (git-ignored); it is rebuilt automatically whenever the CSVs change.
