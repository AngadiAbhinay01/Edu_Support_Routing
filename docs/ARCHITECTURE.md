# Architecture

```
 Browser ──HTTP/JSON──▶ backend/server.py ─▶ backend/api.py ─▶ backend/services.py ─▶ backend/repository.py ─▶ SQLite (app.db)
 frontend/ (tier 1)        (tier 2: HTTP)        routing          business rules           (tier 3: SQL only)        ▲
                                                                    │ uses                                           │ built from
                                                         edu_support/ (pure rules, no I/O)                      data/full/csv
```

| File | Role |
|---|---|
| `frontend/app.js` | SPA; every dynamic string is inserted with `textContent` (no `innerHTML`) so request text cannot inject markup. CSP header forbids inline scripts. |
| `backend/server.py` | `ThreadingHTTPServer`; static files with path-traversal guard; 64 KB body limit; JSON errors; no stack traces leak. |
| `backend/api.py` | Route table, query/body parsing, maps `ApiError` → `{ "error": {code, message, details} }`. 400 bad syntax, 404, 405, 413, 422 validation, 409 state conflict, 403 permission. |
| `backend/services.py` | Every decision: create ticket, route preview, answer validation, lifecycle, escalation, feedback, sweep, metrics. Writes run in one transaction under a lock. |
| `backend/repository.py` | The only place with SQL for the app. |
| `edu_support/rules.py`, `bizhours.py`, `config.py` | Pure functions shared by the generator, the auditor and the live app — one definition of every rule. |
| `edu_support/dictionary.py` | Single source of truth: DDL, validator and `DATA_DICTIONARY.md` are all generated from it. |
| `edu_support/audit.py`, `evaluation.py` | Independent re-derivation of the five defect types from tables alone; scoring against `ground_truth/`. |
| `datagen/` | Deterministic generator, exporter, validator, reproducibility check. |

**Why one shared rules module?** If the generator, the app and the auditor each had their own idea of “business hours” or “escalate”, the checks would prove nothing. Sharing one implementation makes any disagreement a real bug.

**Why no framework?** The company laptop cannot install software; stdlib-only means `python -m backend.server` just works.

## Entities (19 tables, 161 fields)

Eleven required core entities map as: Requester→`requester`, Role→`role`, Term→`term`, PolicyDocument→`policy_document`, KnowledgeArticle→`knowledge_article`, Ticket→`ticket`, Message→`message`, Category→`category`, Assignment→`assignment`, SLA→`sla`, ResolutionFeedback→`resolution_feedback`. Support tables: `team`, `staff`, `sla_policy`, `holiday`, `routing_rule`, `team_category_authorization` (N:M team↔category), `message_article_link` (N:M message↔article, records the **cited version**), `ticket_event` (append-only history).
