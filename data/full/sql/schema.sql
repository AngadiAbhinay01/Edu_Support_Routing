-- AUTO-GENERATED from edu_support/dictionary.py  (do not edit by hand)
PRAGMA foreign_keys = ON;

CREATE TABLE role (
  role_id TEXT NOT NULL PRIMARY KEY,
  role_name TEXT NOT NULL UNIQUE,
  actor_type TEXT NOT NULL CHECK (actor_type IN ('learner','instructor','academic_administrator','support_staff','platform_administrator')),
  can_raise_ticket INTEGER NOT NULL CHECK (can_raise_ticket IN (0,1)),
  can_handle_ticket INTEGER NOT NULL CHECK (can_handle_ticket IN (0,1)),
  description TEXT
);

CREATE TABLE term (
  term_id TEXT NOT NULL PRIMARY KEY,
  term_name TEXT NOT NULL,
  start_date TEXT NOT NULL,
  end_date TEXT NOT NULL,
  registration_opens TEXT NOT NULL,
  add_drop_deadline TEXT NOT NULL,
  aid_deadline TEXT NOT NULL
);

CREATE TABLE team (
  team_id TEXT NOT NULL PRIMARY KEY,
  team_name TEXT NOT NULL UNIQUE,
  tier INTEGER NOT NULL CHECK (tier IN (1,2)),
  domain TEXT CHECK (domain IN ('FIN','REG','IT','ACC','GEN'))
);

CREATE TABLE category (
  category_id TEXT NOT NULL PRIMARY KEY,
  parent_category_id TEXT,
  name TEXT NOT NULL,
  domain TEXT NOT NULL CHECK (domain IN ('FIN','REG','IT','ACC','GEN')),
  level INTEGER NOT NULL CHECK (level BETWEEN 1.0 AND 2.0),
  default_priority TEXT NOT NULL CHECK (default_priority IN ('low','normal','high','urgent')),
  requires_human_review INTEGER NOT NULL CHECK (requires_human_review IN (0,1)),
  routing_keywords TEXT,
  default_team_id TEXT NOT NULL,
  is_active INTEGER NOT NULL CHECK (is_active IN (0,1)),
  FOREIGN KEY (parent_category_id) REFERENCES category(category_id),
  FOREIGN KEY (default_team_id) REFERENCES team(team_id)
);

CREATE TABLE sla_policy (
  sla_policy_id TEXT NOT NULL PRIMARY KEY,
  priority TEXT NOT NULL UNIQUE CHECK (priority IN ('low','normal','high','urgent')),
  first_response_hours REAL NOT NULL CHECK (first_response_hours BETWEEN 0.25 AND 200.0),
  resolution_hours REAL NOT NULL CHECK (resolution_hours BETWEEN 1.0 AND 500.0),
  uses_business_hours INTEGER NOT NULL CHECK (uses_business_hours IN (0,1)),
  effective_from TEXT NOT NULL,
  effective_to TEXT
);

CREATE TABLE holiday (
  holiday_date TEXT NOT NULL PRIMARY KEY,
  holiday_name TEXT NOT NULL
);

CREATE TABLE policy_document (
  policy_id TEXT NOT NULL PRIMARY KEY,
  domain TEXT NOT NULL CHECK (domain IN ('FIN','REG','IT','ACC')),
  category_id TEXT NOT NULL,
  title TEXT NOT NULL,
  version_label TEXT NOT NULL,
  effective_from TEXT NOT NULL,
  effective_to TEXT,
  status TEXT NOT NULL CHECK (status IN ('draft','active','superseded')),
  supersedes_policy_id TEXT,
  owner_team_id TEXT NOT NULL,
  source_type TEXT NOT NULL CHECK (source_type IN ('synthetic','public_reference')),
  source_note TEXT,
  FOREIGN KEY (category_id) REFERENCES category(category_id),
  FOREIGN KEY (supersedes_policy_id) REFERENCES policy_document(policy_id),
  FOREIGN KEY (owner_team_id) REFERENCES team(team_id)
);

CREATE TABLE knowledge_article (
  article_id TEXT NOT NULL PRIMARY KEY,
  topic_key TEXT NOT NULL,
  version_no INTEGER NOT NULL CHECK (version_no BETWEEN 1.0 AND 9.0),
  policy_id TEXT NOT NULL,
  category_id TEXT NOT NULL,
  title TEXT NOT NULL,
  body TEXT NOT NULL,
  key_fact_value REAL NOT NULL,
  key_fact_unit TEXT NOT NULL,
  effective_from TEXT NOT NULL,
  effective_to TEXT,
  status TEXT NOT NULL CHECK (status IN ('draft','current','superseded')),
  supersedes_article_id TEXT,
  audience TEXT NOT NULL CHECK (audience IN ('student','faculty','both')),
  UNIQUE (topic_key, version_no),
  FOREIGN KEY (policy_id) REFERENCES policy_document(policy_id),
  FOREIGN KEY (category_id) REFERENCES category(category_id),
  FOREIGN KEY (supersedes_article_id) REFERENCES knowledge_article(article_id)
);

