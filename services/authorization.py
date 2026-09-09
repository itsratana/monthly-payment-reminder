"""Fresh Telegram authorization; no persistent admin cache is trusted."""
import logging
from database.group_repository import get_all_groups
from database.payment_repository import get_payment

logger = logging.getLogger(__name__)


async def require_admin(bot, actor_id, chat_id):
    if chat_id >= 0 or not any(g['chat_id'] == chat_id for g in get_all_groups()):
        raise PermissionError('Group unavailable. Use /start to choose a group.')
    try:
        member = await bot.get_chat_member(chat_id, actor_id)
    except Exception as error:
        logger.warning('Admin verification unavailable group=%s type=%s', chat_id, type(error).__name__)
        raise PermissionError('Cannot verify group admin rights. Please try again.') from error
    if member.status not in ('administrator', 'creator'):
        logger.warning('Admin action denied group=%s actor=%s', chat_id, actor_id)
        raise PermissionError('Only a current group admin can do this.')


async def require_payment_admin(bot, actor_id, payment_id):
    payment = get_payment(payment_id)
    if payment is None:
        raise ValueError('This payment no longer exists. Use /start.')
    await require_admin(bot, actor_id, payment['chat_id'])
    return payment
