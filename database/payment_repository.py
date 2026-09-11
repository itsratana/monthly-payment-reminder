from .connection import db_connection


def create_payment(
    chat_id: int,
    name: str,
    amount: float,
    currency: str,
    due_day: int,
    reminder_time: str
):
    with db_connection() as conn:
        cursor = conn.execute("""
            INSERT INTO payments (
                chat_id,
                name,
                amount,
                currency,
                due_day,
                reminder_time
            )
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            chat_id,
            name,
            amount,
            currency,
            due_day,
            reminder_time
        ))

        return cursor.lastrowid


def get_payments(chat_id: int):
    with db_connection() as conn:
        return conn.execute("""
            SELECT *
            FROM payments
            WHERE chat_id = ?
            ORDER BY due_day
        """, (chat_id,)).fetchall()


def get_payment(payment_id: int):
    with db_connection() as conn:
        return conn.execute("""
            SELECT *
            FROM payments
            WHERE id = ?
        """, (payment_id,)).fetchone()

def get_payment_reminder_times(payment_id: int):
    with db_connection() as conn:
        return conn.execute("""
            SELECT reminder_time
            FROM payment_reminder_times
            WHERE payment_id = ?
            ORDER BY reminder_time
        """, (payment_id,)).fetchall()


def add_payment_reminder_time(
    payment_id: int,
    reminder_time: str
):
    with db_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")

        payment = conn.execute("""
            SELECT id
            FROM payments
            WHERE id = ?
        """, (payment_id,)).fetchone()

        if payment is None:
            return "missing"

        existing = conn.execute("""
            SELECT 1
            FROM payment_reminder_times
            WHERE payment_id = ?
              AND reminder_time = ?
        """, (
            payment_id,
            reminder_time
        )).fetchone()

        if existing:
            return "exists"

        count = conn.execute("""
            SELECT COUNT(*) AS total
            FROM payment_reminder_times
            WHERE payment_id = ?
        """, (payment_id,)).fetchone()["total"]

        if count >= 3:
            return "limit"

        conn.execute("""
            INSERT INTO payment_reminder_times (
                payment_id,
                reminder_time
            )
            VALUES (?, ?)
        """, (
            payment_id,
            reminder_time
        ))

        # Keep the old payments.reminder_time column synced for
        # backwards compatibility while we transition the bot.
        first_time = conn.execute("""
            SELECT reminder_time
            FROM payment_reminder_times
            WHERE payment_id = ?
            ORDER BY reminder_time
            LIMIT 1
        """, (payment_id,)).fetchone()

        if first_time:
            conn.execute("""
                UPDATE payments
                SET reminder_time = ?
                WHERE id = ?
            """, (
                first_time["reminder_time"],
                payment_id
            ))

        return "added"


def remove_payment_reminder_time(
    payment_id: int,
    reminder_time: str
):
    with db_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")

        rows = conn.execute("""
            SELECT reminder_time
            FROM payment_reminder_times
            WHERE payment_id = ?
            ORDER BY reminder_time
        """, (payment_id,)).fetchall()

        if not rows:
            return "missing"

        times = [
            row["reminder_time"]
            for row in rows
        ]

        if reminder_time not in times:
            return "missing"

        # Every active payment must always keep at least one
        # automatic reminder time.
        if len(times) <= 1:
            return "last"

        conn.execute("""
            DELETE FROM payment_reminder_times
            WHERE payment_id = ?
              AND reminder_time = ?
        """, (
            payment_id,
            reminder_time
        ))

        first_time = conn.execute("""
            SELECT reminder_time
            FROM payment_reminder_times
            WHERE payment_id = ?
            ORDER BY reminder_time
            LIMIT 1
        """, (payment_id,)).fetchone()

        if first_time:
            conn.execute("""
                UPDATE payments
                SET reminder_time = ?
                WHERE id = ?
            """, (
                first_time["reminder_time"],
                payment_id
            ))

        return "removed"


def get_payment_members(payment_id: int):
    with db_connection() as conn:
        return conn.execute("""
            SELECT user_id
            FROM payment_members
            WHERE payment_id = ?
        """, (payment_id,)).fetchall()


def is_member_assigned(payment_id: int, user_id: int) -> bool:
    with db_connection() as conn:
        row = conn.execute("""
            SELECT 1
            FROM payment_members
            WHERE payment_id = ?
              AND user_id = ?
        """, (payment_id, user_id)).fetchone()

        return row is not None


def add_payment_member(payment_id: int, user_id: int):
    with db_connection() as conn:
        conn.execute("""
            INSERT OR IGNORE INTO payment_members (
                payment_id,
                user_id
            )
            VALUES (?, ?)
        """, (payment_id, user_id))


def remove_payment_member(payment_id: int, user_id: int):
    with db_connection() as conn:
        conn.execute("""
            DELETE FROM payment_members
            WHERE payment_id = ?
            AND user_id = ?
        """, (payment_id, user_id))


def get_payment_chat_id(payment_id: int):
    with db_connection() as conn:
        row = conn.execute("""
            SELECT chat_id
            FROM payments
            WHERE id = ?
        """, (payment_id,)).fetchone()

        return row["chat_id"] if row else None


def get_due_payments(day: int):
    with db_connection() as conn:
        return conn.execute("""
            SELECT *
            FROM payments
            WHERE due_day = ?
        """, (day,)).fetchall()


def get_active_payments():
    """All active payments, for scheduler tick candidate evaluation.

    Effective due-day and reminder_time eligibility are date/timezone rules
    applied in services.reminder_service, since SQLite has no clean way to
    express "clamp due_day to the last day of a variable-length month".
    """

    with db_connection() as conn:
        return conn.execute("""
            SELECT *
            FROM payments
            WHERE active = 1
        """).fetchall()


def update_payment(payment_id, chat_id, field, value):
    if field not in {'name', 'amount', 'currency', 'due_day', 'reminder_time', 'active'}:
        raise ValueError('Unknown payment field')
    with db_connection() as conn:
        return conn.execute(f'UPDATE payments SET {field}=? WHERE id=? AND chat_id=?',
                            (value, payment_id, chat_id)).rowcount > 0


def delete_payment_completely(payment_id, chat_id):
    """Permanently delete a payment and all related history."""
    with db_connection() as conn:
        conn.execute('BEGIN IMMEDIATE')

        if not conn.execute(
            'SELECT 1 FROM payments WHERE id=? AND chat_id=?',
            (payment_id, chat_id)
        ).fetchone():
            return 'missing'

        conn.execute(
            'DELETE FROM reminder_dispatches WHERE payment_id=?',
            (payment_id,)
        )

        conn.execute(
            'DELETE FROM payment_status WHERE payment_id=?',
            (payment_id,)
        )

        conn.execute(
            'DELETE FROM payment_members WHERE payment_id=?',
            (payment_id,)
        )

        conn.execute(
            'DELETE FROM payments WHERE id=? AND chat_id=?',
            (payment_id, chat_id)
        )

        return 'deleted'
