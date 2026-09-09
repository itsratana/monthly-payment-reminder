from aiogram import Router,F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from services.authorization import require_admin
from handlers.dashboard import render_dashboard
from handlers.start import choose_groups
router=Router()


async def cancel(event,state):
    data=await state.get_data();await state.clear()
    if hasattr(event,'data'): await event.answer('Canceled')
    if data.get('chat_id'):
        await require_admin(event.bot,event.from_user.id,data['chat_id'])
        await render_dashboard(event,data['chat_id'])
    else: await choose_groups(event)


@router.message(Command('cancel'))
async def cancel_command(message,state:FSMContext): await cancel(message,state)


@router.callback_query(F.data=='cancel')
async def cancel_button(callback,state:FSMContext): await cancel(callback,state)
