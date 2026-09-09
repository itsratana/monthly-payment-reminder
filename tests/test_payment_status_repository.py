from database.payment_repository import remove_payment_member, add_payment_member
from database.payment_status_repository import (
    initialize_for_assigned_members,
    get_unpaid_members,
    get_status,
    mark_as_paid,
)
from database.reminder_dispatch_repository import was_dispatched, record_dispatch


def test_initialize_creates_one_status_row_per_assigned_member(seeded_payment):
    payment_id = seeded_payment["payment_id"]

    initialize_for_assigned_members(payment_id, 2026, 8)

    a = get_status(payment_id, seeded_payment["member_a"], 2026, 8)
    b = get_status(payment_id, seeded_payment["member_b"], 2026, 8)

    assert a is not None and a["paid"] == 0
    assert b is not None and b["paid"] == 0


def test_initialize_twice_creates_no_duplicates(seeded_payment):
    payment_id = seeded_payment["payment_id"]

    initialize_for_assigned_members(payment_id, 2026, 8)
    initialize_for_assigned_members(payment_id, 2026, 8)

    pending = get_unpaid_members(payment_id, 2026, 8)
    assert len(pending) == 2


def test_unpaid_query_returns_identity_fields(seeded_payment):
    payment_id = seeded_payment["payment_id"]
    initialize_for_assigned_members(payment_id, 2026, 8)

    pending = get_unpaid_members(payment_id, 2026, 8)
    by_id = {row["user_id"]: row for row in pending}

    assert by_id[seeded_payment["member_a"]]["username"] == "alice"
    assert by_id[seeded_payment["member_a"]]["full_name"] == "Alice A"
    assert by_id[seeded_payment["member_b"]]["username"] is None
    assert by_id[seeded_payment["member_b"]]["full_name"] == "Bob B"


def test_unpaid_query_excludes_paid_members(seeded_payment):
    payment_id = seeded_payment["payment_id"]
    initialize_for_assigned_members(payment_id, 2026, 8)

    mark_as_paid(payment_id, seeded_payment["member_a"], 2026, 8)

    pending = get_unpaid_members(payment_id, 2026, 8)
    assert [row["user_id"] for row in pending] == [seeded_payment["member_b"]]


def test_unpaid_query_excludes_unassigned_members(seeded_payment):
    payment_id = seeded_payment["payment_id"]
    initialize_for_assigned_members(payment_id, 2026, 8)

    remove_payment_member(payment_id, seeded_payment["member_a"])

    pending = get_unpaid_members(payment_id, 2026, 8)
    assert [row["user_id"] for row in pending] == [seeded_payment["member_b"]]


def test_newly_assigned_member_added_on_next_initialization(seeded_payment):
    payment_id = seeded_payment["payment_id"]
    initialize_for_assigned_members(payment_id, 2026, 8)

    from database.member_repository import add_member

    add_member(1003, seeded_payment["chat_id"], "carol", "Carol C")
    add_payment_member(payment_id, 1003)

    initialize_for_assigned_members(payment_id, 2026, 8)

    pending_ids = {row["user_id"] for row in get_unpaid_members(payment_id, 2026, 8)}
    assert 1003 in pending_ids


def test_mark_as_paid_updates_exactly_one_row(seeded_payment):
    payment_id = seeded_payment["payment_id"]
    initialize_for_assigned_members(payment_id, 2026, 8)

    changed = mark_as_paid(payment_id, seeded_payment["member_a"], 2026, 8)

    assert changed is True
    assert get_status(payment_id, seeded_payment["member_a"], 2026, 8)["paid"] == 1
    assert get_status(payment_id, seeded_payment["member_b"], 2026, 8)["paid"] == 0


def test_repeating_mark_as_paid_is_idempotent(seeded_payment):
    payment_id = seeded_payment["payment_id"]
    initialize_for_assigned_members(payment_id, 2026, 8)

    first = mark_as_paid(payment_id, seeded_payment["member_a"], 2026, 8)
    paid_at_first = get_status(payment_id, seeded_payment["member_a"], 2026, 8)["paid_at"]

    second = mark_as_paid(payment_id, seeded_payment["member_a"], 2026, 8)
    paid_at_second = get_status(payment_id, seeded_payment["member_a"], 2026, 8)["paid_at"]

    assert first is True
    assert second is False
    assert paid_at_first == paid_at_second


def test_status_for_august_does_not_change_september(seeded_payment):
    payment_id = seeded_payment["payment_id"]
    initialize_for_assigned_members(payment_id, 2026, 8)
    initialize_for_assigned_members(payment_id, 2026, 9)

    mark_as_paid(payment_id, seeded_payment["member_a"], 2026, 8)

    august = get_status(payment_id, seeded_payment["member_a"], 2026, 8)
    september = get_status(payment_id, seeded_payment["member_a"], 2026, 9)

    assert august["paid"] == 1
    assert september["paid"] == 0


def test_dispatch_uniqueness_prevents_two_records(seeded_payment):
    payment_id = seeded_payment["payment_id"]
    chat_id = seeded_payment["chat_id"]

    assert was_dispatched(payment_id, "2026-08-19") is False

    first = record_dispatch(payment_id, 2026, 8, "2026-08-19", chat_id, message_id=111)
    second = record_dispatch(payment_id, 2026, 8, "2026-08-19", chat_id, message_id=222)

    assert first is True
    assert second is False
    assert was_dispatched(payment_id, "2026-08-19") is True
