from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.storage.base import StorageKey
from services.authorization import require_admin
from services.member_service import register_member
from database.member_repository import get_member
from database.settings_repository import selected_group,select_group
from handlers.payment_create import add_payment,accept,back
from handlers.navigation import cancel
from database.payment_repository import get_payments
from handlers.payment_status import on_paid_click
from database.payment_status_repository import initialize_for_assigned_members,get_status


def event(chat_id=7,actor=7,data=None):
    bot=SimpleNamespace(get_chat_member=AsyncMock(return_value=SimpleNamespace(status='administrator')))
    message=SimpleNamespace(chat=SimpleNamespace(id=chat_id,type='private'),answer=AsyncMock(),edit_text=AsyncMock())
    if data is None:
        message.bot=bot;message.from_user=SimpleNamespace(id=actor);return message
    return SimpleNamespace(data=data,bot=bot,from_user=SimpleNamespace(id=actor),message=message,answer=AsyncMock())


def state(): return FSMContext(MemoryStorage(),StorageKey(bot_id=1,chat_id=7,user_id=7))


@pytest.mark.asyncio
async def test_permissions_fail_closed(seeded_payment):
    e=event();e.bot.get_chat_member.return_value.status='member'
    with pytest.raises(PermissionError): await require_admin(e.bot,7,seeded_payment['chat_id'])
    e.bot.get_chat_member.side_effect=RuntimeError('unavailable')
    with pytest.raises(PermissionError): await require_admin(e.bot,7,seeded_payment['chat_id'])


@pytest.mark.asyncio
async def test_creation_back_cancel_no_partial_write(seeded_payment):
    s=state();chat=seeded_payment['chat_id'];e=event(data=f'add_payment:{chat}')
    await add_payment(e,s);await accept(e,s,'Internet');await accept(e,s,'25')
    e.data='create_back:2';await back(e,s)
    assert (await s.get_data())['values']['amount']==25
    await cancel(e,s)
    assert await s.get_state() is None and len(get_payments(chat))==1


@pytest.mark.asyncio
async def test_creation_defaults_and_permission_revocation(seeded_payment):
    s=state();chat=seeded_payment['chat_id'];e=event(data=f'add_payment:{chat}')
    await add_payment(e,s)
    assert (await s.get_data())['values']['currency']=='USD'
    for value in ['Internet','25','USD','12']: await accept(e,s,value)
    e.bot.get_chat_member.return_value.status='member'
    with pytest.raises(PermissionError): await accept(e,s,'09:00')
    assert len(get_payments(chat))==1
    e.bot.get_chat_member.return_value.status='administrator';await accept(e,s,'09:00')
    assert len(get_payments(chat))==2 and await s.get_state() is None


def test_join_updates_identity_and_is_group_scoped(temp_db):
    user=SimpleNamespace(id=1,username='old',full_name='Old')
    group=SimpleNamespace(id=-1,type='supergroup',title='Group')
    register_member(user,group);user.full_name='New';register_member(user,group)
    assert get_member(1,-1)['full_name']=='New'
    group.id=-2;register_member(user,group)
    assert get_member(1,-1) is not None and get_member(1,-2) is not None
    group.type='private'
    with pytest.raises(ValueError): register_member(user,group)


def test_selected_group_is_per_admin(temp_db):
    select_group(1,-1);select_group(2,-2);select_group(1,-3)
    assert selected_group(1)==-3 and selected_group(2)==-2


@pytest.mark.asyncio
async def test_live_handler_rejects_old_period_and_wrong_chat(seeded_payment):
    p=seeded_payment;initialize_for_assigned_members(p['payment_id'],2020,1)
    e=event(chat_id=p['chat_id'],actor=p['member_a'],data=f"paid:{p['payment_id']}:202001")
    await on_paid_click(e)
    assert get_status(p['payment_id'],p['member_a'],2020,1)['paid']==0
    assert e.answer.call_args.kwargs['show_alert']