CREATE TABLE requester (
  requester_id TEXT NOT NULL PRIMARY KEY,
  role_id TEXT NOT NULL,
  full_name TEXT NOT NULL,
  email TEXT NOT NULL UNIQUE,
  department TEXT NOT NULL,
  program_level TEXT CHECK (program_level IN ('UG','PG')),
  enrollment_year INTEGER CHECK (enrollment_year BETWEEN 2018.0 AND 2026.0),
  active_from TEXT NOT NULL,
  active_to TEXT,
  status TEXT NOT NULL CHECK (status IN ('active','inactive')),
  FOREIGN KEY (role_id) REFERENCES role(role_id)
);

CREATE TABLE staff (
  staff_id TEXT NOT NULL PRIMARY KEY,
  full_name TEXT NOT NULL,
  email TEXT NOT NULL UNIQUE,
  role_id TEXT NOT NULL,
  team_id TEXT NOT NULL,
  active_from TEXT NOT NULL,
  active_to TEXT,
  FOREIGN KEY (role_id) REFERENCES role(role_id),
  FOREIGN KEY (team_id) REFERENCES team(team_id)
);

CREATE TABLE team_category_authorization (
  team_id TEXT NOT NULL,
  category_id TEXT NOT NULL,
  access_level TEXT NOT NULL CHECK (access_level IN ('handle','escalation')),
  PRIMARY KEY (team_id, category_id),
  FOREIGN KEY (team_id) REFERENCES team(team_id),
  FOREIGN KEY (category_id) REFERENCES category(category_id)
);

CREATE TABLE routing_rule (
  rule_id TEXT NOT NULL PRIMARY KEY,
  category_id TEXT NOT NULL,
  team_id TEXT NOT NULL,
  rule_type TEXT NOT NULL CHECK (rule_type IN ('initial','escalation')),
  effective_from TEXT NOT NULL,
  effective_to TEXT,
  FOREIGN KEY (category_id) REFERENCES category(category_id),
  FOREIGN KEY (team_id) REFERENCES team(team_id)
);

CREATE TABLE ticket (
  ticket_id TEXT NOT NULL PRIMARY KEY,
  requester_id TEXT NOT NULL,
  term_id TEXT NOT NULL,
  category_id TEXT NOT NULL,
  priority TEXT NOT NULL CHECK (priority IN ('low','normal','high','urgent')),
  status TEXT NOT NULL CHECK (status IN ('new','triaged','assigned','in_progress','awaiting_requester','escalated','resolved','closed')),
  channel TEXT NOT NULL CHECK (channel IN ('portal','email','phone','walk_in')),
  subject TEXT NOT NULL,
  body TEXT NOT NULL,
  deadline_date TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  current_team_id TEXT NOT NULL,
  FOREIGN KEY (requester_id) REFERENCES requester(requester_id),
  FOREIGN KEY (term_id) REFERENCES term(term_id),
  FOREIGN KEY (category_id) REFERENCES category(category_id),
  FOREIGN KEY (current_team_id) REFERENCES team(team_id)
);

CREATE TABLE message (
  message_id TEXT NOT NULL PRIMARY KEY,
  ticket_id TEXT NOT NULL,
  seq_no INTEGER NOT NULL CHECK (seq_no BETWEEN 1.0 AND 999.0),
  sender_type TEXT NOT NULL CHECK (sender_type IN ('requester','staff','system')),
  requester_id TEXT,
  staff_id TEXT,
  message_type TEXT NOT NULL CHECK (message_type IN ('question','acknowledgement','clarification_request','clarification_reply','answer','followup','escalation_notice','internal_note','confirmation','reopen_request')),
  is_internal INTEGER NOT NULL CHECK (is_internal IN (0,1)),
  body TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE (ticket_id, seq_no),
  FOREIGN KEY (ticket_id) REFERENCES ticket(ticket_id),
  FOREIGN KEY (requester_id) REFERENCES requester(requester_id),
  FOREIGN KEY (staff_id) REFERENCES staff(staff_id)
);

CREATE TABLE message_article_link (
  message_id TEXT NOT NULL,
  article_id TEXT NOT NULL,
  cited_version_no INTEGER NOT NULL CHECK (cited_version_no BETWEEN 1.0 AND 9.0),
  relevance_score REAL NOT NULL CHECK (relevance_score BETWEEN 0.0 AND 1.0),
  citation_role TEXT NOT NULL CHECK (citation_role IN ('primary','supporting')),
  PRIMARY KEY (message_id, article_id),
  FOREIGN KEY (message_id) REFERENCES message(message_id),
  FOREIGN KEY (article_id) REFERENCES knowledge_article(article_id)
);

