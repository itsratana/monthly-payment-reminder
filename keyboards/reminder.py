from aiogram.utils.keyboard import InlineKeyboardBuilder

from services.reminder_service import build_paid_callback_data


def paid_keyboard(payment_id: int, year: int, month: int):
    builder = InlineKeyboardBuilder()

    builder.button(
        text="✅ I've Paid",
        callback_data=build_paid_callback_data(payment_id, year, month)
    )

    return builder.as_markup()
