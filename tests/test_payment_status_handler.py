"""Tests for the "I've Paid" callback orchestration (spec 4.4, 10.2).

process_paid_click() is the framework-neutral core the handler calls;
testing it directly covers the callback rules without needing a live
aiogram CallbackQuery/Bot.
"""

from database.payment_status_repository import initialize_for_assigned_members, get_status
from services.reminder_service import (
    process_paid_click,
    build_paid_callback_data,
    parse_paid_callback_data,
)


def _data(payment_id, year=2026, month=8):
    return build_paid_callback_data(payment_id, year, month)


def test_assigned_unpaid_actor_can_mark_self_paid(seeded_payment):
    payment_id = seeded_payment["payment_id"]
    initialize_for_assigned_members(payment_id, 2026, 8)

    result = process_paid_click(_data(payment_id), seeded_payment["member_a"])

    assert result.status == "updated"
    assert get_status(payment_id, seeded_payment["member_a"], 2026, 8)["paid"] == 1


def test_unassigned_actor_cannot_update_status(seeded_payment):
    payment_id = seeded_payment["payment_id"]
    initialize_for_assigned_members(payment_id, 2026, 8)

    result = process_paid_click(_data(payment_id), actor_id=999999)

    assert result.status == "not_assigned"
    # No status row should have been created/changed for the stranger.
    assert get_status(payment_id, 999999, 2026, 8) is None


def test_one_actor_cannot_mark_another_actor_paid(seeded_payment):
    """The actor is always callback.from_user.id; there is no user_id field
    in the callback payload an attacker could substitute (spec 4.4)."""

    payment_id = seeded_payment["payment_id"]
    initialize_for_assigned_members(payment_id, 2026, 8)

    process_paid_click(_data(payment_id), seeded_payment["member_a"])

    assert get_status(payment_id, seeded_payment["member_a"], 2026, 8)["paid"] == 1
    assert get_status(payment_id, seeded_payment["member_b"], 2026, 8)["paid"] == 0


def test_old_callback_updates_only_its_encoded_period(seeded_payment):
    payment_id = seeded_payment["payment_id"]
    initialize_for_assigned_members(payment_id, 2026, 7)
    initialize_for_assigned_members(payment_id, 2026, 8)

    result = process_paid_click(_data(payment_id, 2026, 7), seeded_payment["member_a"])

    assert result.status == "updated"
    assert get_status(payment_id, seeded_payment["member_a"], 2026, 7)["paid"] == 1
    assert get_status(payment_id, seeded_payment["member_a"], 2026, 8)["paid"] == 0


def test_malformed_callbacks_are_rejected_cleanly(seeded_payment):
    payment_id = seeded_payment["payment_id"]

    assert parse_paid_callback_data("paid:abc:202608") is None
    assert parse_paid_callback_data("paid:1:2026") is None
    assert parse_paid_callback_data("paid:1:202613") is None
    assert parse_paid_callback_data("notpaid:1:202608") is None
    assert parse_paid_callback_data("paid:1") is None

    result = process_paid_click("paid:1:2026", seeded_payment["member_a"])
    assert result.status == "invalid_period"


def test_double_click_is_already_paid_and_does_not_change_paid_at(seeded_payment):
    payment_id = seeded_payment["payment_id"]
    initialize_for_assigned_members(payment_id, 2026, 8)

    process_paid_click(_data(payment_id), seeded_payment["member_a"])
    paid_at_first = get_status(payment_id, seeded_payment["member_a"], 2026, 8)["paid_at"]

    result = process_paid_click(_data(payment_id), seeded_payment["member_a"])
    paid_at_second = get_status(payment_id, seeded_payment["member_a"], 2026, 8)["paid_at"]

    assert result.status == "already_paid"
    assert paid_at_first == paid_at_second


def test_remaining_member_message_rebuilt_correctly(seeded_payment):
    payment_id = seeded_payment["payment_id"]
    initialize_for_assigned_members(payment_id, 2026, 8)

    result = process_paid_click(_data(payment_id), seeded_payment["member_a"])

    assert result.status == "updated"
    assert result.has_pending is True
    assert "✅ Alice A has paid." in result.text

    bullet_lines = [line for line in result.text.splitlines() if line.startswith("•")]
    assert bullet_lines == ['• <a href="tg://user?id=1002">Bob B</a>']


def test_all_paid_message_has_no_pending_flag(seeded_payment):
    payment_id = seeded_payment["payment_id"]
    initialize_for_assigned_members(payment_id, 2026, 8)

    process_paid_click(_data(payment_id), seeded_payment["member_a"])
    result = process_paid_click(_data(payment_id), seeded_payment["member_b"])

    assert result.status == "updated"
    assert result.has_pending is False
    assert "Monthly Payment Complete" in result.text


def test_status_missing_when_never_initialized(seeded_payment):
    payment_id = seeded_payment["payment_id"]
    # No initialize_for_assigned_members call: no status row exists yet.

    result = process_paid_click(_data(payment_id), seeded_payment["member_a"])

    assert result.status == "status_missing"


def test_payment_missing_for_unknown_payment_id(seeded_payment):
    result = process_paid_click(_data(999999), seeded_payment["member_a"])
    assert result.status == "payment_missing"
