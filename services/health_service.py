"""In-memory health feeds an atomic local state file only while app is running."""
import json
import logging
logger=logging.getLogger(__name__)
import os
import time
from pathlib import Path

_state={'ready':False,'scheduler_at':0,'telegram_at':0,'delivery_failures':0}
_path=None


def configure_health(path):
    global _path
    _path=Path(path)
    _state.update(ready=False,scheduler_at=0,telegram_at=0,delivery_failures=0,selection_failures=0)


def write_health(**values):
    _state.update(values)
    if _path:
        temporary=_path.with_suffix(_path.suffix+'.tmp')
        try:
            temporary.write_text(json.dumps({**_state,'pid':os.getpid(),'written_at':time.time()}))
            temporary.chmod(0o600);temporary.replace(_path)
        except OSError:
            logger.exception('Cannot persist health state; health probe will become stale')


def scheduler_heartbeat(failures=0):
    write_health(scheduler_at=time.time(),delivery_failures=failures)


def telegram_heartbeat(): write_health(telegram_at=time.time())
