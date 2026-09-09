import logging

from aiogram import Router, F
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery

from keyboards.reminder import paid_keyboard
from services.reminder_service import process_paid_click, parse_paid_callback_data
from database.payment_repository import get_payment
from services.settings_service import group_now

router = Router()
logger = logging.getLogger(__name__)

_ALERT_TEXT = {
    "payment_disabled": "This payment is disabled.",
    "not_assigned": "⚠️ This button is only for members assigned to this payment.",
    "already_paid": "✅ Already recorded - you're all set.",
    "status_missing": "⚠️ This reminder is no longer valid for the current period.",
    "payment_missing": "⚠️ This payment no longer exists.",
    "invalid_period": "⚠️ This button is invalid.",
}


@router.callback_query(F.data.startswith("paid:"))
async def on_paid_click(callback: CallbackQuery):
    from services.payment_locks import payment_lock
    parsed = parse_paid_callback_data(callback.data)
    if not parsed:
        await callback.answer('Invalid payment button.', show_alert=True)
        return
    async with payment_lock(parsed[0]):
        await _paid_click(callback)


async def _paid_click(callback):
    # The actor is always the clicking user - never data supplied by the
    # client (spec 4.4). callback.data is untrusted and parsed/validated
    # inside process_paid_click.
    parsed = parse_paid_callback_data(callback.data)
    if parsed:
        payment = get_payment(parsed[0])
        if payment:
            now = group_now(payment['chat_id'])
            if callback.message.chat.id != payment['chat_id'] or (parsed[1], parsed[2]) != (now.year, now.month):
                await callback.answer('This reminder is from another group or an expired month.', show_alert=True)
                return
    result = process_paid_click(callback.data, callback.from_user.id)

    if result.status != "updated":
        # Always answer, including error paths, so Telegram clears the
        # loading spinner (spec 4.4).
        await callback.answer(
            _ALERT_TEXT.get(result.status, "⚠️ Unable to process this click."),
            show_alert=result.status in ("not_assigned", "status_missing", "payment_missing", "invalid_period"),
        )
        return

    await callback.answer("✅ Payment recorded!")

    reply_markup = (
        paid_keyboard(result.payment_id, result.year, result.month)
        if result.has_pending
        else None
    )

    try:
        await callback.message.edit_text(
            result.text,
            parse_mode="HTML",
            reply_markup=reply_markup,
        )
    except TelegramBadRequest as error:
        message = str(error).lower()

        if "message is not modified" in message:
            # Harmless - state matches what's already shown (spec 13).
            return

        # The database update already succeeded; do not revert it just
        # because the message could no longer be edited (e.g. too old,
        # deleted, or the bot lost permission). Log and move on.
        logger.warning(
            "Could not edit reminder message for payment_id=%s: %s",
            result.payment_id,
            error,
        )


    from services.message_service import refresh_reminders
    await refresh_reminders(callback.bot,result.payment_id,result.year,result.month)
