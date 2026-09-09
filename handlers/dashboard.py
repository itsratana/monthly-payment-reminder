from aiogram import Router,F
from aiogram.fsm.context import FSMContext
from services.authorization import require_admin
from database.group_repository import get_all_groups
from database.settings_repository import select_group
from handlers.ui import show

router=Router()


async def render_dashboard(event,chat_id):
    group=next((g for g in get_all_groups() if g['chat_id']==chat_id),None)
    if group is None: raise ValueError('Group unavailable. Use /start.')
    await show(event,f"🏠 {group['title']}",[(label,f'{action}:{chat_id}') for label,action in [
        ('➕ Add Payment','add_payment'),('📋 Payments','payments'),('👥 Members','members'),
        ('📊 Status','status'),('📈 Reports','reports'),('⚙️ Settings','settings')]]+[('🔄 Switch Group','switch_group')])


@router.callback_query(F.data.startswith('group:'))
async def open_group(callback,state:FSMContext):
    chat_id=int(callback.data.split(':')[1])
    await require_admin(callback.bot,callback.from_user.id,chat_id)
    await state.clear();select_group(callback.from_user.id,chat_id)
    await callback.answer();await render_dashboard(callback,chat_id)
