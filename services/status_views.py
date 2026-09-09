from database.payment_repository import get_payments
from database.payment_status_repository import cycle_members, history_payments
from services.settings_service import group_now
from services.payment_status_service import initialize_monthly_status_for_payment
from utils.dates import effective_due_day


def current_payments(chat_id):
    now=group_now(chat_id)
    results=[]
    for p in get_payments(chat_id):
        if p['active']: initialize_monthly_status_for_payment(p['id'],now.year,now.month)
        rows=cycle_members(p['id'],now.year,now.month,current=True)
        label='Disabled' if not p['active'] else ('Not yet due' if now.day<effective_due_day(now.year,now.month,p['due_day']) else 'Current')
        results.append((p,rows,label))
    return now,results


def member_payments(chat_id,user_id):
    now=group_now(chat_id)
    results=[]
    for p in get_payments(chat_id):
        rows=cycle_members(p['id'],now.year,now.month,current=True)
        for row in rows:
            if row['user_id']==user_id: results.append((p,row))
    return now,results
