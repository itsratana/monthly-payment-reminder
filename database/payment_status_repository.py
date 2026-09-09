from .connection import db_connection


def create_payment_status(payment_id, user_id, year, month):
    """Idempotent insert of a single member's status row for a period."""

    with db_connection() as conn:
        conn.execute("""
            INSERT OR IGNORE INTO payment_status (
                payment_id,
                user_id,
                year,
                month
            )
            VALUES (?, ?, ?, ?)
        """, (
            payment_id,
            user_id,
            year,
            month
        ))


def initialize_for_assigned_members(payment_id, year, month):
    """Create a status row for every currently assigned member of a payment.

    Single INSERT ... SELECT, idempotent via INSERT OR IGNORE against the
    (payment_id, user_id, year, month) primary key. Safe to call on every
    reminder build so a member assigned after the first reminder gets a row
    on the next pass (spec 4.3).
    """

    with db_connection() as conn:
        conn.execute("""
            INSERT OR IGNORE INTO payment_status (
                payment_id,
                user_id,
                year,
                month
            )
            SELECT
                pm.payment_id,
                pm.user_id,
                ?,
                ?
            FROM payment_members AS pm
            JOIN payments p ON p.id=pm.payment_id
            JOIN members m ON m.user_id=pm.user_id AND m.chat_id=p.chat_id
            WHERE pm.payment_id = ?
        """, (year, month, payment_id))


def get_unpaid_members(payment_id, year, month):
    """Currently assigned, unpaid members for a period, with mention data.

    Joins payment_members so a member who was unassigned after their status
    row was created no longer appears (spec 4.3). `members` is scoped by
    (user_id, chat_id), so the join also pins chat_id to the payment's own
    group - a user_id that happens to belong to more than one group must
    not produce duplicate or wrong-chat rows.
    """

    with db_connection() as conn:
        return conn.execute("""
            SELECT
                ps.user_id,
                m.username,
                m.full_name
            FROM payment_status AS ps
            JOIN payment_members AS pm
              ON pm.payment_id = ps.payment_id
             AND pm.user_id = ps.user_id
            JOIN payments AS p
              ON p.id = ps.payment_id
            JOIN members AS m
              ON m.user_id = ps.user_id
             AND m.chat_id = p.chat_id
            WHERE ps.payment_id = ?
              AND ps.year = ?
              AND ps.month = ?
              AND ps.paid = 0
            ORDER BY COALESCE(m.full_name, m.username, CAST(m.user_id AS TEXT))
        """, (payment_id, year, month)).fetchall()


def get_status(payment_id, user_id, year, month):
    with db_connection() as conn:
        return conn.execute("""
            SELECT *
            FROM payment_status
            WHERE payment_id = ?
              AND user_id = ?
              AND year = ?
              AND month = ?
        """, (payment_id, user_id, year, month)).fetchone()


def mark_as_paid(payment_id, user_id, year, month) -> bool:
    """Mark a member paid for a period. Returns True if a row changed.

    Guarded by `AND paid = 0` so a repeated click is a harmless no-op
    instead of re-stamping paid_at (spec 4.4).
    """

    with db_connection() as conn:
        cursor = conn.execute("""
            UPDATE payment_status
            SET
                paid = 1,
                paid_at = CURRENT_TIMESTAMP
            WHERE payment_id = ?
              AND user_id = ?
              AND year = ?
              AND month = ?
              AND paid = 0
        """, (payment_id, user_id, year, month))

        return cursor.rowcount > 0


def cycle_members(payment_id, year, month, current=False):
    """History uses recorded rows; current views use current assignments."""
    with db_connection() as conn:
        if current:
            return conn.execute('''SELECT pm.user_id,m.full_name,m.username,COALESCE(ps.paid,0) AS paid
                FROM payment_members pm JOIN payments p ON p.id=pm.payment_id
                JOIN members m ON m.user_id=pm.user_id AND m.chat_id=p.chat_id
                LEFT JOIN payment_status ps ON ps.payment_id=pm.payment_id AND ps.user_id=pm.user_id
                  AND ps.year=? AND ps.month=? WHERE pm.payment_id=? ORDER BY m.full_name,pm.user_id''',
                (year,month,payment_id)).fetchall()
        return conn.execute('''SELECT ps.user_id,m.full_name,m.username,ps.paid FROM payment_status ps
            JOIN payments p ON p.id=ps.payment_id
            LEFT JOIN members m ON m.user_id=ps.user_id AND m.chat_id=p.chat_id
            WHERE ps.payment_id=? AND ps.year=? AND ps.month=? ORDER BY m.full_name,ps.user_id''',
            (payment_id,year,month)).fetchall()


def history_payments(chat_id,year,month):
    with db_connection() as conn:
        return conn.execute('''SELECT p.*,COUNT(ps.user_id) AS total,SUM(ps.paid) AS completed
            FROM payments p JOIN payment_status ps ON ps.payment_id=p.id
            WHERE p.chat_id=? AND ps.year=? AND ps.month=? GROUP BY p.id ORDER BY p.name''',
            (chat_id,year,month)).fetchall()


def change_status(payment_id,user_id,year,month,paid,actor_id):
    """Save a correction and its audit row atomically. No-op preserves timestamps."""
    with db_connection() as conn:
        conn.execute('BEGIN IMMEDIATE')
        row=conn.execute('''SELECT ps.paid,p.chat_id FROM payment_status ps
            JOIN payments p ON p.id=ps.payment_id
            JOIN payment_members pm ON pm.payment_id=ps.payment_id AND pm.user_id=ps.user_id
            JOIN members m ON m.user_id=ps.user_id AND m.chat_id=p.chat_id
            WHERE ps.payment_id=? AND ps.user_id=? AND ps.year=? AND ps.month=? AND p.active=1''',
            (payment_id,user_id,year,month)).fetchone()
        if row is None: raise ValueError('This member or active payment is no longer available.')
        if row['paid']==int(paid): return False
        conn.execute('''UPDATE payment_status SET paid=?,paid_at=CASE WHEN ?=1 THEN CURRENT_TIMESTAMP ELSE NULL END
            WHERE payment_id=? AND user_id=? AND year=? AND month=?''',
            (int(paid),int(paid),payment_id,user_id,year,month))
        conn.execute('''INSERT INTO status_audit(payment_id,chat_id,user_id,actor_id,year,month,old_paid,new_paid)
            VALUES (?,?,?,?,?,?,?,?)''',(payment_id,row['chat_id'],user_id,actor_id,year,month,row['paid'],int(paid)))
        return True
