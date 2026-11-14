"""Data dictionary = single source of truth.

The dictionary below drives:   (1) the SQL DDL (schema.sql)   (2) the generic validator
(types / required / enums / ranges / patterns / unique / PK / FK)   (3) docs/DATA_DICTIONARY.md.

Field DSL (separator " ~ "):   name ~ type ~ R|O ~ constraints ~ unit ~ description
types: text int real bool date datetime json
constraints (';'-separated): PK  UNIQUE  FK:table.col  ENUM:a,b,c  RANGE:lo..hi  PATTERN:regex  LEN:lo..hi
"""
from collections import OrderedDict

PRIORITY_ENUM = "ENUM:low,normal,high,urgent"
STATUS_ENUM = "ENUM:new,triaged,assigned,in_progress,awaiting_requester,escalated,resolved,closed"
DOMAIN_ENUM = "ENUM:FIN,REG,IT,ACC,GEN"

TABLES = OrderedDict()
_ALIAS = {"PRIORITY_ENUM": PRIORITY_ENUM, "STATUS_ENUM": STATUS_ENUM, "DOMAIN_ENUM": DOMAIN_ENUM}


def _table(name, title, description, cardinality, fields, pk=None, unique=None):
    parsed = []
    for line in fields.strip().splitlines():
        line = line.replace(" ~ ~ ", " ~  ~ ")
        parts = [p.strip() for p in line.split(" ~ ")]
        assert len(parts) == 6, "bad dictionary line in %s: %r" % (name, line)
        fname, ftype, req, cons, unit, desc = parts
        c = {"enum": None, "range": None, "pattern": None, "len": None, "fk": None, "pk": False, "unique": False}
        for tok in [x for x in cons.split(";") if x]:
            tok = _ALIAS.get(tok, tok)
            if tok == "PK":
                c["pk"] = True
            elif tok == "UNIQUE":
                c["unique"] = True
            elif tok.startswith("FK:"):
                c["fk"] = tok[3:]
            elif tok.startswith("ENUM:"):
                c["enum"] = tok[5:].split(",")
            elif tok.startswith("RANGE:"):
                lo, hi = tok[6:].split("..")
                c["range"] = (float(lo), float(hi))
            elif tok.startswith("LEN:"):
                lo, hi = tok[4:].split("..")
                c["len"] = (int(lo), int(hi))
            elif tok.startswith("PATTERN:"):
                c["pattern"] = tok[8:]
            else:
                raise ValueError("unknown constraint %s" % tok)
        parsed.append({"name": fname, "type": ftype, "required": req == "R", "unit": "" if unit == "-" else unit,
                       "description": desc, **c})
    TABLES[name] = {"title": title, "description": description, "cardinality": cardinality,
                    "fields": parsed, "pk": pk, "unique": unique or []}


# ===================================================================================================
# MASTER / REFERENCE TABLES
# ===================================================================================================
_table("role", "Role", "Actor roles of the platform (learner, instructor, academic administrator, support staff, platform administrator).",
       "role 1:N requester; role 1:N staff", """
role_id ~ text ~ R ~ PK;PATTERN:^ROLE-[A-Z-]+$ ~ - ~ Immutable role key
role_name ~ text ~ R ~ UNIQUE;LEN:3..60 ~ - ~ Display name
actor_type ~ text ~ R ~ ENUM:learner,instructor,academic_administrator,support_staff,platform_administrator ~ - ~ Actor class named in the problem statement
can_raise_ticket ~ bool ~ R ~  ~ 0/1 ~ Role may submit requests
can_handle_ticket ~ bool ~ R ~  ~ 0/1 ~ Role may work / answer tickets
description ~ text ~ O ~ LEN:0..200 ~ - ~ Free text
""")

