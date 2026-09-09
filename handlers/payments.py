from services.group_service import group_title
from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from services.authorization import require_admin, require_payment_admin
from services.payment_service import get_group_payments, get_selected_members, edit_payment, set_active, delete_payment
from handlers.ui import show, page_items

router = Router()


class EditPaymentState(StatesGroup):
    value = State()


async def render_detail(event, payment):
    p = payment
    await show(event, f"🏠 {group_title(p['chat_id'])}\n💳 {p['name']}\n💰 {p['amount']:.2f} {p['currency']}\n📅 Every {p['due_day']} (short months: last day)\n⏰ {p['reminder_time']}\n👥 {len(get_selected_members(p['id']))} members\n{'🟢 Active' if p['active'] else '⏸ Disabled'}", [
        ('👥 Manage Members', f"manage_members:{p['id']}"),
        ('✏️ Edit', f"edit_payment:{p['id']}"),
        ('⏸ Disable' if p['active'] else '▶️ Reactivate', f"active_payment:{p['id']}:{0 if p['active'] else 1}"),
        ('🗑 Delete', f"delete_payment:{p['id']}"),
        ('⬅️ Back', f"payments:{p['chat_id']}")])


@router.callback_query(F.data.startswith('payments:'))
async def payments(callback):
    parts = callback.data.split(':'); chat_id = int(parts[1])
    await require_admin(callback.bot, callback.from_user.id, chat_id)
    await callback.answer()
    rows, nav = page_items(get_group_payments(chat_id), int(parts[2]) if len(parts)>2 else 0, f'payments:{chat_id}')
    await show(callback, f'🏠 {group_title(chat_id)}\n📋 Payments' if rows else f'🏠 {group_title(chat_id)}\n📭 No payments. Create one to get started.',
               [(f"{'🟢' if p['active'] else '⏸'} {p['name']} • {p['amount']:.2f} {p['currency']} • Due {p['due_day']}", f"payment:{p['id']}") for p in rows]
               + nav + [('➕ Add Payment', f'add_payment:{chat_id}'), ('⬅️ Dashboard', f'group:{chat_id}')])


@router.callback_query(F.data.startswith('payment:'))
async def payment_detail(callback):
    p = await require_payment_admin(callback.bot, callback.from_user.id, int(callback.data.split(':')[1]))
    await callback.answer()
    await render_detail(callback, p)


@router.callback_query(F.data.startswith('edit_payment:'))
async def edit_menu(callback, state: FSMContext):
    p = await require_payment_admin(callback.bot, callback.from_user.id, int(callback.data.split(':')[1]))
    await state.clear()
    await callback.answer()
    await show(callback, f"✏️ Edit {p['name']}\nChanges affect future evaluations; paid status and past history remain unchanged.",
               [(label, f"edit_field:{p['id']}:{field}") for field,label in [('name','📝 Name'),('amount','💰 Amount'),('currency','💵 Currency'),('due_day','📅 Due Day'),('reminder_time','⏰ Reminder Time')]]
               + [('⬅️ Back', f"payment:{p['id']}")])


@router.callback_query(F.data.startswith('edit_field:'))
async def edit_field(callback, state: FSMContext):
    _, raw, field = callback.data.split(':')
    if field not in {'name','amount','currency','due_day','reminder_time'}: raise ValueError('Unknown field')
    p = await require_payment_admin(callback.bot, callback.from_user.id, int(raw))
    await callback.answer()
    await state.set_state(EditPaymentState.value)
    await state.set_data({'chat_id':p['chat_id'], 'payment_id':p['id'], 'field':field})
    await show(callback, f"Current {field.replace('_',' ')}: {p[field]}\nEnter the new value.",
               [('⬅️ Back',f"edit_payment:{p['id']}"),('❌ Cancel','cancel')])


@router.message(EditPaymentState.value)
async def edit_value(message, state: FSMContext):
    data = await state.get_data()
    p = await require_payment_admin(message.bot, message.from_user.id, data['payment_id'])
    if not message.text or message.text.startswith('/'):
        await show(message, 'Enter a value or use /cancel.', [('❌ Cancel','cancel')]); return
    edit_payment(p['id'], p['chat_id'], data['field'], message.text)
    await state.clear()
    from database.payment_repository import get_payment
    await message.answer('✅ Payment updated. Existing daily reminder protection is preserved.')
    await render_detail(message, get_payment(p['id']))


@router.callback_query(F.data.startswith('active_payment:'))
async def active_payment(callback):
    _, raw, active = callback.data.split(':')
    if active not in ('0','1'): raise ValueError('Invalid action')
    p = await require_payment_admin(callback.bot, callback.from_user.id, int(raw))
    set_active(p['id'], p['chat_id'], active=='1')
    await callback.answer('Reactivated' if active=='1' else 'Disabled')
    from services.settings_service import group_now
    from services.message_service import refresh_reminders
    now=group_now(p['chat_id'])
    await refresh_reminders(callback.bot,p['id'],now.year,now.month)
    from database.payment_repository import get_payment
    await render_detail(callback, get_payment(p['id']))


@router.callback_query(F.data.startswith('delete_payment:'))
async def delete_prompt(callback):
    p = await require_payment_admin(
        callback.bot,
        callback.from_user.id,
        int(callback.data.split(':')[1])
    )

    await callback.answer()

    await show(
        callback,
        f"⚠️ Permanently delete {p['name']}?\n\n"
        "This will permanently delete:\n"
        "• the payment\n"
        "• assigned members for this payment\n"
        "• all payment history\n"
        "• all reminder history\n\n"
        "This cannot be undone.",
        [
            ('🗑 Delete Everything', f"confirm_delete:{p['id']}"),
            ('Cancel', f"payment:{p['id']}")
        ]
    )

@router.callback_query(F.data.startswith('confirm_delete:'))
async def confirm_delete(callback):
    p = await require_payment_admin(
        callback.bot,
        callback.from_user.id,
        int(callback.data.split(':')[1])
    )

    result = delete_payment(p['id'], p['chat_id'])

    await callback.answer()

    if result == 'missing':
        await show(
            callback,
            'Payment no longer exists.',
            [('⬅️ Payments', f"payments:{p['chat_id']}")]
        )
        return

    await show(
        callback,
        '✅ Payment and all history deleted.',
        [('⬅️ Payments', f"payments:{p['chat_id']}")]
    )
