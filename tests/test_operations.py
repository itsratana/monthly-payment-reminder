import asyncio
from contextlib import closing
from datetime import datetime,timezone
from pathlib import Path
import json,logging,os,sqlite3,time
from unittest.mock import patch
import pytest
import config
from database.backup import verified_backup,daily_backup
from database.connection import db_connection
from database.migrations import run_migrations
from database.reminder_dispatch_repository import claim_attempt,finish_attempt,was_dispatched
from services.runtime_service import instance_lock,validate_storage
from services.logging_service import SecretSafeFormatter
from ops.__main__ import health_errors


def test_wal_backup_restore_and_retention(temp_db,tmp_path):
    with closing(sqlite3.connect(temp_db)) as conn:
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute("INSERT INTO groups(chat_id,title) VALUES(-5,'Keep')");conn.commit()
        backup=verified_backup(temp_db,tmp_path/'backup.db')
    restored=verified_backup(backup,tmp_path/'restored.db')
    with closing(sqlite3.connect(restored)) as conn:
        assert conn.execute('SELECT title FROM groups WHERE chat_id=-5').fetchone()[0]=='Keep'
        assert conn.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
    with pytest.raises(ValueError): verified_backup(backup,restored)
    for day in range(1,11): daily_backup(temp_db,tmp_path/'backups',datetime(2026,8,day,tzinfo=timezone.utc))
    assert len(list((tmp_path/'backups').glob('daily-*.db')))==7
    assert 1<=len(list((tmp_path/'backups').glob('weekly-*.db')))<=4


def test_migration_failure_rolls_back(temp_db,monkeypatch):
    import database.migrations as migrations
    def fail(conn):
        conn.execute('CREATE TABLE should_rollback(id INTEGER)')
        raise RuntimeError('test')
    monkeypatch.setattr(migrations,'MIGRATIONS',[(999,'failure',fail,False)])
    with db_connection() as conn:
        with pytest.raises(RuntimeError): run_migrations(conn)
        assert conn.execute("SELECT 1 FROM sqlite_master WHERE name='should_rollback'").fetchone() is None
        assert conn.execute('SELECT 1 FROM schema_migrations WHERE version=999').fetchone() is None


def test_single_instance_and_storage(temp_db,tmp_path):
    with instance_lock(temp_db,'test-token'):
        with pytest.raises(RuntimeError):
            with instance_lock(temp_db,'different-token'): pass
        with pytest.raises(RuntimeError):
            with instance_lock(tmp_path/'different.db','test-token'): pass
    with pytest.raises(RuntimeError): validate_storage(tmp_path/'missing.db',True)


def test_attempt_retry_bound_and_uncertainty(temp_db):
    assert claim_attempt(1,'2026-08-01',100)
    assert not claim_attempt(1,'2026-08-01',100)
    finish_attempt(1,'2026-08-01','failed',200)
    assert not claim_attempt(1,'2026-08-01',199)
    assert claim_attempt(1,'2026-08-01',200)
    finish_attempt(1,'2026-08-01','failed',300)
    assert claim_attempt(1,'2026-08-01',300)
    finish_attempt(1,'2026-08-01','failed')
    assert not claim_attempt(1,'2026-08-01',400)
    assert claim_attempt(2,'2026-08-01',100)
    finish_attempt(2,'2026-08-01','uncertain')
    assert not claim_attempt(2,'2026-08-01',10000)


def test_health_staleness_and_backup(temp_db,tmp_path):
    now=time.time();state=tmp_path/'health.json'
    data={'pid':os.getpid(),'ready':True,'scheduler_at':now,'telegram_at':now}
    state.write_text(json.dumps(data))
    assert health_errors(temp_db,state,now=now)==[]
    assert health_errors(temp_db,state,str(tmp_path/'missing'),now=now)
    data['scheduler_at']=0;state.write_text(json.dumps(data))
    assert any('scheduler' in e for e in health_errors(temp_db,state,now=now))


def test_logging_redacts_token_even_in_exception():
    formatter=SecretSafeFormatter('123:SECRET')
    record=logging.LogRecord('test',logging.ERROR,'',1,'https://api.telegram.org/bot123:SECRET/getUpdates',(),None)
    assert 'SECRET' not in formatter.format(record)


@pytest.mark.asyncio
async def test_concurrent_ticks_deliver_once(seeded_payment):
    from scheduler.reminder_scheduler import run_reminder_tick
    class Bot:
        count=0
        async def send_message(self,*args,**kwargs):
            self.count+=1;await asyncio.sleep(0.01)
            return type('Message',(),{'message_id':self.count})()
    bot=Bot()
    with patch('scheduler.reminder_scheduler.datetime') as clock:
        clock.now.return_value=datetime(2026,8,19,9,tzinfo=__import__('zoneinfo').ZoneInfo('Asia/Phnom_Penh'))
        await asyncio.gather(run_reminder_tick(bot),run_reminder_tick(bot))
    assert bot.count==1


