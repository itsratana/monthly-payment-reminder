import pytest

import config
from database.schema import init_db


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    """Point the whole app at a throwaway SQLite file for this test.

    Never touches the user's real reminder.db.
    """

    db_path = str(tmp_path / "test_reminder.db")
    monkeypatch.setattr(config, "DATABASE_PATH", db_path)
    init_db()
    return db_path


@pytest.fixture
def seeded_payment(temp_db):
    """One group with two members, both assigned to one payment."""

    from database.group_repository import add_group
    from database.member_repository import add_member
    from database.payment_repository import create_payment, add_payment_member

    chat_id = -1001
    add_group(chat_id, "Test Group")

    add_member(1001, chat_id, "alice", "Alice A")
    add_member(1002, chat_id, None, "Bob B")  # no username -> id-based mention

    payment_id = create_payment(
        chat_id=chat_id,
        name="TV",
        amount=5.0,
        currency="USD",
        due_day=19,
        reminder_time="09:00",
    )

    add_payment_member(payment_id, 1001)
    add_payment_member(payment_id, 1002)

    return {
        "chat_id": chat_id,
        "payment_id": payment_id,
        "member_a": 1001,
        "member_b": 1002,
    }
