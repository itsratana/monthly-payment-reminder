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
    columns = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(groups)").fetchall()
    }

    if "onboarding_posted" not in columns:
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


def _migration_0005_multiple_reminder_times(conn):
    # ---------------------------------------------------------
    # Reminder times configured for each payment.
    #
    # Existing payments are automatically migrated from the
    # old payments.reminder_time column.
    # ---------------------------------------------------------
    conn.execute("""
        CREATE TABLE IF NOT EXISTS payment_reminder_times (
            payment_id INTEGER NOT NULL,
            reminder_time TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

            PRIMARY KEY (payment_id, reminder_time),

            FOREIGN KEY (payment_id)
                REFERENCES payments(id)
                ON DELETE CASCADE
        )
    """)

    # Preserve the current reminder time of every existing payment.
    conn.execute("""
        INSERT OR IGNORE INTO payment_reminder_times (
            payment_id,
            reminder_time
        )
        SELECT
            id,
            reminder_time
        FROM payments
        WHERE reminder_time IS NOT NULL
          AND reminder_time != ''
    """)

    # ---------------------------------------------------------
    # Automatic reminder duplicate protection.
    #
    # Unlike the old reminder_dispatches table, this allows:
    #
    # payment 1
    # 2026-09-15
    # 09:00
    #
    # AND
    #
    # payment 1
    # 2026-09-15
    # 18:00
    #
    # while still preventing each slot from being sent twice.
    # ---------------------------------------------------------
    conn.execute("""
        CREATE TABLE IF NOT EXISTS reminder_slot_dispatches (
            payment_id INTEGER NOT NULL,
            year INTEGER NOT NULL,
            month INTEGER NOT NULL
                CHECK (month BETWEEN 1 AND 12),
            local_date TEXT NOT NULL,
            reminder_time TEXT NOT NULL,
            chat_id INTEGER NOT NULL,
            message_id INTEGER,
            sent_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

            PRIMARY KEY (
                payment_id,
                local_date,
                reminder_time
            )
        )
    """)

    # ---------------------------------------------------------
    # Retry / delivery protection for each automatic slot.
    # ---------------------------------------------------------
    conn.execute("""
        CREATE TABLE IF NOT EXISTS reminder_slot_attempts (
            payment_id INTEGER NOT NULL,
            local_date TEXT NOT NULL,
            reminder_time TEXT NOT NULL,
            state TEXT NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 1,
            retry_after REAL NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

            PRIMARY KEY (
                payment_id,
                local_date,
                reminder_time
            )
        )
    """)

    # ---------------------------------------------------------
    # Tracks the messages belonging to one reminder send.
    #
    # batch_key will later distinguish:
    #
    # auto:09:00
    # auto:18:00
    # manual:<unique id>
    #
    # This means manual reminders do NOT interfere with
    # automatic reminder duplicate protection.
    # ---------------------------------------------------------
    conn.execute("""
        CREATE TABLE IF NOT EXISTS reminder_message_batches (
            payment_id INTEGER NOT NULL,
            year INTEGER NOT NULL,
            month INTEGER NOT NULL
                CHECK (month BETWEEN 1 AND 12),
            local_date TEXT NOT NULL,
            batch_key TEXT NOT NULL,
            chat_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL,
            sent_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

            PRIMARY KEY (chat_id, message_id)
        )
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS payment_reminder_times_payment_idx
        ON payment_reminder_times(payment_id)
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS reminder_message_batches_period_idx
        ON reminder_message_batches(
            payment_id,
            year,
            month,
            sent_at
        )
    """)


MIGRATIONS.append((
    5,
    'multiple reminder times and reminder message batches',
    _migration_0005_multiple_reminder_times,
    False
))