_table("term", "Term", "Academic terms; ticket.term_id links a request to the term it concerns.",
       "term 1:N ticket", """
term_id ~ text ~ R ~ PK;PATTERN:^TERM-\\d{4}-(SPR|SUM|FALL)$ ~ - ~ Immutable term key
term_name ~ text ~ R ~ LEN:3..40 ~ - ~ Display name
start_date ~ date ~ R ~  ~ ISO date ~ First day of classes
end_date ~ date ~ R ~  ~ ISO date ~ Last day of term (> start_date)
registration_opens ~ date ~ R ~  ~ ISO date ~ Registration window opens (< start_date)
add_drop_deadline ~ date ~ R ~  ~ ISO date ~ Last add/drop day (within term)
aid_deadline ~ date ~ R ~  ~ ISO date ~ Financial-aid completion deadline (within term)
""")

_table("team", "Team", "Handling teams (tier-1 domain desks, triage desk, tier-2 escalation teams).",
       "team 1:N staff; team N:M category (via team_category_authorization)", """
team_id ~ text ~ R ~ PK;PATTERN:^TEAM-[A-Z]+$ ~ - ~ Immutable team key
team_name ~ text ~ R ~ UNIQUE;LEN:3..60 ~ - ~ Display name
tier ~ int ~ R ~ ENUM:1,2 ~ level ~ 1 = first line, 2 = escalation / decision authority
domain ~ text ~ O ~ ENUM:FIN,REG,IT,ACC,GEN ~ - ~ Domain served (empty for cross-domain tier-2 teams)
""")

_table("category", "Category", "Two-level ticket category tree (domain -> leaf) plus the general triage category. Holds the routing keywords used by the router.",
       "category 1:N category (parent); category 1:N ticket; category 1:N knowledge_article; category N:M team", """
category_id ~ text ~ R ~ PK;PATTERN:^CAT-[A-Z]{2,3}(-\\d{2})?$ ~ - ~ Immutable category key
parent_category_id ~ text ~ O ~ FK:category.category_id ~ - ~ Parent (level-2 rows only)
name ~ text ~ R ~ LEN:3..80 ~ - ~ Display name
domain ~ text ~ R ~ DOMAIN_ENUM ~ - ~ Business domain (GEN = unclassified triage)
level ~ int ~ R ~ RANGE:1..2 ~ - ~ 1 = domain, 2 = leaf
default_priority ~ text ~ R ~ PRIORITY_ENUM ~ - ~ Priority before deadline rules
requires_human_review ~ bool ~ R ~  ~ 0/1 ~ Decisions in this category need a human decision-maker (rule E3)
routing_keywords ~ text ~ O ~ LEN:0..400 ~ pipe-separated ~ Keyword phrases the router counts as evidence
default_team_id ~ text ~ R ~ FK:team.team_id ~ - ~ Initial handling team
is_active ~ bool ~ R ~  ~ 0/1 ~ Category may be assigned
""")

_table("sla_policy", "SLA policy", "Response / resolution targets per priority. (Reference table backing the per-ticket SLA entity.)",
       "sla_policy 1:N sla", """
sla_policy_id ~ text ~ R ~ PK;PATTERN:^SLAP-[A-Z]+$ ~ - ~ Immutable policy key
priority ~ text ~ R ~ UNIQUE;PRIORITY_ENUM ~ - ~ Priority the policy applies to
first_response_hours ~ real ~ R ~ RANGE:0.25..200 ~ business hours ~ Target time to first human response
resolution_hours ~ real ~ R ~ RANGE:1..500 ~ business hours ~ Target time to resolution
uses_business_hours ~ bool ~ R ~  ~ 0/1 ~ Clock counts Mon-Fri 09:00-17:00 excluding holidays
effective_from ~ date ~ R ~  ~ ISO date ~ Start of validity
effective_to ~ date ~ O ~  ~ ISO date ~ End of validity (empty = open)
""")

_table("holiday", "Holiday", "Institute holidays excluded from the business-hours clock.",
       "reference only", """
holiday_date ~ date ~ R ~ PK ~ ISO date ~ Holiday date
holiday_name ~ text ~ R ~ LEN:3..80 ~ - ~ Description
""")

