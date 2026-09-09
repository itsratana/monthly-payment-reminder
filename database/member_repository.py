from .connection import db_connection


def add_member(user_id, chat_id, username, full_name):
    with db_connection() as conn:
        conn.execute("""
            INSERT INTO members(
                user_id,
                chat_id,
                username,
                full_name
            )
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id, chat_id) DO UPDATE SET username=excluded.username, full_name=excluded.full_name
        """, (
            user_id,
            chat_id,
            username,
            full_name
        ))


def get_members_by_group(chat_id: int):
    with db_connection() as conn:
        return conn.execute("""
            SELECT *
            FROM members
            WHERE chat_id = ?
            ORDER BY full_name
        """, (chat_id,)).fetchall()


def get_member(user_id: int, chat_id: int):
    with db_connection() as conn:
        return conn.execute("""
            SELECT *
            FROM members
            WHERE user_id = ?
              AND chat_id = ?
        """, (user_id, chat_id)).fetchone()
