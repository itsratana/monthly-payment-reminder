from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from database.reminder_dispatch_repository import was_dispatched
from scheduler.reminder_scheduler import run_reminder_tick

TZ = ZoneInfo("Asia/Phnom_Penh")


class FakeBot:
    """Minimal aiogram.Bot stand-in for scheduler tests."""

    def __init__(self, fail_chat_ids=None):
        self.fail_chat_ids = fail_chat_ids or set()
        self.sent = []
        self._next_message_id = 100

    async def send_message(self, chat_id, text, parse_mode=None, reply_markup=None):
        if chat_id in self.fail_chat_ids:
            raise RuntimeError("Telegram send failed")

        self._next_message_id += 1
        self.sent.append({"chat_id": chat_id, "text": text})
        return SimpleNamespace(message_id=self._next_message_id)


def _two_payments(temp_db):
    from database.group_repository import add_group
    from database.member_repository import add_member
    from database.payment_repository import create_payment, add_payment_member

    add_group(-1, "Group One")
    add_member(1, -1, "a", "A")
    p1 = create_payment(chat_id=-1, name="P1", amount=1, currency="USD", due_day=19, reminder_time="09:00")
    add_payment_member(p1, 1)

    add_group(-2, "Group Two")
    add_member(2, -2, "b", "B")
    p2 = create_payment(chat_id=-2, name="P2", amount=2, currency="USD", due_day=19, reminder_time="09:00")
    add_payment_member(p2, 2)

    return p1, p2


@pytest.mark.asyncio
async def test_successful_send_records_dispatch_with_message_id(seeded_payment):
    bot = FakeBot()
    now = datetime(2026, 8, 19, 9, 0, tzinfo=TZ)

    import scheduler.reminder_scheduler as sched
    from unittest.mock import patch

    with patch("scheduler.reminder_scheduler.datetime") as mock_dt:
        mock_dt.now.return_value = now
        await run_reminder_tick(bot)

    assert len(bot.sent) == 1
    assert was_dispatched(seeded_payment["payment_id"], "2026-08-19") is True


@pytest.mark.asyncio
async def test_failed_send_does_not_record_dispatch(seeded_payment):
    bot = FakeBot(fail_chat_ids={seeded_payment["chat_id"]})
    now = datetime(2026, 8, 19, 9, 0, tzinfo=TZ)

    from unittest.mock import patch

    with patch("scheduler.reminder_scheduler.datetime") as mock_dt:
        mock_dt.now.return_value = now
        await run_reminder_tick(bot)

    assert bot.sent == []
    assert was_dispatched(seeded_payment["payment_id"], "2026-08-19") is False


@pytest.mark.asyncio
async def test_one_payment_failure_does_not_block_others(temp_db):
    p1, p2 = _two_payments(temp_db)
    bot = FakeBot(fail_chat_ids={-1})
    now = datetime(2026, 8, 19, 9, 0, tzinfo=TZ)

    from unittest.mock import patch

    with patch("scheduler.reminder_scheduler.datetime") as mock_dt:
        mock_dt.now.return_value = now
        await run_reminder_tick(bot)

    assert was_dispatched(p1, "2026-08-19") is False
    assert was_dispatched(p2, "2026-08-19") is True
    assert len(bot.sent) == 1
    assert bot.sent[0]["chat_id"] == -2


@pytest.mark.asyncio
async def test_second_tick_same_local_date_does_not_send_duplicate(seeded_payment):
    bot = FakeBot()
    now = datetime(2026, 8, 19, 9, 0, tzinfo=TZ)

    from unittest.mock import patch

    with patch("scheduler.reminder_scheduler.datetime") as mock_dt:
        mock_dt.now.return_value = now
        await run_reminder_tick(bot)
        await run_reminder_tick(bot)

    assert len(bot.sent) == 1
