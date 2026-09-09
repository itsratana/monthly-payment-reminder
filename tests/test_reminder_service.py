from datetime import datetime
from zoneinfo import ZoneInfo

from database.payment_status_repository import mark_as_paid
from services.reminder_service import (
    get_eligible_reminders,
    build_reminder_text,
    build_all_paid_text,
)
from utils.dates import effective_due_day
from utils.telegram_format import escape_html, format_mention, format_amount

TZ = ZoneInfo("Asia/Phnom_Penh")


def _now(year, month, day, hour, minute):
    return datetime(year, month, day, hour, minute, tzinfo=TZ)


def test_not_eligible_before_due_day(seeded_payment):
    now = _now(2026, 8, 18, 9, 0)  # due_day is 19
    assert get_eligible_reminders(now) == []


def test_eligible_on_due_day_at_or_after_reminder_time(seeded_payment):
    now = _now(2026, 8, 19, 9, 0)  # reminder_time is 09:00
    reminders = get_eligible_reminders(now)

    assert len(reminders) == 1
    assert reminders[0].payment_id == seeded_payment["payment_id"]
    assert reminders[0].chat_id == seeded_payment["chat_id"]


def test_not_eligible_before_reminder_time(seeded_payment):
    now = _now(2026, 8, 19, 8, 59)
    assert get_eligible_reminders(now) == []


def test_daily_policy_remains_eligible_after_due_day_while_unpaid(seeded_payment):
    day19 = _now(2026, 8, 19, 9, 0)
    assert len(get_eligible_reminders(day19)) == 1

    # Simulate day 19 already dispatched; day 20 is a new local_date, so the
    # payment is still eligible while a member remains unpaid.
    from database.reminder_dispatch_repository import record_dispatch
    record_dispatch(
        seeded_payment["payment_id"], 2026, 8, "2026-08-19",
        seeded_payment["chat_id"], message_id=1,
    )
    assert get_eligible_reminders(day19) == []  # same day: already dispatched

    day20 = _now(2026, 8, 20, 9, 0)
    assert len(get_eligible_reminders(day20)) == 1


def test_completed_payment_not_eligible_again_that_month(seeded_payment):
    now = _now(2026, 8, 19, 9, 0)

    # Status rows must exist before mark_as_paid can affect anything;
    # initialize once up front (get_eligible_reminders would otherwise do
    # this lazily on its own first pass).
    from services.payment_status_service import initialize_monthly_status_for_payment
    initialize_monthly_status_for_payment(seeded_payment["payment_id"], 2026, 8)
    mark_as_paid(seeded_payment["payment_id"], seeded_payment["member_a"], 2026, 8)
    mark_as_paid(seeded_payment["payment_id"], seeded_payment["member_b"], 2026, 8)

    assert get_eligible_reminders(now) == []


def test_due_day_31_clamped_in_short_months():
    assert effective_due_day(2026, 2, 31) == 28  # Feb 2026, not a leap year
    assert effective_due_day(2024, 2, 31) == 29  # 2024 is a leap year
    assert effective_due_day(2026, 4, 31) == 30  # April has 30 days
    assert effective_due_day(2026, 1, 31) == 31  # January has 31 days


def test_due_day_31_payment_fires_on_last_day_of_february(temp_db):
    from database.group_repository import add_group
    from database.member_repository import add_member
    from database.payment_repository import create_payment, add_payment_member

    chat_id = -2002
    add_group(chat_id, "Feb Group")
    add_member(2001, chat_id, "dana", "Dana D")

    payment_id = create_payment(
        chat_id=chat_id, name="Rent", amount=100, currency="USD",
        due_day=31, reminder_time="09:00",
    )
    add_payment_member(payment_id, 2001)

    # Feb 27, 2026 -> not yet eligible (effective due day is 28)
    assert get_eligible_reminders(_now(2026, 2, 27, 9, 0)) == []
    # Feb 28, 2026 -> eligible (last day of the month)
    assert len(get_eligible_reminders(_now(2026, 2, 28, 9, 0))) == 1


def test_no_assigned_members_produces_no_reminder(temp_db):
    from database.group_repository import add_group
    from database.payment_repository import create_payment

    chat_id = -3003
    add_group(chat_id, "Empty Group")

    create_payment(
        chat_id=chat_id, name="Gym", amount=20, currency="USD",
        due_day=19, reminder_time="09:00",
    )

    assert get_eligible_reminders(_now(2026, 8, 19, 9, 0)) == []


def test_username_mention_is_at_username():
    assert format_mention(1001, "alice", "Alice A") == "@alice"


def test_id_based_mention_when_no_username():
    mention = format_mention(1002, None, "Bob B")
    assert mention == '<a href="tg://user?id=1002">Bob B</a>'


def test_id_based_mention_falls_back_to_id_when_no_name():
    mention = format_mention(1002, None, None)
    assert mention == '<a href="tg://user?id=1002">1002</a>'


def test_html_special_characters_are_escaped():
    assert escape_html("<script>alert(1)</script>") == (
        "&lt;script&gt;alert(1)&lt;/script&gt;"
    )
    assert escape_html("Tom & Jerry") == "Tom &amp; Jerry"


def test_html_escaped_in_reminder_text():
    payment = {"name": "<b>TV</b>", "amount": 5.0, "currency": "USD"}
    pending = [{"user_id": 1, "username": None, "full_name": "<i>Bob</i>"}]

    text = build_reminder_text(payment, pending)

    assert "<b>TV</b>" not in text
    assert "&lt;b&gt;TV&lt;/b&gt;" in text
    assert "&lt;i&gt;Bob&lt;/i&gt;" in text


def test_amount_and_currency_formatting_is_stable():
    assert format_amount(5, "USD") == "5.00 USD"
    assert format_amount(5.5, "usd") == "5.50 usd"
    assert format_amount(1234.567, "USD") == "1234.57 USD"


def test_all_paid_text_mentions_period():
    payment = {"name": "TV", "amount": 5.0, "currency": "USD"}
    text = build_all_paid_text(payment, 2026, 8)
    assert "August 2026" in text
    assert "TV" in text
