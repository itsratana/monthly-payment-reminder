"""Pure input validators used by the payment creation wizard (spec 12)."""

import re
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

_REMINDER_TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


def parse_amount(text: str) -> float | None:
    """Return a positive float amount, or None if invalid."""

    try:
        value = Decimal(text)
        if not value.is_finite() or not 0 < value <= Decimal('999999999.99'):
            return None
        if value != value.quantize(Decimal('0.01')):
            return None
        amount = float(value)
    except (TypeError, ValueError, InvalidOperation):
        return None

    if amount <= 0:
        return None

    return amount


def parse_currency(text: str) -> str | None:
    currency = (text or "").strip().upper()
    return currency if re.fullmatch(r'[A-Z]{3}', currency) else None


def parse_due_day(text: str) -> int | None:
    try:
        due_day = int(text)
    except (TypeError, ValueError):
        return None

    if due_day < 1 or due_day > 31:
        return None

    return due_day


def parse_reminder_time(text: str) -> str | None:
    """Return a normalized HH:MM 24-hour string, or None if invalid.

    Rejects values like "09" that the app expects as "09:00".
    """

    candidate = (text or "").strip()

    if _REMINDER_TIME_RE.match(candidate):
        return candidate

    return None


def parse_name(text):
    value = (text or '').strip()
    return value if 1 <= len(value) <= 100 and not value.startswith('/') else None


def parse_timezone(text):
    try:
        value = (text or '').strip()
        ZoneInfo(value)
        return value
    except (ValueError, ZoneInfoNotFoundError):
        return None


VALIDATORS = {'name': parse_name, 'amount': parse_amount,
              'currency': parse_currency, 'due_day': parse_due_day,
              'reminder_time': parse_reminder_time, 'timezone': parse_timezone}
