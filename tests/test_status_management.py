from datetime import datetime,timezone
import pytest
from database.connection import db_connection
from database.payment_status_repository import cycle_members,history_payments,initialize_for_assigned_members,get_status
from database.payment_repository import remove_payment_member,add_payment_member
from services.payment_status_service import correct_current_status
from services.settings_service import save_setting,group_settings,group_now
from database.schema import init_db

NOW=datetime(2026,8,19,4,tzinfo=timezone.utc)


def test_correction_audit_and_history(seeded_payment):
    p=seeded_payment;pid=p['payment_id'];uid=p['member_a']
    assert correct_current_status(pid,uid,2026,8,True,42,NOW)
    assert not correct_current_status(pid,uid,2026,8,True,42,NOW)
    assert correct_current_status(pid,uid,2026,8,False,42,NOW)
    with db_connection() as c:
        rows=c.execute('SELECT * FROM status_audit').fetchall()
        assert len(rows)==2 and rows[0]['actor_id']==42 and rows[1]['old_paid']==1
    with pytest.raises(ValueError): correct_current_status(pid,uid,2026,7,True,42,NOW)
    assert get_status(pid,uid,2026,7) is None


def test_assignment_history_and_readd_preserve_paid(seeded_payment):
    p=seeded_payment;pid=p['payment_id'];uid=p['member_a']
    correct_current_status(pid,uid,2026,8,True,42,NOW)
    remove_payment_member(pid,uid)
    assert len(cycle_members(pid,2026,8,current=True))==1
    assert len(cycle_members(pid,2026,8))==2
    assert history_payments(p['chat_id'],2026,8)[0]['total']==2
    add_payment_member(pid,uid);initialize_for_assigned_members(pid,2026,8)
    assert get_status(pid,uid,2026,8)['paid']==1


def test_settings_defaults_and_isolation(seeded_payment):
    chat=seeded_payment['chat_id']
    save_setting(chat,'timezone','America/New_York')
    save_setting(chat,'currency','eur')
    assert group_settings(chat)['currency']=='EUR'
    assert group_settings(-999)['currency']=='USD'
    assert group_now(chat,NOW).day==19
    from database.payment_repository import get_payment
    assert get_payment(seeded_payment['payment_id'])['currency']=='USD'
    for field,value in [('timezone','Mars/City'),('reminder_policy','weekly'),('reminder_time','25:00')]:
        with pytest.raises(ValueError): save_setting(chat,field,value)


def test_migration_repeat_preserves_rows_and_legacy_column(seeded_payment):
    p=seeded_payment
    initialize_for_assigned_members(p['payment_id'],2026,8)
    for _ in range(3): init_db()
    with db_connection() as c:
        assert 'last_reminded_at' in [r['name'] for r in c.execute('PRAGMA table_info(payment_status)')]
        assert c.execute('SELECT COUNT(*) FROM payment_status').fetchone()[0]==2
        assert c.execute('SELECT COUNT(*) FROM schema_migrations WHERE version=2').fetchone()[0]==1
        assert c.execute('PRAGMA foreign_keys').fetchone()[0]==0
