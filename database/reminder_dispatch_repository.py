import sqlite3

from .connection import db_connection


def was_dispatched(payment_id: int, local_date: str) -> bool:
    with db_connection() as conn:
        row = conn.execute("""
            SELECT 1
            FROM reminder_dispatches
            WHERE payment_id = ?
              AND local_date = ?
        """, (payment_id, local_date)).fetchone()

        return row is not None


def record_dispatch(
    payment_id: int,
    year: int,
    month: int,
    local_date: str,
    chat_id: int,
    message_id: int | None,
) -> bool:
    """Record a sent reminder. Returns False (not an error) on a duplicate.

    The (payment_id, local_date) primary key is the source of truth for
    "at most one reminder per payment per local day" - a UNIQUE/PK conflict
    here means another tick already recorded today's dispatch, which is an
    expected race under concurrent ticks, not a crash.
    """

    try:
        with db_connection() as conn:
            conn.execute("""
                INSERT INTO reminder_dispatches (
                    payment_id,
                    year,
                    month,
                    local_date,
                    chat_id,
                    message_id
                )
                VALUES (?, ?, ?, ?, ?, ?)
            """, (payment_id, year, month, local_date, chat_id, message_id))
        return True
    except sqlite3.IntegrityError:
        return False


def cycle_dispatches(payment_id,year,month):
    with db_connection() as conn:
        return conn.execute('''SELECT * FROM reminder_dispatches WHERE payment_id=? AND year=? AND month=?
            AND message_id IS NOT NULL ORDER BY local_date DESC''',(payment_id,year,month)).fetchall()


def claim_attempt(payment_id,local_date,now):
    with db_connection() as conn:
        conn.execute('BEGIN IMMEDIATE')
        if conn.execute('SELECT 1 FROM reminder_dispatches WHERE payment_id=? AND local_date=?',(payment_id,local_date)).fetchone(): return False
        row=conn.execute('SELECT * FROM reminder_attempts WHERE payment_id=? AND local_date=?',(payment_id,local_date)).fetchone()
        if row:
            if row['state']!='failed' or row['attempts']>=3 or row['retry_after']>now: return False
            conn.execute("UPDATE reminder_attempts SET state='reserved',attempts=attempts+1,updated_at=CURRENT_TIMESTAMP WHERE payment_id=? AND local_date=?",(payment_id,local_date))
        else:
            conn.execute("INSERT INTO reminder_attempts(payment_id,local_date,state) VALUES (?,?,'reserved')",(payment_id,local_date))
        return True


def finish_attempt(payment_id,local_date,state,retry_after=0):
    if state not in {'sent','failed','uncertain'}: raise ValueError('Invalid delivery state')
    with db_connection() as conn:
        conn.execute('UPDATE reminder_attempts SET state=?,retry_after=?,updated_at=CURRENT_TIMESTAMP WHERE payment_id=? AND local_date=?',(state,retry_after,payment_id,local_date))


def record_message(reminder,message_id):
    with db_connection() as conn:
        conn.execute('INSERT OR IGNORE INTO reminder_messages VALUES (?,?,?,?,?,?)',
                     (reminder.payment_id,reminder.year,reminder.month,reminder.local_date,reminder.chat_id,message_id))


def latest_messages(payment_id,year,month):
    with db_connection() as conn:
        rows=conn.execute('''SELECT * FROM reminder_messages WHERE payment_id=? AND year=? AND month=?
            AND local_date=(SELECT MAX(local_date) FROM reminder_messages WHERE payment_id=? AND year=? AND month=?)
            ORDER BY message_id''',(payment_id,year,month,payment_id,year,month)).fetchall()
    return rows or cycle_dispatches(payment_id,year,month)[:1]
