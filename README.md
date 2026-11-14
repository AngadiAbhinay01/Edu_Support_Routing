# 🎓 Student & Faculty Support Routing

**Route student and faculty requests, answer them from the *current* policy, and track resolution and escalation.**

A complete three-tier project: a web app, a deterministic synthetic-data generator with labelled mistakes, and an independent auditor that finds those mistakes.

> ✅ Python standard library only · ✅ No installs, no admin rights · ✅ Everything inside one folder · ✅ All data is synthetic

---

## 📌 At a glance

| | |
|---|---|
| **Tickets / Articles / Messages** | 5,000 / 200 / 20,000 (fixed seed `20261022`, scale is a parameter) |
| **Database** | 19 tables, 161 fields, generated from one data dictionary |
| **Planted mistakes** | 5 types × 60 tickets = 300, labelled in a separate `ground_truth/` folder |
| **Data validation** | 44 / 44 checks pass |
| **Reproducibility** | Same seed → identical SHA-256 for all 43 files; different seed → different files |
| **Tests** | 68 unit and end-to-end tests pass |
| **Tech** | Python 3.10+ (`http.server`, `sqlite3`, `unittest`), plain HTML/CSS/JavaScript |

---

## 🚀 Quick start (3 commands)

Open a terminal in this folder. On Windows use `py` instead of `python` if needed.

```bash
python -m unittest discover -s tests -t .     # 1. run the 68 tests
python -m datagen.validate --data data/full   # 2. check the data: 44 checks + audit vs ground truth
python -m backend.server                      # 3. start the app → http://127.0.0.1:8000
```

The first start takes about 10 seconds because it builds the database (`data/full/app.db`) from the CSV files. You never install or open a database server.

Handy extras:

```bash
python show_db.py ticket 5                    # print the newest 5 tickets as a table
python -m backend.server --port 8080          # use another port
python -m backend.server --now "2026-11-02 10:00:00"   # freeze the app clock for a demo
```

---

## 🧩 The problem in plain words

A university help desk receives thousands of requests. A good system must:

1. **Route** each request to the right team.
2. **Answer** from the current official policy and say which article and version was used.
3. **Track deadlines (SLAs)** in business hours only.
4. **Escalate** unclear, urgent or sensitive cases to a human specialist.

This project does all four, and also proves its data is trustworthy.

---

## 🏗️ Three-tier architecture

```
┌────────────────────┐    ┌───────────────────────────────┐    ┌──────────────────────────┐
│  1. PRESENTATION   │    │  2. APPLICATION               │    │  3. DATA                 │
│  frontend/         │───▶│  backend/api.py   (routes)    │───▶│  backend/repository.py   │
│  HTML + JS + CSS   │JSON│  backend/services.py (rules)  │SQL │  SQLite: data/full/app.db│
│  shows and clicks  │◀───│  edu_support/ (shared rules)  │◀───│  built from the CSV files│
└────────────────────┘    └───────────────────────────────┘    └──────────────────────────┘
```

| Tier | Folder | What it does |
|---|---|---|
| Presentation | `frontend/` | Dashboard, tickets, new ticket with routing preview, ticket detail, knowledge base, audit. Makes no decisions. |
| Application | `backend/`, `edu_support/` | Validates input, classifies, prioritises, routes, checks answers, escalates, enforces the life-cycle. |
| Data | `backend/repository.py`, `edu_support/db.py`, `data/` | The only code that runs SQL. Foreign keys are enforced. |

---

## 🔄 How a ticket flows through the system

```
 Requester ─▶ validate ─▶ duplicate? ─▶ classify ─▶ priority ─▶ route to an authorized team
                                                                          │
   rated by requester ◀─ resolved ◀─ cited answer checked ◀─ staff reply ◀┘
                                  ╲
                                   ╲─ rule fires (E1–E5) ─▶ escalated to tier-2 team
```

1. **Validate** the input (ID format, text length, deadline, active requester).
2. **Reject duplicates** (same text, same person, within 24 hours).
3. **Classify** by counting keyword matches per domain. A weak or tied result is marked *ambiguous* and goes to triage for clarification.
4. **Set the priority** (category default, raised for close deadlines or urgent words).
5. **Route** using a routing rule and check that the team is *authorized* for that category.
6. **Start the SLA clock** in business hours (Mon–Fri 09:00–17:00, no holidays). A ticket raised Friday 16:30 with a 1-hour target is due **Monday 09:30**.
7. **Answer** from the knowledge-base version in force today, naming the policy, article and version.
8. **Escalate** when a rule fires, then **resolve**, and the requester rates it 1–5.

Every step writes a row to `ticket_event`, so the history is a complete audit trail.

### Escalation rules

| Rule | Fires when |
|---|---|
| E1 | The request is ambiguous and still unresolved after clarification |
| E2 | No policy article was found |
| E3 | The category needs a human decision |
| E4 | An urgent ticket missed its first-response deadline |
| E5 | The requester followed up two or more times |

---

## 🧪 The synthetic data and the five planted mistakes