_table("policy_document", "PolicyDocument", "Synthetic policy documents (one per leaf category per policy revision). Revision 1 is superseded by revision 2 on 2026-07-01.",
       "policy_document 1:N knowledge_article; policy_document 1:1 policy_document (supersedes)", """
policy_id ~ text ~ R ~ PK;PATTERN:^POL-(FIN|REG|IT|ACC)-2026-\\d{3}$ ~ - ~ Immutable policy key POL-<domain>-2026-NNN
domain ~ text ~ R ~ ENUM:FIN,REG,IT,ACC ~ - ~ Policy domain
category_id ~ text ~ R ~ FK:category.category_id ~ - ~ Leaf category the policy governs
title ~ text ~ R ~ LEN:5..120 ~ - ~ Policy title
version_label ~ text ~ R ~ LEN:2..30 ~ - ~ Human revision label
effective_from ~ date ~ R ~ ~ ISO date ~ First day in force
effective_to ~ date ~ O ~ ~ ISO date ~ Last day in force (empty = open); must be >= effective_from
status ~ text ~ R ~ ENUM:draft,active,superseded ~ - ~ Lifecycle state at dataset as-of date
supersedes_policy_id ~ text ~ O ~ FK:policy_document.policy_id ~ - ~ Earlier revision replaced by this one
owner_team_id ~ text ~ R ~ FK:team.team_id ~ - ~ Owning team
source_type ~ text ~ R ~ ENUM:synthetic,public_reference ~ - ~ Provenance (all synthetic in this dataset)
source_note ~ text ~ O ~ LEN:0..200 ~ - ~ Provenance note
""")

_table("knowledge_article", "KnowledgeArticle", "Versioned knowledge-base articles with effective dates. A topic (topic_key) has 2-5 versions with contiguous, non-overlapping windows.",
       "policy_document 1:N article; topic 1:N article (versions); message N:M article (via message_article_link)", """
article_id ~ text ~ R ~ PK;PATTERN:^KB-\\d{6}$ ~ - ~ Immutable article-version key
topic_key ~ text ~ R ~ PATTERN:^(FIN|REG|IT|ACC)-\\d{2}-\\d$ ~ - ~ Stable key shared by all versions of one topic
version_no ~ int ~ R ~ RANGE:1..9 ~ - ~ Version within the topic (1-based, gap-free)
policy_id ~ text ~ R ~ FK:policy_document.policy_id ~ - ~ Source policy revision (article window lies inside policy window)
category_id ~ text ~ R ~ FK:category.category_id ~ - ~ Leaf category
title ~ text ~ R ~ LEN:5..120 ~ - ~ Topic title (same across versions)
body ~ text ~ R ~ LEN:20..1500 ~ - ~ Article text; the only source of facts an answer may state
key_fact_value ~ real ~ R ~ ~ see key_fact_unit ~ Numeric fact stated in the body (changes between versions)
key_fact_unit ~ text ~ R ~ LEN:1..40 ~ - ~ Unit of the numeric fact
effective_from ~ date ~ R ~ ~ ISO date ~ First day this version is valid
effective_to ~ date ~ O ~ ~ ISO date ~ Last day valid (inclusive); empty = open-ended
status ~ text ~ R ~ ENUM:draft,current,superseded ~ - ~ draft = not yet effective at as-of; superseded = window closed
supersedes_article_id ~ text ~ O ~ FK:knowledge_article.article_id ~ - ~ Previous version of the same topic
audience ~ text ~ R ~ ENUM:student,faculty,both ~ - ~ Intended audience
""", unique=[("topic_key", "version_no")])

