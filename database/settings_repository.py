from .connection import db_connection


def read_settings(chat_id):
    with db_connection() as conn:
        row = conn.execute('SELECT * FROM group_settings WHERE chat_id=?',(chat_id,)).fetchone()
        return dict(row) if row else {}


def write_setting(chat_id, field, value):
    if field not in {'currency','timezone','reminder_time','reminder_policy'}:
        raise ValueError('Unknown setting')
    with db_connection() as conn:
        conn.execute('INSERT OR IGNORE INTO group_settings(chat_id) VALUES (?)',(chat_id,))
        conn.execute(f'UPDATE group_settings SET {field}=? WHERE chat_id=?',(value,chat_id))


def select_group(actor_id, chat_id):
    with db_connection() as conn:
        conn.execute('UPDATE group_admins SET selected=0 WHERE user_id=?',(actor_id,))
        conn.execute('''INSERT INTO group_admins(chat_id,user_id,selected) VALUES (?,?,1)
            ON CONFLICT(chat_id,user_id) DO UPDATE SET selected=1''',(chat_id,actor_id))


def selected_group(actor_id):
    with db_connection() as conn:
        row=conn.execute('SELECT chat_id FROM group_admins WHERE user_id=? AND selected=1',(actor_id,)).fetchone()
        return row['chat_id'] if row else None
