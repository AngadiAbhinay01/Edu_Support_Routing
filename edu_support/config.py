"""Shared configuration constants (single source of truth for generator, backend and tests)."""
from datetime import date, datetime, timedelta

DEFAULT_SEED = 20261022
YEAR = 2026

# Dataset snapshot ("as-of") time. Open tickets / SLA statuses are evaluated against this instant.
AS_OF = datetime(2026, 11, 1, 0, 0, 0)

# Default scale required by the problem statement
DEFAULT_TICKETS = 5000
DEFAULT_ARTICLES = 200
DEFAULT_MESSAGES = 20000

# ---- business calendar -------------------------------------------------------------------------
BUSINESS_START_HOUR = 9     # 09:00 inclusive
BUSINESS_END_HOUR = 17      # 17:00 exclusive  (8 business hours / day, Mon-Fri)
HOLIDAYS = {
    date(2026, 1, 1): "New Year's Day (institute holiday)",
    date(2026, 1, 26): "Republic Day (institute holiday)",
    date(2026, 5, 1): "Labour Day (institute holiday)",
    date(2026, 8, 15): "Independence Day (institute holiday)",
    date(2026, 10, 2): "Gandhi Jayanti (institute holiday)",
    date(2026, 12, 25): "Year-end holiday (institute holiday)",
    date(2027, 1, 1): "New Year's Day (institute holiday)",
    date(2027, 1, 26): "Republic Day (institute holiday)",
}

# ---- routing / classification thresholds ---------------------------------------------------------
MIN_TOP_SCORE = 2       # a domain needs >= 2 distinct keyword hits, otherwise "low signal"
MIN_MARGIN = 2          # winner must beat the runner-up by >= 2 hits, otherwise "domain conflict"
MIN_COVERAGE = 0.67     # share of a KB topic title's tokens found in the ticket text
MIN_MATCHED_TOKENS = 2

# ---- escalation rules ----------------------------------------------------------------------------
ESC_GRACE = timedelta(minutes=10)      # tolerance between trigger instant and the escalation event
CLARIFICATION_WAIT_BH = 16             # business hours to wait for a clarification reply (2 days)
FOLLOWUPS_FOR_ESCALATION = 2           # E5: requester follow-ups before auto-escalation
REOPEN_WINDOW_DAYS = 14                # closed tickets can be reopened by the requester for 14 days
AUTO_CLOSE_DAYS = 7                    # resolved -> closed after 7 calendar days

PRIORITIES = ["low", "normal", "high", "urgent"]
STATUSES = ["new", "triaged", "assigned", "in_progress", "awaiting_requester",
            "escalated", "resolved", "closed"]

# Allowed lifecycle transitions (from_status -> set(to_status)); validated by generator, backend and validator
TRANSITIONS = {
    None: {"new"},
    "new": {"triaged"},
    "triaged": {"assigned"},
    "assigned": {"in_progress", "escalated"},
    "in_progress": {"awaiting_requester", "escalated", "resolved", "closed"},
    "awaiting_requester": {"in_progress", "escalated", "resolved", "closed"},
    "escalated": {"in_progress"},
    "resolved": {"closed", "in_progress"},
    "closed": {"in_progress"},
}

ESCALATION_REASONS = {
    "E1_AMBIGUOUS_UNRESOLVED": "Request still ambiguous after clarification (or clarification unanswered)",
    "E2_NO_POLICY_SOURCE": "No applicable current knowledge article found",
    "E3_HUMAN_DECISION_REQUIRED": "Category requires a human decision (appeal / override / accommodation / security)",
    "E4_URGENT_SLA_BREACH": "Urgent ticket missed its first-response SLA",
    "E5_REPEATED_FOLLOWUPS": "Requester followed up repeatedly without resolution",
}

ISSUE_TYPES = [
    "EXPIRED_POLICY_CITATION",
    "UNAUTHORIZED_ROUTING",
    "UNSUPPORTED_CLAIM",
    "SLA_IGNORES_BUSINESS_HOURS",
    "ESCALATION_NOT_TRIGGERED",
]

FMT_DT = "%Y-%m-%d %H:%M:%S"
FMT_D = "%Y-%m-%d"


def fmt_dt(dt):
    return dt.strftime(FMT_DT) if dt else ""


def fmt_d(d):
    return d.strftime(FMT_D) if d else ""


def parse_dt(s):
    return datetime.strptime(s, FMT_DT) if s else None


def parse_d(s):
    return datetime.strptime(s, FMT_D).date() if s else None