_table("requester", "Requester", "People who raise tickets (learners and instructors). Synthetic persons on the reserved example.edu domain.",
       "role 1:N requester; requester 1:N ticket", """
requester_id ~ text ~ R ~ PK;PATTERN:^REQ-\\d{6}$ ~ - ~ Immutable requester key
role_id ~ text ~ R ~ FK:role.role_id ~ - ~ Learner or instructor
full_name ~ text ~ R ~ LEN:3..80 ~ - ~ Synthetic name
email ~ text ~ R ~ UNIQUE;PATTERN:^[a-z0-9.]+@example\\.edu$ ~ - ~ Synthetic e-mail (reserved example.edu domain)
department ~ text ~ R ~ LEN:2..60 ~ - ~ Academic department
program_level ~ text ~ O ~ ENUM:UG,PG ~ - ~ Learners only
enrollment_year ~ int ~ O ~ RANGE:2018..2026 ~ year ~ Learners only
active_from ~ date ~ R ~ ~ ISO date ~ Start of active relationship
active_to ~ date ~ O ~ ~ ISO date ~ End of active relationship (graduated / left); empty = active
status ~ text ~ R ~ ENUM:active,inactive ~ - ~ active_to empty <=> active
""")

_table("staff", "Staff", "Handlers (support staff, academic administrators, platform administrators) who belong to exactly one team.",
       "team 1:N staff; role 1:N staff; staff 1:N assignment", """
staff_id ~ text ~ R ~ PK;PATTERN:^STF-\\d{4}$ ~ - ~ Immutable staff key
full_name ~ text ~ R ~ LEN:3..80 ~ - ~ Synthetic name
email ~ text ~ R ~ UNIQUE;PATTERN:^[a-z0-9.]+@example\\.edu$ ~ - ~ Synthetic e-mail
role_id ~ text ~ R ~ FK:role.role_id ~ - ~ Handling role (can_handle_ticket must be 1)
team_id ~ text ~ R ~ FK:team.team_id ~ - ~ Team
active_from ~ date ~ R ~ ~ ISO date ~ Start date
active_to ~ date ~ O ~ ~ ISO date ~ Leaving date; staff cannot be assigned after it
""")

# ===================================================================================================
# BRIDGE / RULE TABLES
# ===================================================================================================
_table("team_category_authorization", "TeamCategoryAuthorization (bridge)", "N:M bridge: which team may handle (tier 1) or take escalations (tier 2) for which category.",
       "team N:M category", """
team_id ~ text ~ R ~ FK:team.team_id ~ - ~ Team
category_id ~ text ~ R ~ FK:category.category_id ~ - ~ Category
access_level ~ text ~ R ~ ENUM:handle,escalation ~ - ~ handle = may own initial / re-assigned tickets; escalation = may receive escalations only
""", pk=["team_id", "category_id"])

_table("routing_rule", "RoutingRule", "Documented routing rules: category -> initial team, category -> escalation team.",
       "category 1:N routing_rule; team 1:N routing_rule; routing_rule 1:N assignment", """
rule_id ~ text ~ R ~ PK;PATTERN:^RULE-\\d{3}$ ~ - ~ Immutable rule key
category_id ~ text ~ R ~ FK:category.category_id ~ - ~ Category the rule applies to
team_id ~ text ~ R ~ FK:team.team_id ~ - ~ Target team (must be authorized for the category)
rule_type ~ text ~ R ~ ENUM:initial,escalation ~ - ~ initial routing or escalation target
effective_from ~ date ~ R ~ ~ ISO date ~ Start of validity
effective_to ~ date ~ O ~ ~ ISO date ~ End of validity
""")

# ===================================================================================================
# TRANSACTION / EVENT TABLES
# ===================================================================================================
_table("ticket", "Ticket", "A request from a learner / instructor. Holds CURRENT state only; every change is also stored as a ticket_event row (history is never overwritten).",
       "requester 1:N ticket; term 1:N ticket; category 1:N ticket; ticket 1:N message / assignment / ticket_event; ticket 1:1 sla; ticket 0..1 resolution_feedback", """
ticket_id ~ text ~ R ~ PK;PATTERN:^TKT-2026-\\d{6}$ ~ - ~ Immutable key TKT-2026-NNNNNN
requester_id ~ text ~ R ~ FK:requester.requester_id ~ - ~ Who raised it (must be active on created_at)
term_id ~ text ~ R ~ FK:term.term_id ~ - ~ Term the request concerns
category_id ~ text ~ R ~ FK:category.category_id ~ - ~ CURRENT category (history in ticket_event)
priority ~ text ~ R ~ PRIORITY_ENUM ~ - ~ Derived by rule from category default + deadline + urgency words
status ~ text ~ R ~ STATUS_ENUM ~ - ~ CURRENT lifecycle status (= to_status of last event)
channel ~ text ~ R ~ ENUM:portal,email,phone,walk_in ~ - ~ Intake channel
subject ~ text ~ R ~ LEN:5..200 ~ - ~ Subject line
body ~ text ~ R ~ LEN:10..5000 ~ - ~ Original request text (= first message)
deadline_date ~ date ~ O ~ ~ ISO date ~ Requester-stated deadline (>= created date)
created_at ~ datetime ~ R ~ ~ campus local time ~ Creation instant
updated_at ~ datetime ~ R ~ ~ campus local time ~ Time of last event (>= created_at)
current_team_id ~ text ~ R ~ FK:team.team_id ~ - ~ Team of the open assignment
""")

