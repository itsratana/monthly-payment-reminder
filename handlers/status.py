from services.group_service import group_title
from datetime import datetime
from aiogram import Router,F
from services.authorization import require_admin,require_payment_admin
from services.status_views import current_payments,member_payments
from services.payment_status_service import correct_current_status
from services.settings_service import group_now
from services.message_service import refresh_reminders
from database.member_repository import get_members_by_group,get_member
from database.payment_status_repository import cycle_members,history_payments
from handlers.ui import show,page_items

router=Router()


def name(row): return row['full_name'] or row['username'] or str(row['user_id'])


@router.callback_query(F.data.startswith('members:'))
async def members(callback):
    parts=callback.data.split(':');chat_id=int(parts[1])
    await require_admin(callback.bot,callback.from_user.id,chat_id);await callback.answer()
    rows,nav=page_items(get_members_by_group(chat_id),int(parts[2]) if len(parts)>2 else 0,f'members:{chat_id}')
    await show(callback,f'🏠 {group_title(chat_id)}\n👥 Members' if rows else 'No members yet. Post the Join button or ask members to use /join in the group.',
               [(name(m),f"member_detail:{chat_id}:{m['user_id']}") for m in rows]+nav+
               [('Post Join button',f'onboard:{chat_id}'),('⬅️ Dashboard',f'group:{chat_id}')])


@router.callback_query(F.data.startswith('member_detail:'))
async def member_detail(callback):
    parts=callback.data.split(':');chat_id,user_id=map(int,parts[1:3])
    await require_admin(callback.bot,callback.from_user.id,chat_id);await callback.answer()
    member=get_member(user_id,chat_id)
    if member is None: raise ValueError('Member no longer available.')
    now,items=member_payments(chat_id,user_id)
    rows,nav=page_items(items,int(parts[3]) if len(parts)>3 else 0,f'member_detail:{chat_id}:{user_id}')
    text=f"🏠 {group_title(chat_id)}\n👤 {name(member)}\n{now:%B %Y}\nAssigned payments:\n"+'\n'.join(f"{'✅' if r['paid'] else '⏳'} {p['name']}{' (disabled)' if not p['active'] else ''}" for p,r in rows)
    await show(callback,text if rows else text+'None yet.',nav+[('⬅️ Members',f'members:{chat_id}')])


@router.callback_query(F.data.startswith('status:'))
async def status(callback):
    parts=callback.data.split(':');chat_id=int(parts[1])
    await require_admin(callback.bot,callback.from_user.id,chat_id);await callback.answer()
    now,items=current_payments(chat_id)
    rows,nav=page_items(items,int(parts[2]) if len(parts)>2 else 0,f'status:{chat_id}')
    buttons=[]
    for p,members,label in rows:
        count=f"{sum(m['paid'] for m in members)} / {len(members)} paid" if members else 'No members assigned'
        buttons.append((f"{p['name']} • {count} • {label}",f"cycle:{p['id']}:{now.year}:{now.month}:current:0"))
    await show(callback,f'🏠 {group_title(chat_id)}\n📊 {now:%B %Y}\nCurrent assigned members. Select a payment to view Paid / Pending.' if rows else 'No payments yet.',
               buttons+nav+[('⬅️ Dashboard',f'group:{chat_id}')])


@router.callback_query(F.data.startswith('reports:'))
async def reports(callback):
    parts=callback.data.split(':');chat_id=int(parts[1])
    await require_admin(callback.bot,callback.from_user.id,chat_id);await callback.answer()
    now=group_now(chat_id)
    year,month=(map(int,parts[2:4]) if len(parts)>=4 else (now.year,now.month))
    if not 2000<=year<=9998 or not 1<=month<=12: raise ValueError('Invalid report period.')
    rows,nav=page_items(history_payments(chat_id,year,month),int(parts[4]) if len(parts)>4 else 0,f'reports:{chat_id}:{year}:{month}')
    previous=(year-1,12) if month==1 else (year,month-1)
    following=(year+1,1) if month==12 else (year,month+1)
    buttons=[(f"{p['name']} • {p['completed']}/{p['total']} recorded paid",f"cycle:{p['id']}:{year}:{month}:history:0") for p in rows]
    if year>2000 or month>1: nav.append(('◀ Previous month',f'reports:{chat_id}:{previous[0]}:{previous[1]}'))
    if (year,month)<(now.year,now.month): nav.append(('Next month ▶',f'reports:{chat_id}:{following[0]}:{following[1]}'))
    await show(callback,f'🏠 {group_title(chat_id)}\n📈 {datetime(year,month,1):%B %Y}\nRecorded cycle status; names shown are current. No historical amounts or month-end timing is inferred.'+('' if rows else '\nNo recorded history.'),
               buttons+nav+[('⬅️ Dashboard',f'group:{chat_id}')])


@router.callback_query(F.data.startswith('cycle:'))
async def cycle(callback):
    _,pid,y,m,mode,page=callback.data.split(':');pid,year,month,page=map(int,(pid,y,m,page))
    if mode not in ('current','history') or not 1<=year<=9999 or not 1<=month<=12: raise ValueError('Invalid period')
    p=await require_payment_admin(callback.bot,callback.from_user.id,pid);await callback.answer()
    now=group_now(p['chat_id'])
    if mode=='current' and (year,month)!=(now.year,now.month): raise ValueError('Screen expired. Open current Status again.')
    rows,nav=page_items(cycle_members(pid,year,month,current=mode=='current'),page,f'cycle:{pid}:{year}:{month}:{mode}')
    text=f"🏠 {group_title(p['chat_id'])}\n💳 {p['name']} • {year}-{month:02}\n"+'\n'.join(f"{'✅ Paid' if row['paid'] else '⏳ Pending'} • {name(row)}" for row in rows)
    if not rows: text+='No members assigned.' if mode=='current' else 'No recorded history.'
    buttons=[]
    if mode=='current' and p['active']:
        buttons=[(f"{'↩️ Mark Unpaid' if r['paid'] else '✅ Mark Paid'} • {name(r)}",f"correct:{pid}:{r['user_id']}:{year}:{month}:{0 if r['paid'] else 1}") for r in rows]
    await show(callback,text,buttons+nav+[('⬅️ Back',f"status:{p['chat_id']}" if mode=='current' else f"reports:{p['chat_id']}:{year}:{month}")])


@router.callback_query(F.data.startswith('correct:'))
async def correct(callback):
    _,pid,uid,y,m,paid=callback.data.split(':');pid,uid,year,month,paid=map(int,(pid,uid,y,m,paid))
    if paid not in (0,1): raise ValueError('Invalid status')
    from services.payment_locks import payment_lock
    async with payment_lock(pid):
        await require_payment_admin(callback.bot,callback.from_user.id,pid)
        changed=correct_current_status(pid,uid,year,month,paid,callback.from_user.id)
        await callback.answer('✅ Saved' if changed else 'Already recorded')
        await refresh_reminders(callback.bot,pid,year,month)
        await show(callback,'Status saved. Daily reminder protection remains in place.',[('⬅️ Status',f'cycle:{pid}:{year}:{month}:current:0')])
