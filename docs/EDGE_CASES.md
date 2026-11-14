# Edge cases and validation cases covered

Each item is exercised by a test in `tests/` (`test_api.py` unless noted).

**Input:** missing/malformed fields · wrong JSON types · non-object body · invalid JSON · body > 64 KB (413) · over-long subject/body · bad channel · past/unparseable/over-a-year deadline · unknown requester (404) · bad id formats (400) · unknown route (404) · wrong method (405) · bad pagination (`size=1000`, `page=-1`) · SQL-injection-shaped search text stays inert · HTML in a ticket is stored verbatim and rendered as text.

**Requests:** duplicate ticket within 24 h (409, whitespace/case-insensitive) · ambiguous text → triage + clarification · sequential ticket numbers · Friday-evening SLA rolls to Monday · preview writes nothing.

**Answers:** no citation when a source exists · invented number · expired article · draft article · unknown article · citation inside an internal note · wrong-team staff cannot reply · non-owner requester cannot post · message type must match sender.

**Life-cycle:** illegal transitions (409 with allowed list) · resolve before any public response · resolution code required · feedback before resolution · feedback twice · CSAT out of range · reopen by requester · manual escalation needs a reason and routes to tier 2 · human-review ticket cannot be resolved until escalated (`ESCALATION_REQUIRED`) and the sweep escalates it · assignment to an unauthorised team.

**Data (`test_generator.py`, `datagen.validate`):** exact volumes · ID formats · five labelled defect types · no ground-truth columns in input tables · same seed ⇒ identical SHA-256, different seed ⇒ different · too few articles rejected · primary/foreign keys, enums, ranges, date ordering, SLA arithmetic, lifecycle order, duplicates (44 checks).

**Time (`test_bizhours.py`):** within day, overnight, weekend, before opening, exactly at close, zero hours, inverse of add, calendar vs business.
