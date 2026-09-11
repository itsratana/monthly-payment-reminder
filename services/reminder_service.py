"""Reminder building and paid-callback orchestration.

Framework-neutral: builds plain text/data, no aiogram objects.
Handlers and scheduler turn the results into Telegram calls.
"""

import logging
from dataclasses import dataclass
from datetime import datetime

from database.member_repository import get_member
from database.reminder_dispatch_repository import was_slot_dispatched

from services.payment_service import (
    get_all_active_payments,
    get_payment_detail,
    get_payment_group,
    get_reminder_times,
    is_assigned,
)

from services.payment_status_service import (
    initialize_monthly_status_for_payment,
    get_pending_members,
    get_member_status,
)

from utils.dates import effective_due_day
from utils.telegram_format import (
    escape_html,
    format_mention,
    format_amount,
)

logger = logging.getLogger(__name__)

CALLBACK_PREFIX = "paid"


# ---------------------------------------------------------------------------
# Data objects
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ReminderToSend:
    payment_id: int
    chat_id: int
    year: int
    month: int
    local_date: str

    # Exact automatic reminder slot, for example:
    # 09:00
    # 18:00
    reminder_time: str

    text: str
    additional_texts: tuple[str, ...] = ()


@dataclass(frozen=True)
class PaidClickResult:
    status: str
    text: str | None = None
    has_pending: bool = False
    payment_id: int | None = None
    year: int | None = None
    month: int | None = None


# ---------------------------------------------------------------------------
# Callback data
# ---------------------------------------------------------------------------

def build_paid_callback_data(
    payment_id: int,
    year: int,
    month: int
) -> str:
    return (
        f"{CALLBACK_PREFIX}:"
        f"{payment_id}:"
        f"{year:04d}{month:02d}"
    )


def parse_paid_callback_data(data: str):
    """
    Returns:

        (payment_id, year, month)

    or None if malformed.
    """

    parts = data.split(":")

    if len(parts) != 3:
        return None

    if parts[0] != CALLBACK_PREFIX:
        return None

    payment_id_raw = parts[1]
    period_raw = parts[2]

    if not payment_id_raw.isdigit():
        return None

    if not period_raw.isdigit():
        return None

    if len(period_raw) != 6:
        return None

    payment_id = int(payment_id_raw)

    year = int(period_raw[:4])
    month = int(period_raw[4:6])

    if payment_id <= 0:
        return None

    if not 1 <= year <= 9999:
        return None

    if not 1 <= month <= 12:
        return None

    return payment_id, year, month


# ---------------------------------------------------------------------------
# Message building
# ---------------------------------------------------------------------------

def _pending_lines(pending_members) -> str:
    lines = [
        (
            f"• "
            f"{format_mention(
                member['user_id'],
                member['username'],
                member['full_name']
            )}"
        )
        for member in pending_members
    ]

    return "\n".join(lines)


def _bounded_pending(members):
    lines = []
    size = 0

    for index, member in enumerate(members):
        line = _pending_lines([member])

        if size + len(line) > 2800:
            remaining = len(members) - index

            lines.append(
                f"… {remaining} more pending; "
                f"see other reminder messages or ask your admin."
            )

            break

        lines.append(line)

        size += len(line) + 1

    return "\n".join(lines)


def payment_period_text(
    year: int,
    month: int
) -> str:
    return datetime(
        year,
        month,
        1
    ).strftime("%B %Y")


def build_reminder_messages(
    payment,
    pending,
    year: int,
    month: int,
):
    chunks = []

    chunk = []
    size = 0

    for member in pending:
        length = len(
            _pending_lines([member])
        ) + 1

        if chunk and size + length > 2700:
            chunks.append(chunk)

            chunk = []
            size = 0

        chunk.append(member)

        size += length

    if chunk:
        chunks.append(chunk)

    return [
        build_reminder_text(
            payment,
            members,
            year,
            month,
        )
        for members in chunks
    ]


def build_reminder_text(
    payment,
    pending_members,
    year: int,
    month: int,
    just_paid_name: str | None = None,
) -> str:
    period = payment_period_text(
        year,
        month
    )

    lines = [
        "📢 Monthly Payment Reminder",
        "",
        f"💳 {escape_html(payment['name'])}",
        (
            f"💰 "
            f"{format_amount(
                payment['amount'],
                payment['currency']
            )}"
        ),
        f"📅 Payment for: {period}",
        "",
        "⏳ Pending:",
        _bounded_pending(
            pending_members
        ),
    ]

    if just_paid_name:
        lines += [
            "",
            (
                f"✅ "
                f"{escape_html(just_paid_name)} "
                f"has paid."
            ),
        ]

    return "\n".join(lines)


def build_all_paid_text(
    payment,
    year: int,
    month: int
) -> str:
    period = payment_period_text(
        year,
        month
    )

    return (
        "✅ Monthly Payment Complete\n\n"
        f"💳 {escape_html(payment['name'])}\n"
        f"💰 "
        f"{format_amount(
            payment['amount'],
            payment['currency']
        )}\n"
        f"📅 Payment for: {period}\n\n"
        f"Everyone assigned to this payment "
        f"has paid for {period}."
    )


# ---------------------------------------------------------------------------
# Automatic reminder selection
# ---------------------------------------------------------------------------

