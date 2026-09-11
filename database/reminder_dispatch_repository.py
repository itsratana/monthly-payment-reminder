import sqlite3

from .connection import db_connection


# ---------------------------------------------------------------------------
# Legacy daily reminder functions
#
# Keep these temporarily because the current scheduler/message service still
# calls them. We will switch the scheduler to the new slot-aware functions
# in the next step.
# ---------------------------------------------------------------------------

def was_dispatched(payment_id: int, local_date: str) -> bool:
    with db_connection() as conn:
        row = conn.execute("""
            SELECT 1
            FROM reminder_dispatches
            WHERE payment_id = ?
              AND local_date = ?
        """, (
            payment_id,
            local_date
        )).fetchone()

        return row is not None


def record_dispatch(
    payment_id: int,
    year: int,
    month: int,
    local_date: str,
    chat_id: int,
    message_id: int | None,
) -> bool:
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
            """, (
                payment_id,
                year,
                month,
                local_date,
                chat_id,
                message_id
            ))

        return True

    except sqlite3.IntegrityError:
        return False


def claim_attempt(
    payment_id: int,
    local_date: str,
    now: float
) -> bool:
    with db_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")

        already_sent = conn.execute("""
            SELECT 1
            FROM reminder_dispatches
            WHERE payment_id = ?
              AND local_date = ?
        """, (
            payment_id,
            local_date
        )).fetchone()

        if already_sent:
            return False

        row = conn.execute("""
            SELECT *
            FROM reminder_attempts
            WHERE payment_id = ?
              AND local_date = ?
        """, (
            payment_id,
            local_date
        )).fetchone()

        if row:
            if (
                row["state"] != "failed"
                or row["attempts"] >= 3
                or row["retry_after"] > now
            ):
                return False

            conn.execute("""
                UPDATE reminder_attempts
                SET state = 'reserved',
                    attempts = attempts + 1,
                    updated_at = CURRENT_TIMESTAMP
                WHERE payment_id = ?
                  AND local_date = ?
            """, (
                payment_id,
                local_date
            ))

        else:
            conn.execute("""
                INSERT INTO reminder_attempts (
                    payment_id,
                    local_date,
                    state
                )
                VALUES (?, ?, 'reserved')
            """, (
                payment_id,
                local_date
            ))

        return True


def finish_attempt(
    payment_id: int,
    local_date: str,
    state: str,
    retry_after: float = 0
):
    if state not in {
        "sent",
        "failed",
        "uncertain"
    }:
        raise ValueError("Invalid delivery state")

    with db_connection() as conn:
        conn.execute("""
            UPDATE reminder_attempts
            SET state = ?,
                retry_after = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE payment_id = ?
              AND local_date = ?
        """, (
            state,
            retry_after,
            payment_id,
            local_date
        ))


# ---------------------------------------------------------------------------
# New multi-time automatic reminder functions
# ---------------------------------------------------------------------------

def was_slot_dispatched(
    payment_id: int,
    local_date: str,
    reminder_time: str
) -> bool:
    """
    True only if this exact automatic reminder slot was already sent.

    Example:
        09:00 sent -> True for 09:00
        18:00      -> still False
    """

    with db_connection() as conn:
        row = conn.execute("""
            SELECT 1
            FROM reminder_slot_dispatches
            WHERE payment_id = ?
              AND local_date = ?
              AND reminder_time = ?
        """, (
            payment_id,
            local_date,
            reminder_time
        )).fetchone()

        return row is not None


def record_slot_dispatch(
    payment_id: int,
    year: int,
    month: int,
    local_date: str,
    reminder_time: str,
    chat_id: int,
    message_id: int | None,
) -> bool:
    """
    Record one automatic reminder slot.

    Duplicate:
        payment 1
        2026-09-15
        09:00

    is rejected, while 18:00 on the same day is allowed.
    """

    try:
        with db_connection() as conn:
            conn.execute("""
                INSERT INTO reminder_slot_dispatches (
                    payment_id,
                    year,
                    month,
                    local_date,
                    reminder_time,
                    chat_id,
                    message_id
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                payment_id,
                year,
                month,
                local_date,
                reminder_time,
                chat_id,
                message_id
            ))

        return True

    except sqlite3.IntegrityError:
        return False


