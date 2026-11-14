# Validation summary

Data set: `data/sample`  |  as-of: 2026-11-01 00:00:00  |  checks passed: **44 / 44**

## Row counts

| table | rows |
|---|---:|
| role | 5 |
| term | 5 |
| team | 7 |
| category | 21 |
| sla_policy | 4 |
| holiday | 8 |
| policy_document | 32 |
| knowledge_article | 60 |
| requester | 90 |
| staff | 14 |
| team_category_authorization | 42 |
| routing_rule | 42 |
| ticket | 300 |
| message | 1200 |
| message_article_link | 324 |
| assignment | 371 |
| sla | 300 |
| ticket_event | 2407 |
| resolution_feedback | 283 |

## Integrity checks

| group | check | what is verified | items checked | violations | result |
|---|---|---|---:|---:|---|
| schema | `csv_headers_match_dictionary` | CSV header == data-dictionary column list (names and order) | 19 | 0 | PASS |
| schema | `required_fields_present` | Every field marked R in the dictionary is non-empty | 41965 | 0 | PASS |
| schema | `types_parse` | int / real / bool(0,1) / date / datetime values parse | 50173 | 0 | PASS |
| domain | `allowed_enums` | Enumerated fields contain only allowed values | 15707 | 0 | PASS |
| domain | `numeric_ranges` | Numeric fields lie inside the documented RANGE | 6035 | 0 | PASS |
| domain | `id_and_format_patterns` | PATTERN constraints (ID conventions, e-mail format) hold | 5305 | 0 | PASS |
| domain | `text_lengths` | Text fields respect the documented LEN bounds | 2342 | 0 | PASS |
| keys | `primary_key_uniqueness` | Primary keys are unique (single and composite) | 5515 | 0 | PASS |
| keys | `unique_constraints` | UNIQUE fields / composite unique sets contain no duplicates | 4370 | 0 | PASS |
| keys | `foreign_key_integrity` | Every FK value exists in its parent table (join validation) | 9714 | 0 | PASS |
| dates | `term_dates_ordered` | registration_opens < start_date < end_date; add/drop and aid deadlines inside the term | 5 | 0 | PASS |
| dates | `policy_windows` | policy effective_from <= effective_to; superseded policies have an end date; status matches as-of date | 64 | 0 | PASS |
| dates | `article_version_chain` | Versions per topic are gap-free (1..k), windows contiguous & non-overlapping, only the last is open-ended, status matches as-of date, window lies inside the source policy window | 324 | 0 | PASS |
| dates | `person_active_windows` | requester/staff active_from <= active_to; requester.status consistent with active_to | 194 | 0 | PASS |
| dates | `ticket_dates` | created_at <= updated_at; deadline >= created date; requester active at creation; term window covers creation | 1200 | 0 | PASS |
| dates | `message_order` | Message seq_no contiguous 1..n, created_at non-decreasing, first message = ticket body at created_at, none before ticket | 3785 | 0 | PASS |
| dates | `event_order` | Event seq_no contiguous, event_at non-decreasing and >= ticket.created_at | 600 | 0 | PASS |
| dates | `assignment_windows` | assigned_at <= unassigned_at; assigned_at >= ticket creation; consecutive assignments do not overlap | 442 | 0 | PASS |
| dates | `sla_times` | sla.clock_start = ticket.created_at; due >= start; response / resolution >= start | 1200 | 0 | PASS |
| dates | `feedback_times` | resolved_at >= created_at; feedback_at >= resolved_at | 283 | 0 | PASS |
| lifecycle | `event_chain_and_transitions` | First event is 'created'; each from_status = previous to_status; every transition is in the allowed table | 300 | 0 | PASS |
| lifecycle | `ticket_state_matches_history` | ticket.status = last event.to_status; updated_at = last event_at; category = last (re)categorisation; current_team = last assignment | 300 | 0 | PASS |
| lifecycle | `closed_after_resolved_and_feedback` | 'closed' only after 'resolved'; feedback exists iff the ticket currently is resolved/closed | 577 | 0 | PASS |
| lifecycle | `escalation_consistency` | Every 'escalated' event has a matching 'escalation' assignment (same instant) and vice versa; escalate at most once | 300 | 0 | PASS |
| lifecycle | `assignment_actors_valid` | Assigned staff belong to the team, hold a handling role and are active (with a 45-day horizon) | 371 | 0 | PASS |
| lifecycle | `single_open_assignment` | At most one open assignment per ticket and none after 'closed' | 300 | 0 | PASS |
| lifecycle | `requester_roles_can_raise` | Ticket requesters hold a role that may raise tickets | 300 | 0 | PASS |
| lifecycle | `staff_message_authors_assigned` | Staff authors of public/internal messages belong to a team that held the ticket at that time | 481 | 0 | PASS |
| arithmetic | `sla_status_reconciles` | first_response_status / resolution_status recomputed from stored due, response / resolution times and the as-of date | 300 | 0 | PASS |
| arithmetic | `sla_hours_reconcile` | first_response_business_hours / resolution_business_hours = business hours between created_at and the event | 300 | 0 | PASS |
| arithmetic | `sla_sources_reconcile` | sla.first_response_at = first public staff response; sla.resolved_at = feedback.resolved_at; sla.priority = ticket.priority | 300 | 0 | PASS |
| arithmetic | `feedback_derived_fields` | resolution_calendar/business hours and reopen_count recomputed from events; resolution_code equals the last 'resolved' event | 283 | 0 | PASS |
| arithmetic | `priority_follows_rule` | ticket.priority = derive_priority(category default, deadline, urgency words) | 300 | 0 | PASS |
| arithmetic | `routing_follows_rule` | Triage decision (category, ambiguity) = classify(subject + body); initial team = routing rule of the category (unless staff override) | 596 | 0 | PASS |
| arithmetic | `citation_version_recorded` | message_article_link.cited_version_no = article.version_no; links only on public staff 'answer' messages | 324 | 0 | PASS |
| arithmetic | `volume_totals` | Every ticket has >= 1 message (the request) and exactly one SLA row | 301 | 0 | PASS |
| duplicates | `duplicate_tickets` | No two tickets share (requester, subject, body, created_at) | 300 | 0 | PASS |
| duplicates | `duplicate_articles` | No two article versions of a topic share the same key fact value consecutively unless intended; no duplicate (topic, version) | 24 | 0 | PASS |
| duplicates | `duplicate_messages` | No duplicate (ticket, sender, type, created_at, body) | 1200 | 0 | PASS |
| ids | `ticket_ids_contiguous` | TKT-2026-000001..N has no gaps; KB-000001..N has no gaps; REQ / STF contiguous | 5 | 0 | PASS |
| ids | `policy_ids_follow_convention` | POL-<domain>-2026-NNN with the domain matching the policy domain and gap-free counters per domain | 36 | 0 | PASS |
| leakage | `ground_truth_not_in_input_tables` | No input column carries ground-truth labels (issue_type, expected_*, true_*, scenario, kind, is_ambiguous ...) | 161 | 0 | PASS |
| leakage | `ground_truth_is_separate_and_joinable` | ground_truth.csv lives in its own folder and every ticket_id joins to ticket (1:1) | 2 | 0 | PASS |
| database | `loads_into_sqlite_with_constraints` | CSV loads into SQLite with PRIMARY KEY / FOREIGN KEY / CHECK constraints enforced | 1 | 0 | PASS |