The generator first creates **clean** data, then re-creates a small share of tickets with exactly one mistake each. Where they are is saved **separately** in `data/full/ground_truth/`.

| # | Planted mistake | What it means |
|---|---|---|
| 1 | `EXPIRED_POLICY_CITATION` | The answer cites a policy version that had already expired |
| 2 | `UNAUTHORIZED_ROUTING` | The ticket went to a team not allowed to handle that category |
| 3 | `UNSUPPORTED_CLAIM` | The answer states a number its cited source does not contain |
| 4 | `SLA_IGNORES_BUSINESS_HOURS` | The deadline was computed on wall-clock time |
| 5 | `ESCALATION_NOT_TRIGGERED` | A rule required escalation, but nobody escalated |

The **auditor** (`edu_support/audit.py`) re-finds them using only the normal tables. `edu_support/evaluation.py` then scores it against the ground truth.

**Result:** 300 planted, 300 found, 0 false alarms. See the honest note below on why this is expected.

---

## 🛡️ Edge cases and validation handled

All are covered by tests. The full list is in [docs/EDGE_CASES.md](docs/EDGE_CASES.md).

- **Bad input:** missing or wrong-type fields, invalid JSON, oversized body (413), bad IDs, past deadlines, bad pagination
- **Duplicates:** the same ticket within 24 hours (409)
- **Answers:** expired or draft article, no citation when a source exists, a number the source does not contain, citing from an internal note
- **Permissions:** staff from the wrong team, a requester posting on someone else's ticket, assigning to an unauthorized team
- **Life-cycle:** illegal status changes (409 with the allowed moves), resolving before any reply, resolving while an escalation is due, feedback before resolution, feedback twice, reopening
- **Security:** no `innerHTML` (all text is escaped), parameterized SQL, request size limit, path-traversal guard, Content-Security-Policy header
- **Time:** weekends, holidays, before opening, exactly at closing

---

## 📁 Project structure

```
edu-support-routing/
├── frontend/            Tier 1: index.html, app.js, style.css
├── backend/             Tier 2: server.py, api.py, services.py, errors.py
│   └── repository.py   Tier 3: all SQL lives here
├── edu_support/         Shared rules: config, bizhours, rules, dictionary, db, audit, evaluation, docgen
├── datagen/             Generator, exporter, validator, reproducibility check, catalog
├── data/
│   ├── full/            5,000 tickets: csv/ json/ sql/ ground_truth/ manifests, validation + reproducibility reports
│   └── sample/          Small dataset for quick tries
├── tests/               68 tests (business hours, rules, generator, API edge cases)
├── docs/                Written guides (see below)
└── show_db.py           Print any table from the database
```

---

## 📚 Documentation

| Read this | To learn |
|---|---|
| [docs/UNDERSTANDING_THE_PROJECT.md](docs/UNDERSTANDING_THE_PROJECT.md) | **Start here.** The whole project in plain language, with a 3-minute demo |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | The tiers, each file's job, the 19 tables |
| [docs/RULES.md](docs/RULES.md) | Classification, SLA, retrieval, escalation, life-cycle |
| [docs/EDGE_CASES.md](docs/EDGE_CASES.md) | Every edge case and where it is tested |
| [docs/GENERATOR.md](docs/GENERATOR.md) | How the data is generated and why it is deterministic |
| [docs/DATA_DICTIONARY.md](docs/DATA_DICTIONARY.md) | Every table and field (generated from the code) |
| [docs/PROMPTS.md](docs/PROMPTS.md) | The stage-by-stage AI prompt plan for building this project |

---

## 🔁 Regenerate the data (fixed seed)

```bash
python -m datagen.generate --out data/full --tickets 5000 --articles 200 --messages 20000 --seed 20261022
python -m datagen.validate --data data/full           # 44 checks + audit vs ground truth
python -m datagen.reproducibility                     # regenerates 3 times, compares row counts and SHA-256
python -m edu_support.docgen                          # rebuilds the data dictionary and schema.sql
```

`data/full` contains: `csv/` (19 tables), `json/`, `sql/` (schema + seed), `ground_truth/`, `manifest.json` (row counts and checksums), `source_manifest.json`, `VALIDATION_SUMMARY.md`, `REPRODUCIBILITY.md`.

---

## ⚠️ Honest notes

- **100% detection is expected, not proof of real-world accuracy.** The planted mistakes are defined by the same rules the auditor checks, so the score shows the pipeline is wired correctly. Real data would be noisier.
- **The router is rule-based on purpose:** transparent and repeatable, with every decision showing its scores. It is not a machine-learning model, and it covers the topics in the catalog.
- **All data is synthetic** (`example.edu` addresses, invented policies). No external or personal data is used.
- **`app.db` is a build artefact** (git-ignored). It is rebuilt automatically whenever the CSV files change.
- **Not tested under heavy concurrent load.** SQLite fits this scale; a larger deployment would use PostgreSQL.

---

## 🔮 Possible improvements

Embedding-based retrieval and a learned classifier, user login and roles, email notifications, and PostgreSQL for many users.