def get_eligible_reminders(
    now: datetime
) -> list[ReminderToSend]:
    reminders = []

    errors = 0

    for payment in get_all_active_payments():
        try:
            reminder = _eligible_payment(
                payment,
                now
            )

            if reminder is not None:
                reminders.append(
                    reminder
                )

        except Exception:
            errors += 1

            logger.exception(
                "Reminder evaluation failed payment=%s",
                payment["id"],
            )

    from services.health_service import write_health

    write_health(
        selection_failures=errors
    )

    return reminders


def _eligible_payment(
    payment,
    instant
):
    """
    Return the latest automatic reminder slot that should run
    for this payment right now.

    Example schedule:

        09:00
        13:00
        18:00

    At 09:05:
        evaluates 09:00

    At 13:05:
        evaluates 13:00

    At 18:05:
        evaluates 18:00

    If the bot was offline until 18:05, it does NOT send the
    missed 09:00 and 13:00 reminders all at once. It only
    evaluates the latest due slot: 18:00.
    """

    from services.settings_service import group_now
    from utils.validators import parse_reminder_time

    now = group_now(
        payment["chat_id"],
        instant
    )

    payment_id = payment["id"]

    # ---------------------------------------------------------
    # Validate due day
    # ---------------------------------------------------------

    if not 1 <= payment["due_day"] <= 31:
        raise ValueError(
            "Invalid stored due day"
        )

    due_day = effective_due_day(
        now.year,
        now.month,
        payment["due_day"]
    )

    # Monthly cycle has not started yet.
    if now.day < due_day:
        return None

    # ---------------------------------------------------------
    # Load configured reminder times
    # ---------------------------------------------------------

    reminder_times = get_reminder_times(
        payment_id
    )

    # Backwards-compatible fallback in case an old database
    # has not populated the new table yet.
    if not reminder_times:
        reminder_times = [
            payment["reminder_time"]
        ]

    current_time = now.strftime(
        "%H:%M"
    )

    eligible_times = []

    for configured_time in reminder_times:
        parsed_time = parse_reminder_time(
            configured_time
        )

        if parsed_time is None:
            raise ValueError(
                "Invalid stored reminder time"
            )

        if current_time >= parsed_time:
            eligible_times.append(
                parsed_time
            )

    # No reminder time has arrived yet today.
    if not eligible_times:
        return None

    # Only consider the latest reminder slot whose time has
    # already arrived.
    #
    # This prevents three reminders being sent together after
    # server downtime.
    reminder_time = max(
        eligible_times
    )

    local_date = now.strftime(
        "%Y-%m-%d"
    )

    # This exact slot already sent today.
    if was_slot_dispatched(
        payment_id,
        local_date,
        reminder_time,
    ):
        return None

    # ---------------------------------------------------------
    # Monthly payment statuses
    # ---------------------------------------------------------

    initialize_monthly_status_for_payment(
        payment_id,
        now.year,
        now.month
    )

    pending = get_pending_members(
        payment_id,
        now.year,
        now.month
    )

    if not pending:
        return None

    # ---------------------------------------------------------
    # Build Telegram reminder
    # ---------------------------------------------------------

    texts = build_reminder_messages(
        payment,
        pending,
        now.year,
        now.month,
    )

    if not texts:
        return None

    return ReminderToSend(
        payment_id=payment_id,
        chat_id=payment["chat_id"],
        year=now.year,
        month=now.month,
        local_date=local_date,
        reminder_time=reminder_time,
        text=texts[0],
        additional_texts=tuple(
            texts[1:]
        ),
    )


# ---------------------------------------------------------------------------
# Mark-paid orchestration
# ---------------------------------------------------------------------------

def process_paid_click(
    callback_data: str,
    actor_id: int
) -> PaidClickResult:
    parsed = parse_paid_callback_data(
        callback_data
    )

    if parsed is None:
        return PaidClickResult(
            status="invalid_period"
        )

    payment_id, year, month = parsed

    payment = get_payment_detail(
        payment_id
    )

    if payment is None:
        return PaidClickResult(
            status="payment_missing"
        )

    if not payment["active"]:
        return PaidClickResult(
            status="payment_disabled"
        )

    if not is_assigned(
        payment_id,
        actor_id
    ):
        return PaidClickResult(
            status="not_assigned"
        )

    status_row = get_member_status(
        payment_id,
        actor_id,
        year,
        month
    )

    if status_row is None:
        return PaidClickResult(
            status="status_missing"
        )

    if bool(status_row["paid"]):
        return PaidClickResult(
            status="already_paid",
            payment_id=payment_id,
            year=year,
            month=month,
        )

    from database.payment_status_repository import change_status

    change_status(
        payment_id,
        actor_id,
        year,
        month,
        True,
        actor_id,
    )

    pending = get_pending_members(
        payment_id,
        year,
        month
    )

    if pending:
        actor_name = _actor_display_name(
            actor_id,
            payment_id
        )

        text = build_reminder_text(
            payment,
            pending,
            year,
            month,
            just_paid_name=actor_name,
        )

    else:
        text = build_all_paid_text(
            payment,
            year,
            month
        )

    return PaidClickResult(
        status="updated",
        text=text,
        has_pending=bool(pending),
        payment_id=payment_id,
        year=year,
        month=month,
    )


def _actor_display_name(
    user_id: int,
    payment_id: int
) -> str:
    """
    Best-effort plain-text name for:

        X has paid.
    """

    chat_id = get_payment_group(
        payment_id
    )

    member = get_member(
        user_id,
        chat_id
    )

    if member is None:
        return str(user_id)

    return (
        member["full_name"]
        or member["username"]
        or str(user_id)
    )