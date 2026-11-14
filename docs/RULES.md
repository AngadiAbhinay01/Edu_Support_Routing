# Business rules

All constants are in `edu_support/config.py`.

## Classification (`rules.classify`)
Domain score = number of distinct keyword phrases found (generic domain keywords + leaf-specific keywords; light plural stemming). Leaf = best leaf in the winning domain, else the domain category. **Ambiguous** if top score < 2 or lead over runner-up < 2 → category `CAT-GEN`, team `TEAM-TRIAGE`, clarification requested.

## Priority
Category default; raised for deadlines within 2 days or urgency words (“urgent”, “exam today” …). See `rules.derive_priority`; the reasons are stored in the `triaged` event.

## Business hours and SLA
Mon–Fri 09:00–17:00, holidays excluded (`holiday` table). Hours (first response / resolution): urgent 1/16, high 4/40, normal 8/72, low 16/120. A ticket raised Friday 16:30 with a 1-hour target is due **Monday 09:30**. Wall-clock SLAs are the injected defect `SLA_IGNORES_BUSINESS_HOURS`.

## Retrieval
`match_topic` needs ≥ 2 title tokens and ≥ 67 % title coverage. `effective_article(versions, at)` selects the version in force on the message date. Every citation stores `cited_version_no`.

## Answer controls (reject with 422)
`ARTICLE_NOT_EFFECTIVE` (expired/draft/not yet valid), `MISSING_CITATION` (a source exists but none cited), `UNSUPPORTED_CLAIM` (a number not in any cited source), `CITATION_DOMAIN_MISMATCH`, `UNKNOWN_ARTICLE`, `CITATION_NOT_ALLOWED` (internal notes).

## Routing controls
`team_category_authorization` lists who may `handle` or only receive `escalation` for each category. Assignment to anyone else → `UNAUTHORIZED_TEAM`.

## Escalation (10-minute grace)
| Rule | Fires when |
|---|---|
| E1 | ambiguous and still unresolved after clarification, or no reply after 16 business hours |
| E2 | no KB source found (after first staff response) |
| E3 | category requires human review (FIN-04, REG-04, IT-04, ACC-04) |
| E4 | urgent ticket missed first-response SLA |
| E5 | ≥ 2 follow-ups |
Tier-2: `TEAM-ADMIN` (FIN/REG/ACC/GEN), `TEAM-PLAT` (IT). A ticket cannot be resolved while a fired rule is unescalated (`ESCALATION_REQUIRED`). `POST /api/admin/sweep` (dry-run by default) applies time-based rules.

## Life-cycle
`new → triaged → assigned → in_progress ⇄ awaiting_requester → resolved → closed`; `escalated` from in-progress states; reopen (requester only) from resolved, or from closed within 14 days. Resolved tickets auto-close after 7 days (sweep). Exact table: `config.TRANSITIONS`.
