# Understanding this project (read this first)

## 1. The problem in one paragraph
A university help desk gets thousands of questions from students and faculty ("how do I pay late tuition?", "my account is locked"). Someone must (a) send each request to the right team, (b) answer from the **current** official policy and say which policy, (c) track deadlines (SLAs), and (d) hand hard or unclear cases to a human specialist (escalation). The hackathon asked for two things: **a realistic fake dataset** with a few deliberately planted mistakes, and **a way to find those mistakes**. This project does both and adds a working app on top.

## 2. The three tiers (what the organisers asked for)
```
Frontend (browser)  ──►  Backend (Python server)  ──►  Database (SQLite)
 frontend/                 backend/ + edu_support/        data/ → app.db
 what you see              decisions + rules              stored rows
```
* **Frontend** never decides anything; it shows JSON and sends clicks to the API.
* **Backend** is where rules live: classification, routing, answer checks, escalation.
* **Database** only stores/returns data; all SQL is in `backend/repository.py`.

## 3. Life of one ticket
1. A requester submits subject + text (`POST /api/tickets`).
2. **Validate** the input (length, id format, deadline) and reject duplicates.
3. **Classify**: count keyword hits per domain (Finance, Registrar, IT, Accessibility). Unclear → "ambiguous" → triage team asks a clarifying question.
4. **Prioritise** (deadline close? urgent words?).
5. **Route** with a routing rule, and check the team is **authorised** for that category.
6. **SLA clock** starts, counted only in business hours (Mon–Fri 9–5, no holidays).
7. Staff open the ticket, click *Fill suggested answer*: the system finds the matching knowledge article **in force today** and builds an answer that names the article and its version.
8. On *Send*, the backend refuses answers that cite an expired article, have no citation, or contain numbers the source doesn't contain.
9. If a rule says a human must decide (E1–E5) the ticket is **escalated** to the tier-2 team; it cannot be marked resolved before that.
10. Resolved → requester gives a 1–5 rating; resolved tickets auto-close after 7 days.
Every step writes a row to `ticket_event`, so the history is a complete audit trail.

## 4. The synthetic data and the "five planted defects"
The generator first builds **clean** data, then re-creates a small share of tickets with exactly one mistake each:

| Defect | Plain meaning |
|---|---|
| `EXPIRED_POLICY_CITATION` | the answer quotes an old policy version that had already expired |
| `UNAUTHORIZED_ROUTING` | ticket sent to a team not allowed to handle that category |
| `UNSUPPORTED_CLAIM` | the answer states a number/fact its cited source doesn't contain |
| `SLA_IGNORES_BUSINESS_HOURS` | due time computed on wall-clock time, not business hours |
| `ESCALATION_NOT_TRIGGERED` | a rule required escalation, but nobody escalated |

The list of which tickets were altered is saved **separately** in `ground_truth/`. The **auditor** (`edu_support/audit.py`) then looks only at the normal tables, finds the defects, and `evaluation.py` compares against ground truth. Result: 300 planted, 300 found, 0 false alarms. (This is expected on purpose-built data; see README "Honest notes".)

## 5. Why the data is trustworthy
* **Deterministic**: same seed 20261022 ⇒ byte-identical files (proved by SHA-256 across runs).
* **Derived, not invented**: SLA breach flags and resolution hours are computed from timestamps.
* **Validated**: 44 automatic checks (keys, foreign keys, enums, date order, arithmetic, lifecycle, duplicates, ID formats, no ground-truth leakage).

## 6. Try it in 3 minutes
1. `python -m backend.server` → open http://127.0.0.1:8000
2. **Dashboard**: counts, SLA breach rates, escalation reasons.
3. **New ticket** → subject "Transcript fee", text "Registrar: what is the transcript delivery fee for my official transcript request?" → *Preview routing* shows the decision trace → *Create*.
4. On the ticket page: pick a staff member → *Fill suggested answer* → *Send* → change status to *resolved*.
5. Try breaking rules: send an answer without article ids (MISSING_CITATION), write "the fee is 9999" (UNSUPPORTED_CLAIM), resolve before replying (NO_RESPONSE_YET).
6. **Audit & evaluation** page: the 300 findings and the precision/recall table. Open a finding's ticket to see why it was flagged.

## 7. Likely questions from reviewers
* *Why SQLite / stdlib?* Locked-down laptop: nothing to install, one folder.
* *Why not ML routing?* Explainable, deterministic, and every decision shows its scores.
* *How do you prevent leaking answers to the auditor?* Separate folder, never imported by `audit.py`; `validate` asserts no label columns exist in input tables.
* *What happens at 100 % precision?* It is an artefact of synthetic, rule-defined defects — say so openly.
* *Where is article version recorded?* `message_article_link.cited_version_no`.
* *How are unresolved/ambiguous cases escalated?* Rules E1/E2 in `RULES.md`, enforced by the sweep and by the resolve guard.

## 8. Reading order for the code
`edu_support/config.py` → `bizhours.py` → `rules.py` → `dictionary.py` → `datagen/generate.py` → `audit.py` → `backend/services.py` → `backend/api.py` → `frontend/app.js` → `tests/`.
