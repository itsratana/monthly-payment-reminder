"""Best-effort synchronization of already-delivered reminders."""
import logging
from aiogram.exceptions import TelegramAPIError
from database.payment_repository import get_payment
from database.reminder_dispatch_repository import latest_messages
from services.payment_status_service import get_pending_members
from services.reminder_service import build_all_paid_text,build_reminder_messages
from keyboards.reminder import paid_keyboard
logger=logging.getLogger(__name__)


async def refresh_reminders(bot,payment_id,year,month):
    payment=get_payment(payment_id)
    if not payment: return
    pending=get_pending_members(payment_id,year,month)
    texts=build_reminder_messages(payment,pending) if pending else [build_all_paid_text(payment,year,month)]
    markup=paid_keyboard(payment_id,year,month) if pending and payment['active'] else None
    # Only the latest message needs active controls; old messages are period-bound.
    rows=latest_messages(payment_id,year,month)
    for index,row in enumerate(rows):
        text=texts[index] if index<len(texts) else ("No pending members on this page. See the latest reminder." if pending else texts[0])
        if not payment['active']: text = '⏸ Payment disabled. Reminders are paused.\n\n' + text
        try:
            await bot.edit_message_text(chat_id=row['chat_id'],message_id=row['message_id'],
                                        text=text,parse_mode='HTML',reply_markup=markup)
        except TelegramAPIError as error:
            if 'message is not modified' in str(error).lower(): continue
            logger.warning('Reminder refresh failed payment=%s type=%s',payment_id,type(error).__name__)