_table("message", "Message", "Message history of a ticket (requester, staff and system messages, incl. internal notes).",
       "ticket 1:N message; message N:M knowledge_article (via message_article_link)", """
message_id ~ text ~ R ~ PK;PATTERN:^MSG-TKT-2026-\\d{6}-\\d{3}$ ~ - ~ Immutable key MSG-<ticket-id>-NNN
ticket_id ~ text ~ R ~ FK:ticket.ticket_id ~ - ~ Parent ticket
seq_no ~ int ~ R ~ RANGE:1..999 ~ - ~ 1-based, gap-free, ordered by created_at
sender_type ~ text ~ R ~ ENUM:requester,staff,system ~ - ~ Author class
requester_id ~ text ~ O ~ FK:requester.requester_id ~ - ~ Set iff sender_type = requester
staff_id ~ text ~ O ~ FK:staff.staff_id ~ - ~ Set iff sender_type = staff
message_type ~ text ~ R ~ ENUM:question,acknowledgement,clarification_request,clarification_reply,answer,followup,escalation_notice,internal_note,confirmation,reopen_request ~ - ~ Semantic type
is_internal ~ bool ~ R ~ ~ 0/1 ~ Internal staff note (hidden from requester)
body ~ text ~ R ~ LEN:1..5000 ~ - ~ Message text
created_at ~ datetime ~ R ~ ~ campus local time ~ Send time
""", unique=[("ticket_id", "seq_no")])

_table("message_article_link", "MessageArticleLink (bridge)", "N:M bridge linking an answer message to the exact article VERSION it cites (version is recorded).",
       "message N:M knowledge_article", """
message_id ~ text ~ R ~ FK:message.message_id ~ - ~ Citing message
article_id ~ text ~ R ~ FK:knowledge_article.article_id ~ - ~ Cited article version
cited_version_no ~ int ~ R ~ RANGE:1..9 ~ - ~ Version number recorded at citation time (= article.version_no)
relevance_score ~ real ~ R ~ RANGE:0..1 ~ ratio ~ Title-token coverage of the retrieval match
citation_role ~ text ~ R ~ ENUM:primary,supporting ~ - ~ Role of the citation
""", pk=["message_id", "article_id"])

_table("assignment", "Assignment", "Assignment history: one row per (re)assignment / escalation. Rows are closed (unassigned_at) never overwritten.",
       "ticket 1:N assignment; team 1:N assignment; staff 1:N assignment", """
assignment_id ~ text ~ R ~ PK;PATTERN:^ASG-TKT-2026-\\d{6}-\\d{2}$ ~ - ~ Immutable key ASG-<ticket-id>-NN
ticket_id ~ text ~ R ~ FK:ticket.ticket_id ~ - ~ Parent ticket
team_id ~ text ~ R ~ FK:team.team_id ~ - ~ Receiving team
staff_id ~ text ~ R ~ FK:staff.staff_id ~ - ~ Owner (must belong to team_id and be active)
assignment_type ~ text ~ R ~ ENUM:initial,reassignment,escalation ~ - ~ Why the row exists
category_id_at_assignment ~ text ~ R ~ FK:category.category_id ~ - ~ Ticket category when the assignment was made
routing_rule_id ~ text ~ O ~ FK:routing_rule.rule_id ~ - ~ Rule that produced the decision
assigned_at ~ datetime ~ R ~ ~ campus local time ~ Start
unassigned_at ~ datetime ~ O ~ ~ campus local time ~ End (empty = open); >= assigned_at
assigned_by ~ text ~ R ~ ENUM:system,staff ~ - ~ Decision maker
""")

