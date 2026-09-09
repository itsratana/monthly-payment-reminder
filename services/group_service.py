import logging
logger = logging.getLogger(__name__)
from database.group_repository import get_all_groups


async def get_admin_groups(bot, user_id):

    groups = get_all_groups()

    my_groups = []

    for group in groups:

        try:
            member = await bot.get_chat_member(
                group["chat_id"],
                user_id
            )

            if member.status in ("administrator", "creator"):
                my_groups.append(group)

        except Exception as error:
            logger.warning("Group permission lookup failed group=%s type=%s", group["chat_id"], type(error).__name__)

    return my_groups

def group_title(chat_id):
    from database.group_repository import get_group
    group=get_group(chat_id)
    return group['title'] if group else str(chat_id)