## Rule engine / auditor vs. separate ground truth

Ground truth is read only by the evaluator; the auditor works from the input tables alone.

| anomaly type | TP | FP | FN | precision | recall |
|---|---:|---:|---:|---:|---:|
| EXPIRED_POLICY_CITATION | 4 | 0 | 0 | 1.000 | 1.000 |
| UNAUTHORIZED_ROUTING | 4 | 0 | 0 | 1.000 | 1.000 |
| UNSUPPORTED_CLAIM | 4 | 0 | 0 | 1.000 | 1.000 |
| SLA_IGNORES_BUSINESS_HOURS | 4 | 0 | 0 | 1.000 | 1.000 |
| ESCALATION_NOT_TRIGGERED | 4 | 0 | 0 | 1.000 | 1.000 |
| **overall** | 20 | 0 | 0 | 1.000 | 1.000 |

| metric | value |
|---|---:|
| router category accuracy | 1.0000 |
| router domain accuracy (non-ambiguous) | 1.0000 |
| ambiguity detection precision / recall | 1.000 / 1.000 |
| priority accuracy | 1.0000 |
| initial team accuracy | 0.9867 |
| escalation precision / recall vs expected | 1.000 / 0.939 |
| first cited article accuracy | 0.9854 |

### Acceptance criteria

| criterion | measured |
|---|---|
| answers cite current sources | cited_answers=324, citing_expired_version=4, rate_current=0.9877 |
| routing is consistent | initial_assignments=300, to_authorised_team_rate=0.9867 |
| unresolved or ambiguous cases escalate | expected_escalations=66, escalated=62, rate=0.9394 |
| article version recorded | links=324, version_recorded_correctly=324, rate=1.0 |