_table("sla", "SLA", "Per-ticket SLA clock (SLA-<ticket-id>). Due times are derived from the policy and the business calendar; statuses derived from messages / events.",
       "ticket 1:1 sla; sla_policy 1:N sla", """
sla_id ~ text ~ R ~ PK;PATTERN:^SLA-TKT-2026-\\d{6}$ ~ - ~ Immutable key SLA-<ticket-id>
ticket_id ~ text ~ R ~ UNIQUE;FK:ticket.ticket_id ~ - ~ Ticket
sla_policy_id ~ text ~ R ~ FK:sla_policy.sla_policy_id ~ - ~ Policy applied
priority ~ text ~ R ~ PRIORITY_ENUM ~ - ~ Priority at creation
clock_mode ~ text ~ R ~ ENUM:business,calendar ~ - ~ business = Mon-Fri 09-17 excl. holidays; calendar = wall clock (non-compliant)
clock_start ~ datetime ~ R ~ ~ campus local time ~ = ticket.created_at
first_response_due ~ datetime ~ R ~ ~ campus local time ~ clock_start + first_response_hours on the clock
resolution_due ~ datetime ~ R ~ ~ campus local time ~ clock_start + resolution_hours on the clock
first_response_at ~ datetime ~ O ~ ~ campus local time ~ First public staff message (clarification_request / answer)
resolved_at ~ datetime ~ O ~ ~ campus local time ~ Last 'resolved' event while status is resolved/closed
first_response_status ~ text ~ R ~ ENUM:met,breached,pending ~ - ~ Derived vs. due date and as-of
resolution_status ~ text ~ R ~ ENUM:met,breached,pending ~ - ~ Derived vs. due date and as-of
first_response_business_hours ~ real ~ O ~ RANGE:0..5000 ~ business hours ~ Derived elapsed business time to first response
resolution_business_hours ~ real ~ O ~ RANGE:0..5000 ~ business hours ~ Derived elapsed business time to resolution
""")

_table("ticket_event", "TicketEvent", "Append-only state-change log. Every status / category / assignment change is an event.",
       "ticket 1:N ticket_event", """
event_id ~ text ~ R ~ PK;PATTERN:^EVT-TKT-2026-\\d{6}-\\d{3}$ ~ - ~ Immutable key EVT-<ticket-id>-NNN
ticket_id ~ text ~ R ~ FK:ticket.ticket_id ~ - ~ Parent ticket
seq_no ~ int ~ R ~ RANGE:1..999 ~ - ~ 1-based, gap-free
event_type ~ text ~ R ~ ENUM:created,triaged,assigned,started,awaiting_requester,requester_replied,escalated,recategorized,reassigned,resolved,closed,reopened ~ - ~ Event kind
from_status ~ text ~ O ~ STATUS_ENUM ~ - ~ Status before (empty only for 'created')
to_status ~ text ~ R ~ STATUS_ENUM ~ - ~ Status after
event_at ~ datetime ~ R ~ ~ campus local time ~ Event instant (non-decreasing within ticket)
actor_type ~ text ~ R ~ ENUM:requester,staff,system ~ - ~ Who caused it
actor_id ~ text ~ O ~ ~ - ~ requester_id / staff_id (empty for system)
details ~ json ~ O ~ ~ JSON ~ Decision trace (rule inputs, reasons, from/to category, team ...)
""", unique=[("ticket_id", "seq_no")])

