"""Small shared rendering primitives; all admin text uses plain text."""
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramBadRequest


def keyboard(buttons):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=str(label)[:100], callback_data=data)] for label, data in buttons
    ])


async def show(event, text, buttons=()):
    markup = keyboard(buttons)
    if hasattr(event, 'data'):
        try:
            await event.message.edit_text(text, reply_markup=markup)
        except TelegramBadRequest as error:
            if 'message is not modified' not in str(error).lower():
                await event.message.answer(text, reply_markup=markup)
    else:
        await event.answer(text, reply_markup=markup)


def page_items(items, page, prefix, size=8):
    page = max(0, min(page, max(0, (len(items)-1)//size)))
    nav = []
    if page:
        nav.append(('⬅️ Previous', f'{prefix}:{page-1}'))
    if (page+1)*size < len(items):
        nav.append(('Next ➡️', f'{prefix}:{page+1}'))
    return items[page*size:(page+1)*size], nav
