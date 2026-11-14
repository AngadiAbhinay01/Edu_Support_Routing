"""Business-hours arithmetic: Mon-Fri 09:00-17:00 excluding institute holidays.

All timestamps are naive campus-local datetimes.
"""
from datetime import datetime, timedelta, date, time

from .config import BUSINESS_START_HOUR, BUSINESS_END_HOUR, HOLIDAYS

_OPEN = time(BUSINESS_START_HOUR, 0)
_CLOSE = time(BUSINESS_END_HOUR, 0)
HOURS_PER_DAY = BUSINESS_END_HOUR - BUSINESS_START_HOUR


def is_business_day(d: date) -> bool:
    return d.weekday() < 5 and d not in HOLIDAYS


def _open_dt(d: date) -> datetime:
    return datetime.combine(d, _OPEN)


def _close_dt(d: date) -> datetime:
    return datetime.combine(d, _CLOSE)


def next_business_day(d: date) -> date:
    d = d + timedelta(days=1)
    while not is_business_day(d):
        d += timedelta(days=1)
    return d


def roll_forward(dt: datetime) -> datetime:
    """Return dt if it is inside business hours, otherwise the next opening instant."""
    d = dt.date()
    if is_business_day(d):
        if dt < _open_dt(d):
            return _open_dt(d)
        if dt < _close_dt(d):
            return dt
    return _open_dt(next_business_day(d))


def add_business_hours(start: datetime, hours: float) -> datetime:
    """Instant reached after consuming `hours` of business time starting from `start`."""
    if hours < 0:
        raise ValueError("hours must be >= 0")
    dt = roll_forward(start)
    remaining = timedelta(seconds=round(hours * 3600))
    while True:
        avail = _close_dt(dt.date()) - dt
        if remaining <= avail:
            return dt + remaining
        remaining -= avail
        dt = _open_dt(next_business_day(dt.date()))


def business_hours_between(a: datetime, b: datetime) -> float:
    """Business hours elapsed between a and b (0 if b <= a)."""
    if b <= a:
        return 0.0
    total = timedelta(0)
    d = a.date()
    while d <= b.date():
        if is_business_day(d):
            lo = max(a, _open_dt(d))
            hi = min(b, _close_dt(d))
            if hi > lo:
                total += hi - lo
        d += timedelta(days=1)
    return round(total.total_seconds() / 3600, 2)


def sla_due(start: datetime, hours: float, mode: str = "business") -> datetime:
    if mode == "business":
        return add_business_hours(start, hours)
    if mode == "calendar":
        return start + timedelta(hours=hours)
    raise ValueError("unknown clock mode: %s" % mode)
