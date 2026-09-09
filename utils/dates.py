"""Date helpers shared by the reminder service and scheduler.

Kept dependency-free and pure so the due-day edge cases (spec 4.2) have one
tested home instead of being reimplemented ad hoc.
"""

import calendar


def effective_due_day(year: int, month: int, due_day: int) -> int:
    """Clamp a configured due_day (1-31) to the real length of the month.

    Example: due_day=31 in February returns 28 (or 29 in a leap year).
    """

    last_day_of_month = calendar.monthrange(year, month)[1]
    return min(due_day, last_day_of_month)
