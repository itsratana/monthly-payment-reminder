from .connection import db_connection


def add_group(chat_id: int, title: str):
    with db_connection() as conn:
        conn.execute("""
            INSERT INTO groups (
                chat_id,
                title
            )
            VALUES (?, ?)
            ON CONFLICT(chat_id) DO UPDATE SET title=excluded.title
        """, (chat_id, title))


def get_all_groups():
    with db_connection() as conn:
        return conn.execute("""
            SELECT *
            FROM groups
        """).fetchall()


def get_group(chat_id: int):
    with db_connection() as conn:
        return conn.execute("""
            SELECT *
            FROM groups
            WHERE chat_id = ?
        """, (chat_id,)).fetchone()

def is_onboarding_posted(chat_id: int) -> bool:
    with db_connection() as conn:
        row = conn.execute("""
            SELECT onboarding_posted
            FROM groups
            WHERE chat_id = ?
        """, (chat_id,)).fetchone()

        return bool(row["onboarding_posted"]) if row else False

def mark_onboarding_posted(chat_id: int):
    with db_connection() as conn:
        conn.execute("""
            UPDATE groups
            SET onboarding_posted = 1
            WHERE chat_id = ?
        """, (chat_id,))