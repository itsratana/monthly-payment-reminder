import argparse
from contextlib import closing
import json
import logging
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import time
import urllib.request
import config
from database.backup import verified_backup,daily_backup
from services.runtime_service import instance_lock


def health_errors(db,health_path,backup_directory='',now=None):
    now=time.time() if now is None else now;errors=[]
    try:
        state=json.loads(Path(health_path).read_text())
        if not state.get('ready'): errors.append('Application is not ready')
        for field,max_age in [('scheduler_at',max(180,config.REMINDER_CHECK_SECONDS*3)),('telegram_at',180)]:
            if not 0<=now-state.get(field,0)<=max_age: errors.append(f'{field} heartbeat is stale')
        if state.get('selection_failures',0): errors.append('Some payments could not be evaluated')
        if state.get('delivery_failures',0): errors.append('Last scheduler tick had delivery failures')
        os.kill(int(state['pid']),0)
    except (OSError,ValueError,KeyError,TypeError): errors.append('Health state or process unavailable')
    try:
        path=Path(db).resolve()
        with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=2)) as conn:
            conn.execute('SELECT version FROM schema_migrations').fetchall()
            if conn.execute("SELECT COUNT(*) FROM reminder_attempts WHERE state IN ('reserved','uncertain')").fetchone()[0]:
                errors.append('Uncertain/reserved deliveries require operator reconciliation')
            if conn.execute("SELECT COUNT(*) FROM reminder_attempts WHERE state='failed' AND attempts>=3").fetchone()[0]:
                errors.append('Delivery retries exhausted; inspect bot permissions and reconcile')
        if shutil.disk_usage(path.parent).free<100*1024*1024: errors.append('Less than 100 MiB free on database volume')
    except (OSError,sqlite3.Error): errors.append('Database health query failed')
    if backup_directory:
        backups=list(Path(backup_directory).glob('daily-*.db'))
        if not backups or now-max(p.stat().st_mtime for p in backups)>36*3600:
            errors.append('Daily backup is missing or older than 36 hours')
    return errors


def alert(errors):
    url=os.getenv('MONITOR_WEBHOOK_URL')
    if not url:
        logging.error('MONITOR_WEBHOOK_URL is not configured; route service failures to your monitoring system')
        return
    if not url.startswith('https://'): raise ValueError('Monitoring webhook must use HTTPS')
    request=urllib.request.Request(url,data=json.dumps({'text':'Monthly Payment Reminder health failure: '+'; '.join(errors)}).encode(),headers={'Content-Type':'application/json'})
    try:
        with urllib.request.urlopen(request,timeout=10) as response: response.read(1024)
    except Exception as error:
        # Do not print webhook URLs/tokens on delivery errors.
        raise RuntimeError('Monitoring alert delivery failed') from None


def main(argv=None):
    parser=argparse.ArgumentParser(description='Monthly Payment Reminder operations')
    parser.add_argument('--db',default=config.DATABASE_PATH)
    commands=parser.add_subparsers(dest='command',required=True)
    backup=commands.add_parser('backup');backup.add_argument('--directory',required=True)
    restore=commands.add_parser('restore');restore.add_argument('--source',required=True);restore.add_argument('--destination',required=True)
    commands.add_parser('init')
    commands.add_parser('migrate')
    health=commands.add_parser('health');health.add_argument('--state',default=config.HEALTH_PATH);health.add_argument('--backups',default=config.BACKUP_DIRECTORY);health.add_argument('--notify',action='store_true')
    reconcile=commands.add_parser('reconcile');reconcile.add_argument('--payment',type=int,required=True);reconcile.add_argument('--date',required=True);reconcile.add_argument('--outcome',choices=['sent','retry'],required=True)
    args=parser.parse_args(argv)
    if args.command=='backup':
        print(daily_backup(args.db,args.directory))
    elif args.command=='restore':
        with instance_lock(args.destination,config.BOT_TOKEN or 'maintenance'):
            print(verified_backup(args.source,args.destination))
    elif args.command in ('init','migrate'):
        exists=Path(args.db).exists()
        if args.command=='init' and exists: raise ValueError('Database already exists; use migrate after backing up.')
        if args.command=='migrate' and not exists: raise ValueError('Existing database missing; refusing empty initialization.')
        with instance_lock(args.db,config.BOT_TOKEN or 'maintenance'):
            if exists: print(verified_backup(args.db,str(args.db)+f'.backup-{time.time_ns()}'))
            config.DATABASE_PATH=args.db
            from database.schema import init_db
            init_db();Path(args.db).chmod(0o600)
            print('Database ready')
    elif args.command=='health':
        errors=health_errors(args.db,args.state,args.backups)
        if errors:
            print('\n'.join(errors))
            if args.notify: alert(errors)
            return 1
        print('Healthy')
    else:
        from datetime import date
        date.fromisoformat(args.date)
        with instance_lock(args.db,config.BOT_TOKEN or 'maintenance'):
            with closing(sqlite3.connect(Path(args.db).resolve().as_uri()+'?mode=rw',uri=True)) as conn:
                conn.execute('BEGIN IMMEDIATE')
                row=conn.execute('SELECT state FROM reminder_attempts WHERE payment_id=? AND local_date=?',(args.payment,args.date)).fetchone()
                if not row: raise ValueError('No attempt exists for this payment/date')
                if args.outcome=='retry':
                    if conn.execute('SELECT 1 FROM reminder_dispatches WHERE payment_id=? AND local_date=?',(args.payment,args.date)).fetchone():
                        raise ValueError('A successful dispatch exists; refusing duplicate retry')
                    conn.execute("UPDATE reminder_attempts SET state='failed',attempts=0,retry_after=0 WHERE payment_id=? AND local_date=?",(args.payment,args.date))
                else:
                    conn.execute("UPDATE reminder_attempts SET state='sent' WHERE payment_id=? AND local_date=?",(args.payment,args.date))
                conn.commit()
                print('Reconciled. Retry is allowed only after verifying no message was delivered.')
    return 0


if __name__=='__main__':
    try: sys.exit(main())
    except (ValueError,RuntimeError,OSError,sqlite3.Error) as error:
        print(f'Operation failed: {error}',file=sys.stderr);sys.exit(1)