CREATE TABLE assignment (
  assignment_id TEXT NOT NULL PRIMARY KEY,
  ticket_id TEXT NOT NULL,
  team_id TEXT NOT NULL,
  staff_id TEXT NOT NULL,
  assignment_type TEXT NOT NULL CHECK (assignment_type IN ('initial','reassignment','escalation')),
  category_id_at_assignment TEXT NOT NULL,
  routing_rule_id TEXT,
  assigned_at TEXT NOT NULL,
  unassigned_at TEXT,
  assigned_by TEXT NOT NULL CHECK (assigned_by IN ('system','staff')),
  FOREIGN KEY (ticket_id) REFERENCES ticket(ticket_id),
  FOREIGN KEY (team_id) REFERENCES team(team_id),
  FOREIGN KEY (staff_id) REFERENCES staff(staff_id),
  FOREIGN KEY (category_id_at_assignment) REFERENCES category(category_id),
  FOREIGN KEY (routing_rule_id) REFERENCES routing_rule(rule_id)
);

CREATE TABLE sla (
  sla_id TEXT NOT NULL PRIMARY KEY,
  ticket_id TEXT NOT NULL UNIQUE,
  sla_policy_id TEXT NOT NULL,
  priority TEXT NOT NULL CHECK (priority IN ('low','normal','high','urgent')),
  clock_mode TEXT NOT NULL CHECK (clock_mode IN ('business','calendar')),
  clock_start TEXT NOT NULL,
  first_response_due TEXT NOT NULL,
  resolution_due TEXT NOT NULL,
  first_response_at TEXT,
  resolved_at TEXT,
  first_response_status TEXT NOT NULL CHECK (first_response_status IN ('met','breached','pending')),
  resolution_status TEXT NOT NULL CHECK (resolution_status IN ('met','breached','pending')),
  first_response_business_hours REAL CHECK (first_response_business_hours BETWEEN 0.0 AND 5000.0),
  resolution_business_hours REAL CHECK (resolution_business_hours BETWEEN 0.0 AND 5000.0),
  FOREIGN KEY (ticket_id) REFERENCES ticket(ticket_id),
  FOREIGN KEY (sla_policy_id) REFERENCES sla_policy(sla_policy_id)
);

CREATE TABLE ticket_event (
  event_id TEXT NOT NULL PRIMARY KEY,
  ticket_id TEXT NOT NULL,
  seq_no INTEGER NOT NULL CHECK (seq_no BETWEEN 1.0 AND 999.0),
  event_type TEXT NOT NULL CHECK (event_type IN ('created','triaged','assigned','started','awaiting_requester','requester_replied','escalated','recategorized','reassigned','resolved','closed','reopened')),
  from_status TEXT CHECK (from_status IN ('new','triaged','assigned','in_progress','awaiting_requester','escalated','resolved','closed')),
  to_status TEXT NOT NULL CHECK (to_status IN ('new','triaged','assigned','in_progress','awaiting_requester','escalated','resolved','closed')),
  event_at TEXT NOT NULL,
  actor_type TEXT NOT NULL CHECK (actor_type IN ('requester','staff','system')),
  actor_id TEXT,
  details TEXT,
  UNIQUE (ticket_id, seq_no),
  FOREIGN KEY (ticket_id) REFERENCES ticket(ticket_id)
);

CREATE TABLE resolution_feedback (
  feedback_id TEXT NOT NULL PRIMARY KEY,
  ticket_id TEXT NOT NULL UNIQUE,
  resolution_code TEXT NOT NULL CHECK (resolution_code IN ('answered_from_kb','resolved_by_staff','resolved_by_escalation','no_response_closed')),
  resolved_at TEXT NOT NULL,
  resolution_calendar_hours REAL NOT NULL CHECK (resolution_calendar_hours BETWEEN 0.0 AND 20000.0),
  resolution_business_hours REAL NOT NULL CHECK (resolution_business_hours BETWEEN 0.0 AND 5000.0),
  reopen_count INTEGER NOT NULL CHECK (reopen_count BETWEEN 0.0 AND 20.0),
  csat INTEGER CHECK (csat BETWEEN 1.0 AND 5.0),
  answer_helpful INTEGER CHECK (answer_helpful IN (0,1)),
  comment TEXT,
  feedback_at TEXT,
  FOREIGN KEY (ticket_id) REFERENCES ticket(ticket_id)
);

CREATE INDEX ix_ticket_status ON ticket(status);
CREATE INDEX ix_ticket_category ON ticket(category_id);
CREATE INDEX ix_ticket_requester ON ticket(requester_id);
CREATE INDEX ix_ticket_created ON ticket(created_at);
CREATE INDEX ix_message_ticket ON message(ticket_id);
CREATE INDEX ix_event_ticket ON ticket_event(ticket_id);
CREATE INDEX ix_assign_ticket ON assignment(ticket_id);
CREATE INDEX ix_article_topic ON knowledge_article(topic_key);
