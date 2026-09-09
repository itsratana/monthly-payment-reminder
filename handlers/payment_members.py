from services.group_service import group_title
from aiogram import Router,F
from services.authorization import require_payment_admin
from services.payment_service import get_selected_members,assign_member,unassign_member
from database.member_repository import get_members_by_group
from handlers.ui import show,page_items
router=Router()


async def render_members(callback,payment,page=0):
    pid=payment['id'];rows,nav=page_items(get_members_by_group(payment['chat_id']),page,f'manage_members:{pid}')
    selected={r['user_id'] for r in get_selected_members(pid)}
    await show(callback,f"🏠 {group_title(payment['chat_id'])}\n👥 Manage Members • {payment['name']}\nAssignments affect current and future reminders; past records are kept."+('' if rows else '\nNo registered members yet. Use /join in the group.'),
               [(f"{'✅' if m['user_id'] in selected else '⬜'} {m['full_name'] or m['user_id']}",f"assign_member:{pid}:{m['user_id']}:{0 if m['user_id'] in selected else 1}:{page}") for m in rows]+nav+[('⬅️ Back',f'payment:{pid}')])


@router.callback_query(F.data.startswith('manage_members:'))
async def manage_members(callback):
    parts=callback.data.split(':');p=await require_payment_admin(callback.bot,callback.from_user.id,int(parts[1]))
    await callback.answer();await render_members(callback,p,int(parts[2]) if len(parts)>2 else 0)


@router.callback_query(F.data.startswith('assign_member:'))
async def assignment(callback):
    _,pid,uid,desired,page=callback.data.split(':');pid,uid,page=int(pid),int(uid),int(page)
    if desired not in ('0','1'): raise ValueError('Invalid assignment')
    p=await require_payment_admin(callback.bot,callback.from_user.id,pid)
    (assign_member if desired=='1' else unassign_member)(pid,uid)
    await callback.answer('Assignment saved');await render_members(callback,p,page)


@router.callback_query(F.data.startswith('toggle_member:'))
async def old_toggle(callback):
    await callback.answer('This old control expired. Open Manage Members again.',show_alert=True)
