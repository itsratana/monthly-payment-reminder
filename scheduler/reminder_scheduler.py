"""Single-owner scheduler adapter with durable, bounded delivery attempts."""
import asyncio
import logging
from datetime import datetime
from zoneinfo import ZoneInfo
from aiogram.exceptions import TelegramBadRequest,TelegramForbiddenError,TelegramRetryAfter
import config
from database.reminder_dispatch_repository import record_dispatch,claim_attempt,finish_attempt,record_message
from database.payment_repository import get_payment
from keyboards.reminder import paid_keyboard
from services.reminder_service import get_eligible_reminders
logger=logging.getLogger(__name__)
_tick_lock=asyncio.Lock()


async def run_reminder_tick(bot):
    if _tick_lock.locked(): return
    async with _tick_lock:
        now=datetime.now(ZoneInfo(config.APP_TIMEZONE))
        failures=0
        try:
            reminders=get_eligible_reminders(now)
            for reminder in reminders:
                from services.payment_locks import payment_lock
                async with payment_lock(reminder.payment_id):
                    sent_any=False
                    try:
                        payment=get_payment(reminder.payment_id)
                        if not payment or not payment['active']: continue
                        from services.reminder_service import _eligible_payment
                        reminder = _eligible_payment(payment, now)
                        if reminder is None: continue
                        if not claim_attempt(reminder.payment_id,reminder.local_date,now.timestamp()): continue
                        for text in (reminder.text,*reminder.additional_texts):
                            message=await bot.send_message(reminder.chat_id,text,parse_mode='HTML',
                                reply_markup=paid_keyboard(reminder.payment_id,reminder.year,reminder.month))
                            sent_any=True
                            record_message(reminder,message.message_id)
                        record_dispatch(reminder.payment_id,reminder.year,reminder.month,reminder.local_date,reminder.chat_id,message.message_id)
                        finish_attempt(reminder.payment_id,reminder.local_date,'sent')
                        logger.info('Reminder sent payment=%s group=%s date=%s',reminder.payment_id,reminder.chat_id,reminder.local_date)
                    except asyncio.CancelledError:
                        # A durable reserved attempt is deliberately not blindly retried.
                        raise
                    except (TelegramBadRequest,TelegramForbiddenError,TelegramRetryAfter) as error:
                        failures+=1
                        delay=getattr(error,'retry_after',300)
                        finish_attempt(reminder.payment_id,reminder.local_date,'uncertain' if sent_any else 'failed',now.timestamp()+delay)
                        logger.warning('Reminder rejected payment=%s type=%s',reminder.payment_id,type(error).__name__)
                    except Exception:
                        failures+=1
                        # Telegram may have accepted a send before the connection failed.
                        finish_attempt(reminder.payment_id,reminder.local_date,'uncertain')
                        logger.exception('Uncertain reminder delivery payment=%s; inspect before reconciliation',reminder.payment_id)
        except Exception:
            failures += 1
            logger.exception('Scheduler tick failed')
            raise
        finally:
            from services.health_service import scheduler_heartbeat
            scheduler_heartbeat(failures)
