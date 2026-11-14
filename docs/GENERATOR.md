# Synthetic data generator

`python -m datagen.generate --out DIR --tickets 5000 --articles 200 --messages 20000 --seed 20261022`

1. **Master data** — roles, terms, teams, categories (5 domains, level-2 leaves), SLA policies, holidays, 24 policy topics with several versions each (current/superseded/draft), requesters, staff, routing rules, authorisations.
2. **Pass 1 — clean baseline.** Each ticket is simulated from its own RNG (`"<seed>:sim:<n>"`) so ticket *n* never depends on others. Flows: plain answer, human-review, no-source, follow-up, ambiguous→clarify.
3. **Pass 2 — defect injection.** 1.2 % of tickets per type (60 each at 5,000) are re-simulated with exactly one defect: `expired_cite`, `wrong_team`, `unsupported_claim`, `calendar_clock`, `suppress_escalation`.
4. Internal notes top up to the exact message count; deterministic ID numbering; SLA and feedback **derived** from the event/message records (never invented); cut at the as-of date 2026-11-01.
5. **Export** CSV/JSON/SQL, `ground_truth/` (separate), `manifest.json` (counts + SHA-256), `source_manifest.json`.

Determinism: no `random` global state, no set/dict-order dependence; verified across different `PYTHONHASHSEED`s by `datagen.reproducibility`.

`ground_truth/` holds the labels (anomalies, expected category/team/priority/article/escalation per ticket). The application and auditor never read it; only `evaluation.py` and `validate.py` do, to score results.
