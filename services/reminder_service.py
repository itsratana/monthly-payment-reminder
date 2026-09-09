"""Reminder building and paid-callback orchestration (spec 10).

Framework-neutral: builds plain text/data, no aiogram objects, so it stays
testable without a running bot. Handlers/scheduler turn the results into
actual Telegram calls.
"""

import logging
from dataclasses import dataclass
from datetime import datetime

from database.member_repository import get_member
from database.reminder_dispatch_repository import was_dispatched
from services.payment_service import (
    get_all_active_payments,
    get_payment_detail,
    get_payment_group,
    is_assigned,
)
from services.payment_status_service import (
    initialize_monthly_status_for_payment,
    get_pending_members,
    get_member_status,
    set_member_paid,
)
from utils.dates import effective_due_day
from utils.telegram_format import escape_html, format_mention, format_amount

logger = logging.getLogger(__name__)

CALLBACK_PREFIX = "paid"


@dataclass(frozen=True)
class ReminderToSend:
    payment_id: int
    chat_id: int
    year: int
    month: int
    local_date: str
    text: str
    additional_texts: tuple[str, ...] = ()


@dataclass(frozen=True)
class PaidClickResult:
    status: str  # updated | already_paid | not_assigned | status_missing | payment_missing | invalid_period
    text: str | None = None
    has_pending: bool = False
    payment_id: int | None = None
    year: int | None = None
    month: int | None = None


# ---------------------------------------------------------------------------
# Callback data
# ---------------------------------------------------------------------------

def build_paid_callback_data(payment_id: int, year: int, month: int) -> str:
    return f"{CALLBACK_PREFIX}:{payment_id}:{year:04d}{month:02d}"


def parse_paid_callback_data(data: str):
    """Returns (payment_id, year, month) or None if malformed."""

    parts = data.split(":")
    if len(parts) != 3 or parts[0] != CALLBACK_PREFIX:
        return None

    payment_id_raw, period_raw = parts[1], parts[2]

    if not payment_id_raw.isdigit() or not period_raw.isdigit() or len(period_raw) != 6:
        return None

    payment_id = int(payment_id_raw)
    year = int(period_raw[:4])
    month = int(period_raw[4:6])

    if not (1 <= month <= 12 and 1 <= year <= 9999 and payment_id > 0):
        return None

    return payment_id, year, month


# ---------------------------------------------------------------------------
# Message building
# ---------------------------------------------------------------------------

def _pending_lines(pending_members) -> str:
    lines = [
        f"• {format_mention(m['user_id'], m['username'], m['full_name'])}"
        for m in pending_members
    ]
    return "\n".join(lines)


def _bounded_pending(members):
    lines=[];size=0
    for index,member in enumerate(members):
        line=_pending_lines([member])
        if size+len(line)>2800:
            lines.append(f"… {len(members)-index} more pending; see other reminder messages or ask your admin.")
            break
        lines.append(line);size+=len(line)+1
    return "\n".join(lines)


def build_reminder_messages(payment,pending):
    chunks=[];chunk=[];size=0
    for member in pending:
        length=len(_pending_lines([member]))+1
        if chunk and size+length>2700:
            chunks.append(chunk);chunk=[];size=0
        chunk.append(member);size+=length
    if chunk: chunks.append(chunk)
    return [build_reminder_text(payment,chunk) for chunk in chunks]


def build_reminder_text(payment, pending_members, just_paid_name: str | None = None) -> str:
    lines = [
        "📢 Monthly Payment Reminder",
        "",
        f"💳 {escape_html(payment['name'])}",
        f"💰 {format_amount(payment['amount'], payment['currency'])}",
    ]

    if just_paid_name is None:
        lines.append("📅 Monthly payment due")

    lines += [
        "",
        "⏳ Pending:",
        _bounded_pending(pending_members),
    ]

    if just_paid_name:
        lines += ["", f"✅ {escape_html(just_paid_name)} has paid."]

    return "\n".join(lines)


