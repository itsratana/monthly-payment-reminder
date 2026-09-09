from aiogram import Router,F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from services.group_service import get_admin_groups
from database.settings_repository import selected_group
from handlers.dashboard import render_dashboard
from handlers.ui import show,page_items
router=Router()


async def choose_groups(event,page=0):
    groups=await get_admin_groups(event.bot,event.from_user.id)
    rows,nav=page_items(groups,page,'switch_group')
    await show(event,'🏠 My Groups' if rows else 'No available admin groups. Add the bot to a group, run /join there, and ensure you are an admin. Then open /start privately.',
               [(g['title'],f"group:{g['chat_id']}") for g in rows]+nav)


@router.message(Command('start'))
async def start(message,state:FSMContext):
    await state.clear()
    if message.chat.type!='private':
        await message.answer('👋 Open a private chat with me and send /start to manage your groups.');return
    groups=await get_admin_groups(message.bot,message.from_user.id)
    selected=selected_group(message.from_user.id)
    if selected in {g['chat_id'] for g in groups}:
        await render_dashboard(message,selected)
    else: await choose_groups(message)


@router.callback_query(F.data.startswith('switch_group'))
async def switch_group(callback,state:FSMContext):
    await callback.answer();await state.clear()
    parts=callback.data.split(':')
    await choose_groups(callback,int(parts[1]) if len(parts)>1 else 0)
