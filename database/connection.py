from contextlib import contextmanager
import sqlite3

import config

# Kept for backward compatibility with any code that imports DB_NAME
# directly. Prefer config.DATABASE_PATH / the db_path argument below.
DB_NAME = config.DATABASE_PATH


def get_connection(db_path: str | None = None) -> sqlite3.Connection:
    """Open a new SQLite connection.

    Reads config.DATABASE_PATH at call time (not import time) so tests can
    point the whole app at a temporary database by monkeypatching
    config.DATABASE_PATH, without needing to change every call site.
    """

    conn = sqlite3.connect(db_path or config.DATABASE_PATH, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 5000")
    # Existing composite-key schema is incompatible with global FK enforcement.
    return conn


@contextmanager
def db_connection(db_path: str | None = None):
    """Context manager that reliably closes the connection.

    sqlite3.Connection's own `__exit__` only commits/rolls back the
    transaction, it does NOT close the connection - relying on that alone
    would leak connections. This commits on a clean exit, rolls back on
    exception, and always closes.
    """

    conn = get_connection(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def check_integrity():
    with db_connection() as conn:
        if conn.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
            raise RuntimeError('Database integrity check failed. Restore a verified backup before starting.')
