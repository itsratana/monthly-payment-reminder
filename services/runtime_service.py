import asyncio
import fcntl
import hashlib
import logging
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from aiogram.methods import GetUpdates
from services.health_service import telegram_heartbeat,write_health
logger=logging.getLogger(__name__)


@contextmanager
def instance_lock(database_path,token):
    """Both database and token locks are necessary; acquired for process lifetime."""
    paths=[Path(str(Path(database_path).resolve())+'.lock'),
           Path(tempfile.gettempdir())/f'payment-bot-{os.getuid()}-{hashlib.sha256(token.encode()).hexdigest()[:24]}.lock']
    handles=[]
    try:
        for path in paths:
            handle=open(path,'a');handles.append(handle);os.chmod(path,0o600)
            try: fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError as error: raise RuntimeError('Another bot owns this database or token. Stop it first.') from error
        yield
    finally:
        for handle in reversed(handles): handle.close()


async def observe_telegram(make_request,bot,method):
    result=await make_request(bot,method)
    if isinstance(method,GetUpdates): telegram_heartbeat()
    return result


async def startup_probe(bot):
    await bot.get_me()
    telegram_heartbeat()


def validate_storage(path,require_existing=False):
    path=Path(path).resolve()
    if require_existing and not path.is_file(): raise RuntimeError('Database missing. Restore/mount the persistent database before starting.')
    if not path.parent.is_dir() or not os.access(path.parent,os.W_OK): raise RuntimeError('Database directory is not writable.')
    if path.exists() and not os.access(path,os.W_OK): raise RuntimeError('Database is not writable.')
    return path
