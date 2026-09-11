"""Single-owner scheduler adapter with durable, bounded delivery attempts."""

import asyncio
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramRetryAfter,
)

import config

from database.payment_repository import get_payment

from database.reminder_dispatch_repository import (
    claim_slot_attempt,
    finish_slot_attempt,
    record_slot_dispatch,
    record_message_batch,
)

from keyboards.reminder import paid_keyboard

from services.reminder_service import (
    get_eligible_reminders,
)

logger = logging.getLogger(__name__)

_tick_lock = asyncio.Lock()


async def run_reminder_tick(bot):
    if _tick_lock.locked():
        return

    async with _tick_lock:
        now = datetime.now(
            ZoneInfo(config.APP_TIMEZONE)
        )

        failures = 0

        try:
            reminders = get_eligible_reminders(
                now
            )

            for reminder in reminders:
                from services.payment_locks import payment_lock

                async with payment_lock(
                    reminder.payment_id
                ):
                    sent_any = False

                    try:
                        # -------------------------------------------------
                        # Re-check payment before delivery
                        # -------------------------------------------------

                        payment = get_payment(
                            reminder.payment_id
                        )

                        if (
                            not payment
                            or not payment["active"]
                        ):
                            continue

                        # Re-evaluate after acquiring the payment lock.
                        # This prevents stale scheduler results from sending.
                        from services.reminder_service import _eligible_payment

                        reminder = _eligible_payment(
                            payment,
                            now
                        )

                        if reminder is None:
                            continue

                        # -------------------------------------------------
                        # Claim this exact automatic time slot
                        # -------------------------------------------------

                        claimed = claim_slot_attempt(
                            reminder.payment_id,
                            reminder.local_date,
                            reminder.reminder_time,
                            now.timestamp(),
                        )

                        if not claimed:
                            continue

                        # All Telegram messages created by this automatic
                        # reminder belong to one batch.
                        batch_key = (
                            f"auto:"
                            f"{reminder.reminder_time}"
                        )

                        last_message_id = None

                        # -------------------------------------------------
                        # Send reminder message(s)
                        # -------------------------------------------------

                        for text in (
                            reminder.text,
                            *reminder.additional_texts,
                        ):
                            message = await bot.send_message(
                                reminder.chat_id,
                                text,
                                parse_mode="HTML",
                                reply_markup=paid_keyboard(
                                    reminder.payment_id,
                                    reminder.year,
                                    reminder.month,
                                ),
                            )

                            sent_any = True

                            last_message_id = (
                                message.message_id
                            )

                            record_message_batch(
                                reminder,
                                message.message_id,
                                batch_key,
                            )

                        # -------------------------------------------------
                        # Mark slot as successfully delivered
                        # -------------------------------------------------

                        record_slot_dispatch(
                            payment_id=reminder.payment_id,
                            year=reminder.year,
                            month=reminder.month,
                            local_date=reminder.local_date,
                            reminder_time=reminder.reminder_time,
                            chat_id=reminder.chat_id,
                            message_id=last_message_id,
                        )

                        finish_slot_attempt(
                            reminder.payment_id,
                            reminder.local_date,
                            reminder.reminder_time,
                            "sent",
                        )

                        logger.info(
                            (
                                "Reminder sent "
                                "payment=%s "
                                "group=%s "
                                "date=%s "
                                "time=%s"
                            ),
                            reminder.payment_id,
                            reminder.chat_id,
                            reminder.local_date,
                            reminder.reminder_time,
                        )

                    except asyncio.CancelledError:
                        # A durable reserved attempt is deliberately
                        # not blindly retried.
                        raise

                    except (
                        TelegramBadRequest,
                        TelegramForbiddenError,
                        TelegramRetryAfter,
                    ) as error:
                        failures += 1

                        delay = getattr(
                            error,
                            "retry_after",
                            300,
                        )

                        finish_slot_attempt(
                            reminder.payment_id,
                            reminder.local_date,
                            reminder.reminder_time,
                            (
                                "uncertain"
                                if sent_any
                                else "failed"
                            ),
                            now.timestamp() + delay,
                        )

                        logger.warning(
                            (
                                "Reminder rejected "
                                "payment=%s "
                                "time=%s "
                                "type=%s"
                            ),
                            reminder.payment_id,
                            reminder.reminder_time,
                            type(error).__name__,
                        )

                    except Exception:
                        failures += 1

                        # Telegram may have accepted a send before
                        # the network request failed.
                        finish_slot_attempt(
                            reminder.payment_id,
                            reminder.local_date,
                            reminder.reminder_time,
                            "uncertain",
                        )

                        logger.exception(
                            (
                                "Uncertain reminder delivery "
                                "payment=%s "
                                "time=%s; "
                                "inspect before reconciliation"
                            ),
                            reminder.payment_id,
                            reminder.reminder_time,
                        )

        except Exception:
            failures += 1

            logger.exception(
                "Scheduler tick failed"
            )

            raise

        finally:
            from services.health_service import scheduler_heartbeat

            scheduler_heartbeat(
                failures
            )