@pytest.mark.asyncio
async def test_ambiguous_failure_not_blindly_retried(seeded_payment):
    from scheduler.reminder_scheduler import run_reminder_tick
    class Bot:
        count=0
        async def send_message(self,*args,**kwargs): self.count+=1;raise TimeoutError('connection lost')
    bot=Bot()
    with patch('scheduler.reminder_scheduler.datetime') as clock:
        clock.now.return_value=datetime(2026,8,19,9,tzinfo=__import__('zoneinfo').ZoneInfo('Asia/Phnom_Penh'))
        await run_reminder_tick(bot);await run_reminder_tick(bot)
    assert bot.count==1
    assert not was_dispatched(seeded_payment['payment_id'],'2026-08-19')


@pytest.mark.asyncio
async def test_clean_shutdown_and_partial_startup_close_resources(temp_db,tmp_path,monkeypatch):
    import app
    from types import SimpleNamespace
    from unittest.mock import AsyncMock,Mock
    monkeypatch.setattr(config,'BOT_TOKEN','123456789:TEST_TOKEN_NOT_FOR_NETWORK')
    monkeypatch.setattr(config,'HEALTH_PATH',str(tmp_path/'runtime-health.json'))
    bot=SimpleNamespace(get_me=AsyncMock(),session=SimpleNamespace(middleware=Mock(),close=AsyncMock()))
    monkeypatch.setattr(app,'Bot',Mock(return_value=bot))
    monkeypatch.setattr(app.dp,'start_polling',AsyncMock())
    await app.main()
    bot.session.close.assert_awaited_once()
    assert json.loads((tmp_path/'runtime-health.json').read_text())['ready'] is False
    bot.session.close.reset_mock();bot.get_me.side_effect=RuntimeError('probe failed')
    with pytest.raises(RuntimeError): await app.main()
    bot.session.close.assert_awaited_once()
    with instance_lock(temp_db,config.BOT_TOKEN): pass


def test_multigroup_timezone_and_bad_payment_isolation(seeded_payment):
    from database.group_repository import add_group
    from database.member_repository import add_member
    from database.payment_repository import create_payment,add_payment_member
    from services.settings_service import save_setting
    from services.reminder_service import get_eligible_reminders
    add_group(-2,'New York');add_member(2001,-2,None,'Member')
    pid=create_payment(-2,'New York rent',1,'USD',19,'09:00');add_payment_member(pid,2001)
    save_setting(-2,'timezone','America/New_York')
    instant=datetime(2026,8,19,3,tzinfo=timezone.utc)
    reminders=get_eligible_reminders(instant)
    assert [r.payment_id for r in reminders]==[seeded_payment['payment_id']]
    with db_connection() as c: c.execute("UPDATE payments SET reminder_time='broken' WHERE id=?",(pid,))
    reminders=get_eligible_reminders(datetime(2026,8,19,14,tzinfo=timezone.utc))
    assert [r.payment_id for r in reminders]==[seeded_payment['payment_id']]


def test_large_group_mentions_split_without_losing_members():
    from services.reminder_service import build_reminder_messages
    members=[{'user_id':i,'username':None,'full_name':'<&'+str(i)+'x'*80} for i in range(200)]
    messages=build_reminder_messages({'name':'Big group','amount':5,'currency':'USD'},members)
    assert len(messages)>1 and all(len(text)<4096 for text in messages)
    assert sum(text.count('tg://user?id=') for text in messages)==200


def test_operational_cli_roundtrip_and_init_protection(temp_db,tmp_path):
    from ops.__main__ import main
    destination=tmp_path/'restored-cli.db';backups=tmp_path/'cli-backups'
    assert main(['--db',temp_db,'backup','--directory',str(backups)])==0
    source=next(backups.glob('daily-*.db'))
    assert main(['restore','--source',str(source),'--destination',str(destination)])==0
    with pytest.raises(ValueError): main(['--db',temp_db,'init'])
    with closing(sqlite3.connect(destination)) as conn:
        assert conn.execute('PRAGMA integrity_check').fetchone()[0]=='ok'


def test_destructive_migration_backs_up_before_change(temp_db,monkeypatch):
    import database.migrations as migrations
    def add_test_table(conn): conn.execute('CREATE TABLE migration_proof(id INTEGER)')
    monkeypatch.setattr(migrations,'MIGRATIONS',[(999,'test backup path',add_test_table,True)])
    with db_connection() as conn: run_migrations(conn,temp_db)
    backups=list(Path(temp_db).parent.glob('test_reminder.db.backup-*'))
    assert len(backups)==1
    with closing(sqlite3.connect(backups[0])) as conn:
        assert conn.execute("SELECT 1 FROM sqlite_master WHERE name='migration_proof'").fetchone() is None
        assert conn.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
