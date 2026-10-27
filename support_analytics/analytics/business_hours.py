"""Business-time arithmetic: how many working minutes passed between two moments.

A reply at 9:10 on Sunday to a message sent at 17:50 on Thursday took 20 business minutes
(10 on Thursday + 10 on Sunday), not 63 hours. Holidays and the team's time zone are respected.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from support_analytics.core.config import WEEKDAYS, BusinessHours


def business_minutes(start: datetime, end: datetime, hours: BusinessHours) -> float:
    """Working minutes in [start, end). Both datetimes must be timezone-aware."""
    if end <= start:
        return 0.0
    tz = hours.tz
    s, e = start.astimezone(tz), end.astimezone(tz)
    total = 0.0
    day = s.date()
    while day <= e.date():
        window = hours.days.get(WEEKDAYS[day.weekday()])
        if window and day not in hours.holidays:
            open_min, close_min = window.minutes()
            midnight = datetime(day.year, day.month, day.day, tzinfo=tz)
            open_at = midnight + timedelta(minutes=open_min)
            close_at = midnight + timedelta(minutes=close_min)
            lo, hi = max(s, open_at), min(e, close_at)
            if hi > lo:
                total += (hi - lo).total_seconds() / 60
        day += timedelta(days=1)
    return round(total, 1)
