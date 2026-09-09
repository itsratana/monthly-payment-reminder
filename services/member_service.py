from database.group_repository import add_group, get_group
from database.member_repository import add_member, get_member

def register_member(user, chat):

    if chat.type not in ('group', 'supergroup'):
        raise ValueError('Use /join or the Join button inside your group.')

    title = chat.title or chat.full_name or "Private Chat"

    add_group(chat.id, title)

    add_member(
        user.id,
        chat.id,
        user.username,
        user.full_name
    )

def is_member_registered(user_id: int, chat_id: int) -> bool:
    return get_member(user_id, chat_id) is not None

def is_group_registered(chat_id: int) -> bool:
    return get_group(chat_id) is not None