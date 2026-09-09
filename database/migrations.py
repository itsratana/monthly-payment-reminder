"""Small versioned migration mechanism.

The project has no external migration framework (no Alembic, etc.), so this
module provides a minimal one: each migration is an additive, idempotent
function keyed by an integer version. Applied versions are recorded in
`schema_migrations` so `init_db()` is safe to call on every process start
without redoing work or risking existing data.

Only additive migrations are registered today (new tables / columns via
`CREATE TABLE IF NOT EXISTS` / `ALTER TABLE ... ADD COLUMN`). If a future
migration must be destructive (drop/rename/rewrite), mark it
`is_destructive=True` so a timestamped backup of the database file is taken
automatically before it runs.
"""

import logging
import os
from database.backup import verified_backup
from datetime import datetime

import config

logger = logging.getLogger(__name__)


def _ensure_migrations_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)


def _applied_versions(conn):
    rows = conn.execute("SELECT version FROM schema_migrations").fetchall()
    return {row["version"] for row in rows}


def _backup_database(db_path: str):
    if not os.path.exists(db_path):
        return None

    timestamp = datetime.now().strftime("%Y%m%d%H%M%S%f")
    backup_path = f"{db_path}.backup-{timestamp}"
    verified_backup(db_path, backup_path)
    logger.warning("Backed up database to %s before migration", backup_path)
    return backup_path


def _migration_0001_reminder_dispatches(conn):
    """Additive: durable dispatch idempotency table (spec section 8.2)."""

    conn.execute("""
        CREATE TABLE IF NOT EXISTS reminder_dispatches (
            payment_id INTEGER NOT NULL,
            year INTEGER NOT NULL,
            month INTEGER NOT NULL CHECK (month BETWEEN 1 AND 12),
            local_date TEXT NOT NULL,
            chat_id INTEGER NOT NULL,
            message_id INTEGER,
            sent_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (payment_id, local_date)
        )
    """)


# (version, description, migration_fn, is_destructive)
MIGRATIONS = [
    (1, "create reminder_dispatches", _migration_0001_reminder_dispatches, False),
]


def run_migrations(conn, db_path: str | None = None):
    _ensure_migrations_table(conn)
    applied = _applied_versions(conn)

    pending = [m for m in MIGRATIONS if m[0] not in applied]
    if not pending:
        return

    if any(is_destructive for _, _, _, is_destructive in pending):
        _backup_database(db_path or config.DATABASE_PATH)

    for version, description, migration_fn, _ in pending:
        logger.info("Applying migration %s: %s", version, description)
        try:
            conn.execute('BEGIN IMMEDIATE')
            migration_fn(conn)
            conn.execute("INSERT INTO schema_migrations (version) VALUES (?)", (version,))
            conn.commit()
        except Exception:
            conn.rollback()
            raise


def _migration_0002_management(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS group_settings (
        chat_id INTEGER PRIMARY KEY, currency TEXT NOT NULL DEFAULT 'USD',
        timezone TEXT, reminder_time TEXT NOT NULL DEFAULT '09:00',
        reminder_policy TEXT NOT NULL DEFAULT 'daily_until_paid')''')
    conn.execute('''CREATE TABLE IF NOT EXISTS status_audit (
        id INTEGER PRIMARY KEY AUTOINCREMENT, payment_id INTEGER NOT NULL,
        chat_id INTEGER NOT NULL, user_id INTEGER NOT NULL, actor_id INTEGER NOT NULL,
        year INTEGER NOT NULL, month INTEGER NOT NULL, old_paid INTEGER NOT NULL,
        new_paid INTEGER NOT NULL, changed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
    conn.execute('CREATE INDEX IF NOT EXISTS payments_group_idx ON payments(chat_id, due_day)')
    conn.execute('CREATE INDEX IF NOT EXISTS status_period_idx ON payment_status(year, month, payment_id)')
    conn.execute('CREATE INDEX IF NOT EXISTS audit_payment_idx ON status_audit(payment_id, year, month)')


MIGRATIONS.append((2, 'group settings and status correction audit', _migration_0002_management, False))


def _migration_0003_delivery_attempts(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS reminder_attempts (
        payment_id INTEGER NOT NULL,local_date TEXT NOT NULL,state TEXT NOT NULL,
        attempts INTEGER NOT NULL DEFAULT 1,retry_after REAL NOT NULL DEFAULT 0,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY(payment_id,local_date))''')
    conn.execute('''CREATE TABLE IF NOT EXISTS reminder_messages (
        payment_id INTEGER NOT NULL,year INTEGER NOT NULL,month INTEGER NOT NULL,
        local_date TEXT NOT NULL,chat_id INTEGER NOT NULL,message_id INTEGER NOT NULL,
        PRIMARY KEY(chat_id,message_id))''')


MIGRATIONS.append((3,'durable delivery attempts and multipart messages',_migration_0003_delivery_attempts,False))


def _migration_0004_group_onboarding(conn):
    conn.execute("""
        ALTER TABLE groups
        ADD COLUMN onboarding_posted INTEGER NOT NULL DEFAULT 0
    """)


MIGRATIONS.append((
    4,
    'track whether group onboarding button was posted',
    _migration_0004_group_onboarding,
    False
))
