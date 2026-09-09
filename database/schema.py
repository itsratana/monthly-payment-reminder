from .connection import get_connection
from .migrations import run_migrations


def init_db():
    conn = get_connection()
    try:
        cursor = conn.cursor()
    
        # --------------------
        # Groups
        # --------------------
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS groups (
            chat_id INTEGER PRIMARY KEY,
            title TEXT NOT NULL,
            onboarding_posted INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
    
        # --------------------
        # Members
        # --------------------
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS members (
            user_id INTEGER,
            chat_id INTEGER,
            username TEXT,
            full_name TEXT,
            joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(user_id, chat_id)
        )
        """)
    
        # --------------------
        # Group Admins
        # --------------------
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS group_admins (
            chat_id INTEGER,
            user_id INTEGER,
            selected INTEGER DEFAULT 0,
            PRIMARY KEY(chat_id, user_id)
        )
        """)
    
        # --------------------
        # Payments
        # --------------------
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER,
            name TEXT NOT NULL,
            amount REAL NOT NULL,
            currency TEXT DEFAULT 'USD',
            due_day INTEGER NOT NULL,
            reminder_time TEXT DEFAULT '09:00',
            active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
    
        # --------------------
        # Payment Members
        # --------------------
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS payment_members (
            payment_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
    
            PRIMARY KEY(payment_id, user_id),
    
            FOREIGN KEY(payment_id) REFERENCES payments(id),
            FOREIGN KEY(user_id) REFERENCES members(user_id)
        )
        """)
    
        # --------------------
        # Payment Status
        # --------------------
        # NOTE: the real database already has this table with a
        # `last_reminded_at` column from an earlier iteration. That column is no
        # longer written by the app (dispatch idempotency now lives in
        # reminder_dispatches instead) but is kept here so CREATE TABLE IF NOT
        # EXISTS matches existing installs and never touches existing rows.
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS payment_status (
            payment_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            year INTEGER NOT NULL,
            month INTEGER NOT NULL CHECK (month BETWEEN 1 AND 12),
            paid INTEGER NOT NULL DEFAULT 0 CHECK (paid IN (0, 1)),
            paid_at TEXT,
            last_reminded_at TIMESTAMP,
            PRIMARY KEY (payment_id, user_id, year, month)
        )
        """)
    
        conn.commit()
    
        # Additive, versioned migrations (new tables/columns only). Safe to run
        # on every startup.
        run_migrations(conn)
    
    finally:
        conn.close()