def build_all_paid_text(payment, year: int, month: int) -> str:
    period = datetime(year, month, 1).strftime("%B %Y")

    return (
        "✅ Monthly Payment Complete\n\n"
        f"💳 {escape_html(payment['name'])}\n"
        f"💰 {format_amount(payment['amount'], payment['currency'])}\n\n"
        f"Everyone assigned to this payment has paid for {period}."
    )


# ---------------------------------------------------------------------------
# Scheduled reminder selection (spec 10.1)
# ---------------------------------------------------------------------------

def get_eligible_reminders(now: datetime) -> list[ReminderToSend]:
    reminders = []
    errors = 0
    for payment in get_all_active_payments():
        try:
            reminder = _eligible_payment(payment, now)
            if reminder is not None:
                reminders.append(reminder)
        except Exception:
            errors += 1
            logger.exception('Reminder evaluation failed payment=%s', payment['id'])
    from services.health_service import write_health
    write_health(selection_failures=errors)
    return reminders


def _eligible_payment(payment, instant):
    from services.settings_service import group_now
    now = group_now(payment['chat_id'], instant)
    payment_id = payment['id']
    if not 1 <= payment['due_day'] <= 31:
        raise ValueError('Invalid stored due day')
    due_day = effective_due_day(now.year, now.month, payment['due_day'])
    if now.day < due_day:
        return None
    local_date = now.strftime('%Y-%m-%d')
    from utils.validators import parse_reminder_time
    reminder_time = parse_reminder_time(payment['reminder_time'])
    if reminder_time is None:
        raise ValueError('Invalid stored reminder time')
    if now.strftime('%H:%M') < reminder_time or was_dispatched(payment_id, local_date):
        return None
    initialize_monthly_status_for_payment(payment_id, now.year, now.month)
    pending = get_pending_members(payment_id, now.year, now.month)
    if not pending:
        return None
    texts = build_reminder_messages(payment, pending)
    return ReminderToSend(payment_id, payment['chat_id'], now.year, now.month,
                          local_date, texts[0], tuple(texts[1:]))


# ---------------------------------------------------------------------------
# Mark-paid orchestration (spec 10.2)
# ---------------------------------------------------------------------------

def process_paid_click(callback_data: str, actor_id: int) -> PaidClickResult:
    parsed = parse_paid_callback_data(callback_data)
    if parsed is None:
        return PaidClickResult(status="invalid_period")

    payment_id, year, month = parsed

    payment = get_payment_detail(payment_id)
    if payment is None:
        return PaidClickResult(status="payment_missing")

    if not payment["active"]:
        return PaidClickResult(status="payment_disabled")

    if not is_assigned(payment_id, actor_id):
        return PaidClickResult(status="not_assigned")

    status_row = get_member_status(payment_id, actor_id, year, month)
    if status_row is None:
        return PaidClickResult(status="status_missing")

    if bool(status_row["paid"]):
        # Already recorded: harmless no-op, no message edit needed - the
        # message already reflects this state from the first click.
        return PaidClickResult(
            status="already_paid",
            payment_id=payment_id,
            year=year,
            month=month,
        )

    from database.payment_status_repository import change_status
    change_status(payment_id, actor_id, year, month, True, actor_id)

    pending = get_pending_members(payment_id, year, month)

    if pending:
        actor_name = _actor_display_name(actor_id, payment_id)
        text = build_reminder_text(payment, pending, just_paid_name=actor_name)
    else:
        text = build_all_paid_text(payment, year, month)

    return PaidClickResult(
        status="updated",
        text=text,
        has_pending=bool(pending),
        payment_id=payment_id,
        year=year,
        month=month,
    )


def _actor_display_name(user_id: int, payment_id: int) -> str:
    """Best-effort plain-text name for the "X has paid" line."""

    chat_id = get_payment_group(payment_id)
    member = get_member(user_id, chat_id)

    if member is None:
        return str(user_id)

    return member["full_name"] or member["username"] or str(user_id)