def claim_slot_attempt(
    payment_id: int,
    local_date: str,
    reminder_time: str,
    now: float
) -> bool:
    """
    Reserve one automatic reminder slot before sending.

    Prevents two scheduler ticks from sending the same slot
    at the same time.
    """

    with db_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")

        already_sent = conn.execute("""
            SELECT 1
            FROM reminder_slot_dispatches
            WHERE payment_id = ?
              AND local_date = ?
              AND reminder_time = ?
        """, (
            payment_id,
            local_date,
            reminder_time
        )).fetchone()

        if already_sent:
            return False

        row = conn.execute("""
            SELECT *
            FROM reminder_slot_attempts
            WHERE payment_id = ?
              AND local_date = ?
              AND reminder_time = ?
        """, (
            payment_id,
            local_date,
            reminder_time
        )).fetchone()

        if row:
            if (
                row["state"] != "failed"
                or row["attempts"] >= 3
                or row["retry_after"] > now
            ):
                return False

            conn.execute("""
                UPDATE reminder_slot_attempts
                SET state = 'reserved',
                    attempts = attempts + 1,
                    updated_at = CURRENT_TIMESTAMP
                WHERE payment_id = ?
                  AND local_date = ?
                  AND reminder_time = ?
            """, (
                payment_id,
                local_date,
                reminder_time
            ))

        else:
            conn.execute("""
                INSERT INTO reminder_slot_attempts (
                    payment_id,
                    local_date,
                    reminder_time,
                    state
                )
                VALUES (?, ?, ?, 'reserved')
            """, (
                payment_id,
                local_date,
                reminder_time
            ))

        return True


def finish_slot_attempt(
    payment_id: int,
    local_date: str,
    reminder_time: str,
    state: str,
    retry_after: float = 0
):
    if state not in {
        "sent",
        "failed",
        "uncertain"
    }:
        raise ValueError("Invalid delivery state")

    with db_connection() as conn:
        conn.execute("""
            UPDATE reminder_slot_attempts
            SET state = ?,
                retry_after = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE payment_id = ?
              AND local_date = ?
              AND reminder_time = ?
        """, (
            state,
            retry_after,
            payment_id,
            local_date,
            reminder_time
        ))


# ---------------------------------------------------------------------------
# Reminder message tracking
# ---------------------------------------------------------------------------

def record_message(reminder, message_id: int):
    """
    Legacy message storage.

    Kept temporarily while the old scheduler still exists.
    """

    with db_connection() as conn:
        conn.execute("""
            INSERT OR IGNORE INTO reminder_messages
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            reminder.payment_id,
            reminder.year,
            reminder.month,
            reminder.local_date,
            reminder.chat_id,
            message_id
        ))


def record_message_batch(
    reminder,
    message_id: int,
    batch_key: str
):
    """
    Store a message belonging to one reminder send.

    Automatic examples:
        auto:09:00
        auto:18:00

    Manual example:
        manual:20260911T154500123456

    Manual reminders therefore never interfere with automatic
    reminder duplicate protection.
    """

    with db_connection() as conn:
        conn.execute("""
            INSERT OR IGNORE INTO reminder_message_batches (
                payment_id,
                year,
                month,
                local_date,
                batch_key,
                chat_id,
                message_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            reminder.payment_id,
            reminder.year,
            reminder.month,
            reminder.local_date,
            batch_key,
            reminder.chat_id,
            message_id
        ))


# ---------------------------------------------------------------------------
# Message retrieval used when someone presses "I've Paid"
# ---------------------------------------------------------------------------

def cycle_dispatches(
    payment_id: int,
    year: int,
    month: int
):
    with db_connection() as conn:
        return conn.execute("""
            SELECT *
            FROM reminder_dispatches
            WHERE payment_id = ?
              AND year = ?
              AND month = ?
              AND message_id IS NOT NULL
            ORDER BY local_date DESC
        """, (
            payment_id,
            year,
            month
        )).fetchall()


def latest_messages(
    payment_id: int,
    year: int,
    month: int
):
    """
    Return every Telegram message belonging to the most recent
    reminder batch.

    Prefer the new multi-time/manual batch table.

    Fall back to legacy tables so old reminder messages continue
    working after deployment.
    """

    with db_connection() as conn:
        latest_batch = conn.execute("""
            SELECT batch_key
            FROM reminder_message_batches
            WHERE payment_id = ?
              AND year = ?
              AND month = ?
            ORDER BY sent_at DESC,
                     message_id DESC
            LIMIT 1
        """, (
            payment_id,
            year,
            month
        )).fetchone()

        if latest_batch:
            rows = conn.execute("""
                SELECT *
                FROM reminder_message_batches
                WHERE payment_id = ?
                  AND year = ?
                  AND month = ?
                  AND batch_key = ?
                ORDER BY message_id
            """, (
                payment_id,
                year,
                month,
                latest_batch["batch_key"]
            )).fetchall()

            if rows:
                return rows

        # Legacy fallback.
        rows = conn.execute("""
            SELECT *
            FROM reminder_messages
            WHERE payment_id = ?
              AND year = ?
              AND month = ?
              AND local_date = (
                    SELECT MAX(local_date)
                    FROM reminder_messages
                    WHERE payment_id = ?
                      AND year = ?
                      AND month = ?
              )
            ORDER BY message_id
        """, (
            payment_id,
            year,
            month,
            payment_id,
            year,
            month
        )).fetchall()

    if rows:
        return rows

    return cycle_dispatches(
        payment_id,
        year,
        month
    )[:1]