_table("resolution_feedback", "ResolutionFeedback", "Resolution record and requester feedback for a resolved / closed ticket (1:1 with ticket, optional).",
       "ticket 1:0..1 resolution_feedback", """
feedback_id ~ text ~ R ~ PK;PATTERN:^FB-TKT-2026-\\d{6}$ ~ - ~ Immutable key FB-<ticket-id>
ticket_id ~ text ~ R ~ UNIQUE;FK:ticket.ticket_id ~ - ~ Ticket
resolution_code ~ text ~ R ~ ENUM:answered_from_kb,resolved_by_staff,resolved_by_escalation,no_response_closed ~ - ~ How it ended
resolved_at ~ datetime ~ R ~ ~ campus local time ~ Time of the last 'resolved' event
resolution_calendar_hours ~ real ~ R ~ RANGE:0..20000 ~ hours ~ Derived: resolved_at - created_at
resolution_business_hours ~ real ~ R ~ RANGE:0..5000 ~ business hours ~ Derived: business time between created_at and resolved_at
reopen_count ~ int ~ R ~ RANGE:0..20 ~ - ~ Derived: number of 'reopened' events
csat ~ int ~ O ~ RANGE:1..5 ~ score ~ Requester satisfaction (optional)
answer_helpful ~ bool ~ O ~ ~ 0/1 ~ Requester judged the answer helpful
comment ~ text ~ O ~ LEN:0..1000 ~ - ~ Free-text comment
feedback_at ~ datetime ~ O ~ ~ campus local time ~ When feedback was given (>= resolved_at)
""")


# ===================================================================================================
# helpers
# ===================================================================================================
def columns(table):
    return [f["name"] for f in TABLES[table]["fields"]]


def to_sql_type(t):
    return {"text": "TEXT", "int": "INTEGER", "real": "REAL", "bool": "INTEGER",
            "date": "TEXT", "datetime": "TEXT", "json": "TEXT"}[t]


def ddl():
    out = ["-- AUTO-GENERATED from edu_support/dictionary.py  (do not edit by hand)", "PRAGMA foreign_keys = ON;", ""]
    for name, t in TABLES.items():
        lines, fks = [], []
        for f in t["fields"]:
            parts = ["  %s %s" % (f["name"], to_sql_type(f["type"]))]
            if f["required"]:
                parts.append("NOT NULL")
            if f["pk"] and not t["pk"]:
                parts.append("PRIMARY KEY")
            if f["unique"]:
                parts.append("UNIQUE")
            if f["enum"]:
                vals = f["enum"]
                q = ",".join(v if f["type"] == "int" else "'%s'" % v for v in vals)
                parts.append("CHECK (%s IN (%s))" % (f["name"], q))
            if f["type"] == "bool":
                parts.append("CHECK (%s IN (0,1))" % f["name"])
            if f["range"]:
                parts.append("CHECK (%s BETWEEN %s AND %s)" % (f["name"], f["range"][0], f["range"][1]))
            lines.append(" ".join(parts))
            if f["fk"]:
                tt, cc = f["fk"].split(".")
                fks.append("  FOREIGN KEY (%s) REFERENCES %s(%s)" % (f["name"], tt, cc))
        if t["pk"]:
            lines.append("  PRIMARY KEY (%s)" % ", ".join(t["pk"]))
        for u in t["unique"]:
            lines.append("  UNIQUE (%s)" % ", ".join(u))
        out.append("CREATE TABLE %s (\n%s\n);" % (name, ",\n".join(lines + fks)))
        out.append("")
    out += [
        "CREATE INDEX ix_ticket_status ON ticket(status);",
        "CREATE INDEX ix_ticket_category ON ticket(category_id);",
        "CREATE INDEX ix_ticket_requester ON ticket(requester_id);",
        "CREATE INDEX ix_ticket_created ON ticket(created_at);",
        "CREATE INDEX ix_message_ticket ON message(ticket_id);",
        "CREATE INDEX ix_event_ticket ON ticket_event(ticket_id);",
        "CREATE INDEX ix_assign_ticket ON assignment(ticket_id);",
        "CREATE INDEX ix_article_topic ON knowledge_article(topic_key);",
        "",
    ]
    return "\n".join(out)

