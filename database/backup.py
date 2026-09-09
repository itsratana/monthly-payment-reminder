"""Consistent SQLite backups, including databases using WAL."""
from contextlib import closing
from datetime import datetime,timezone
from pathlib import Path
import os
import sqlite3
import tempfile


def verified_backup(source,destination):
    source=Path(source).resolve();destination=Path(destination).resolve()
    if source==destination or destination.exists(): raise ValueError('Backup destination must be a new, separate file.')
    destination.parent.mkdir(parents=True,exist_ok=True)
    fd,temporary=tempfile.mkstemp(prefix='.backup-',dir=destination.parent);os.close(fd)
    temporary=Path(temporary)
    try:
        with closing(sqlite3.connect(source.as_uri()+'?mode=ro',uri=True)) as src, closing(sqlite3.connect(temporary)) as dst:
            src.backup(dst)
            if dst.execute('PRAGMA integrity_check').fetchone()[0]!='ok': raise RuntimeError('Backup integrity check failed')
            dst.commit()
        temporary.chmod(0o600)
        # Link is exclusive: never overwrite an existing backup in a race.
        os.link(temporary,destination)
        return destination
    finally: temporary.unlink(missing_ok=True)


def daily_backup(source,directory,now=None):
    now=now or datetime.now(timezone.utc);directory=Path(directory)
    stamp=now.strftime('%Y%m%dT%H%M%S%fZ')
    result=verified_backup(source,directory/f'daily-{stamp}.db')
    week=now.strftime('%G-W%V')
    if not list(directory.glob(f'weekly-{week}-*.db')):
        verified_backup(result,directory/f'weekly-{week}-{stamp}.db')
    for pattern,keep in [('daily-*.db',7),('weekly-*.db',4)]:
        for old in sorted(directory.glob(pattern),reverse=True)[keep:]: old.unlink()
    return result
