import pytest
from database.payment_repository import get_payment
from database.payment_status_repository import initialize_for_assigned_members, mark_as_paid, get_status
from database.reminder_dispatch_repository import record_dispatch, was_dispatched
from services.payment_service import edit_payment, set_active, delete_payment
from utils.validators import parse_amount, parse_currency


def test_edit_preserves_history_and_dispatch(seeded_payment):
    p=seeded_payment; pid=p['payment_id']
    initialize_for_assigned_members(pid,2026,8); mark_as_paid(pid,p['member_a'],2026,8)
    record_dispatch(pid,2026,8,'2026-08-19',p['chat_id'],123)
    assert edit_payment(pid,p['chat_id'],'amount','18.50')
    assert get_payment(pid)['amount']==18.5
    assert get_status(pid,p['member_a'],2026,8)['paid']==1
    assert was_dispatched(pid,'2026-08-19')
    assert not edit_payment(pid,-999,'name','Wrong group')
    assert get_payment(pid)['name']=='TV'


@pytest.mark.parametrize('value',['NaN','inf','-1','0','1.001','1e1000'])
def test_invalid_amount(value):
    assert parse_amount(value) is None


def test_invalid_edit_no_write(seeded_payment):
    with pytest.raises(ValueError): edit_payment(seeded_payment['payment_id'],seeded_payment['chat_id'],'currency','dollar')
    assert parse_currency(' usd ')=='USD'


def test_disable_reactivate_and_safe_delete(seeded_payment):
    p=seeded_payment; pid=p['payment_id']
    set_active(pid,p['chat_id'],False); assert get_payment(pid)['active']==0
    set_active(pid,p['chat_id'],True); assert get_payment(pid)['active']==1
    assert delete_payment(pid,-999)=='missing'
    assert delete_payment(pid,p['chat_id'])=='deleted'
    assert delete_payment(pid,p['chat_id'])=='missing'


def test_delete_history_refused(seeded_payment):
    p=seeded_payment
    initialize_for_assigned_members(p['payment_id'],2026,8)
    assert delete_payment(p['payment_id'],p['chat_id'])=='history'
    assert get_payment(p['payment_id']) is not None
