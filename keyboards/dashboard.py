from aiogram.utils.keyboard import InlineKeyboardBuilder


def groups_keyboard(groups):

    builder = InlineKeyboardBuilder()

    for group in groups:

        builder.button(
            text=f"🏠 {group['title']}",
            callback_data=f"group:{group['chat_id']}"
        )

    builder.adjust(1)

    return builder.as_markup()