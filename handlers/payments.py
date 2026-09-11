from services.group_service import group_title
from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from services.authorization import require_admin, require_payment_admin
from services.payment_service import (
    get_group_payments,
    get_selected_members,
    edit_payment,
    set_active,
    delete_payment,
    get_reminder_times,
    add_reminder_time,
    remove_reminder_time,
)
from handlers.ui import show, page_items
from datetime import datetime

from services.settings_service import group_now
from services.payment_status_service import (
    initialize_monthly_status_for_payment,
    get_pending_members,
)
from services.reminder_service import (
    ReminderToSend,
    build_reminder_messages,
)
from database.reminder_dispatch_repository import record_message_batch
from keyboards.reminder import paid_keyboard

router = Router()


class EditPaymentState(StatesGroup):
    value = State()

class AddReminderTimeState(StatesGroup):
    value = State()


async def render_detail(event, payment):
    p = payment

    reminder_times = get_reminder_times(p['id'])

    if reminder_times:
        reminder_text = ", ".join(reminder_times)
    else:
        reminder_text = p['reminder_time']

    await show(
        event,
        f"🏠 {group_title(p['chat_id'])}\n"
        f"💳 {p['name']}\n"
        f"💰 {p['amount']:.2f} {p['currency']}\n"
        f"📅 Every {p['due_day']} (short months: last day)\n"
        f"🔔 Reminders: {reminder_text}\n"
        f"👥 {len(get_selected_members(p['id']))} members\n"
        f"{'🟢 Active' if p['active'] else '⏸ Disabled'}",
        [
            ('🔔 Reminder Schedule', f"reminder_times:{p['id']}"),
            ('📊 Status', f"payment_status_view:{p['id']}"),
            ('📢 Send Reminder Now', f"manual_reminder:{p['id']}"),
            ('👥 Manage Members', f"manage_members:{p['id']}"),
            ('✏️ Edit', f"edit_payment:{p['id']}"),
            (
                '⏸ Disable' if p['active'] else '▶️ Reactivate',
                f"active_payment:{p['id']}:{0 if p['active'] else 1}"
            ),
            ('🗑 Delete', f"delete_payment:{p['id']}"),
            ('⬅️ Back', f"payments:{p['chat_id']}")
        ]
    )


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

@router.callback_query(F.data.startswith('manual_reminder:'))
async def manual_reminder_prompt(callback):
    payment_id = int(
        callback.data.split(':')[1]
    )

    p = await require_payment_admin(
        callback.bot,
        callback.from_user.id,
        payment_id
    )

    now = group_now(
        p['chat_id']
    )

    # Manual reminder uses the current payment period.
    initialize_monthly_status_for_payment(
        payment_id,
        now.year,
        now.month
    )

    pending = get_pending_members(
        payment_id,
        now.year,
        now.month
    )

    if not pending:
        await callback.answer(
            'Everyone has already paid for this month.',
            show_alert=True
        )
        return

    await callback.answer()

    period = datetime(
        now.year,
        now.month,
        1
    ).strftime('%B %Y')

    await show(
        callback,
        f"📢 Send Reminder Now\n\n"
        f"💳 {p['name']}\n"
        f"📅 Payment for: {period}\n"
        f"⏳ {len(pending)} member"
        f"{'s' if len(pending) != 1 else ''} still unpaid.\n\n"
        f"Send a reminder to the group now?",
        [
            (
                '📢 Send Now',
                f"confirm_manual_reminder:{payment_id}"
            ),
            (
                '❌ Cancel',
                f"payment:{payment_id}"
            ),
        ]
    )


@router.callback_query(F.data.startswith('confirm_manual_reminder:'))
async def manual_reminder_send(callback):
    payment_id = int(
        callback.data.split(':')[1]
    )

    p = await require_payment_admin(
        callback.bot,
        callback.from_user.id,
        payment_id
    )

    now = group_now(
        p['chat_id']
    )

    initialize_monthly_status_for_payment(
        payment_id,
        now.year,
        now.month
    )

    pending = get_pending_members(
        payment_id,
        now.year,
        now.month
    )

    # Re-check after confirmation in case someone paid
    # while the confirmation screen was open.
    if not pending:
        await callback.answer(
            'Everyone has already paid for this month.',
            show_alert=True
        )

        await render_detail(
            callback,
            p
        )

        return

    await callback.answer(
        'Sending reminder...'
    )

    texts = build_reminder_messages(
        p,
        pending,
        now.year,
        now.month
    )

    local_date = now.strftime(
        '%Y-%m-%d'
    )

    # Unique key every time.
    #
    # Manual reminders therefore never consume an
    # automatic reminder slot.
    batch_key = (
        'manual:'
        + now.strftime(
            '%Y%m%dT%H%M%S%f'
        )
    )

    reminder = ReminderToSend(
        payment_id=payment_id,
        chat_id=p['chat_id'],
        year=now.year,
        month=now.month,
        local_date=local_date,
        reminder_time='manual',
        text=texts[0],
        additional_texts=tuple(
            texts[1:]
        ),
    )

    try:
        for text in texts:
            message = await callback.bot.send_message(
                p['chat_id'],
                text,
                parse_mode='HTML',
                reply_markup=paid_keyboard(
                    payment_id,
                    now.year,
                    now.month
                )
            )

            record_message_batch(
                reminder,
                message.message_id,
                batch_key
            )

    except Exception:
        await callback.message.answer(
            '❌ Failed to send the reminder to the group.'
        )
        raise

    period = datetime(
        now.year,
        now.month,
        1
    ).strftime('%B %Y')

    await show(
        callback,
        f"✅ Reminder sent.\n\n"
        f"💳 {p['name']}\n"
        f"📅 Payment for: {period}\n"
        f"👥 {len(pending)} unpaid member"
        f"{'s' if len(pending) != 1 else ''} mentioned.",
        [
            (
                '⬅️ Back',
                f"payment:{payment_id}"
            )
        ]
    )

@router.callback_query(F.data.startswith('reminder_times:'))
async def reminder_times(callback):
    payment_id = int(callback.data.split(':')[1])

    p = await require_payment_admin(
        callback.bot,
        callback.from_user.id,
        payment_id
    )

    await callback.answer()

    times = get_reminder_times(payment_id)

    if times:
        lines = [
            f"• {time}"
            for time in times
        ]

        schedule_text = "\n".join(lines)
    else:
        schedule_text = "No reminder times configured."

    buttons = []

    if len(times) < 3:
        buttons.append(
            ('➕ Add Time', f'add_reminder_time:{payment_id}')
        )

    if len(times) > 1:
        buttons.append(
            ('🗑 Remove Time', f'remove_reminder_time:{payment_id}')
        )

    buttons.append(
        ('⬅️ Back', f'payment:{payment_id}')
    )

    await show(
        callback,
        f"🔔 Reminder Schedule\n\n"
        f"{schedule_text}\n\n"
        f"Maximum: 3 reminders per day.",
        buttons
    )

@router.callback_query(F.data.startswith('add_reminder_time:'))
async def add_reminder_time_prompt(callback, state: FSMContext):
    payment_id = int(callback.data.split(':')[1])

    await require_payment_admin(
        callback.bot,
        callback.from_user.id,
        payment_id
    )

    times = get_reminder_times(payment_id)

    if len(times) >= 3:
        await callback.answer(
            'Maximum 3 reminder times.',
            show_alert=True
        )
        return

    await callback.answer()

    await state.set_state(
        AddReminderTimeState.value
    )

    await state.set_data({
        'payment_id': payment_id
    })

    await show(
        callback,
        "➕ Add Reminder Time\n\n"
        "Enter a time using HH:MM.\n\n"
        "Examples:\n"
        "09:00\n"
        "13:30\n"
        "18:00",
        [
            ('❌ Cancel', f'reminder_times:{payment_id}')
        ]
    )

@router.message(AddReminderTimeState.value)
async def add_reminder_time_value(message, state: FSMContext):
    data = await state.get_data()

    payment_id = data['payment_id']

    await require_payment_admin(
        message.bot,
        message.from_user.id,
        payment_id
    )

    if not message.text or message.text.startswith('/'):
        await message.answer(
            'Enter a time such as 09:00 or use /cancel.'
        )
        return

    try:
        result = add_reminder_time(
            payment_id,
            message.text
        )

    except ValueError as exc:
        await message.answer(str(exc))
        return

    if result == 'exists':
        await message.answer(
            '⚠️ That reminder time already exists.'
        )
        return

    if result == 'limit':
        await state.clear()

        await message.answer(
            '⚠️ Maximum 3 reminder times per payment.'
        )
        return

    if result == 'missing':
        await state.clear()

        await message.answer(
            '⚠️ Payment no longer exists.'
        )
        return

    await state.clear()

    await message.answer(
        f'✅ Reminder time {message.text} added.'
    )

    from database.payment_repository import get_payment

    await render_detail(
        message,
        get_payment(payment_id)
    )

@router.callback_query(F.data.startswith('remove_reminder_time:'))
async def remove_reminder_time_menu(callback):
    payment_id = int(callback.data.split(':')[1])

    await require_payment_admin(
        callback.bot,
        callback.from_user.id,
        payment_id
    )

    await callback.answer()

    times = get_reminder_times(payment_id)

    if len(times) <= 1:
        await show(
            callback,
            "⚠️ A payment must keep at least one reminder time.",
            [
                ('⬅️ Back', f'reminder_times:{payment_id}')
            ]
        )
        return

    buttons = [
        (
            f'🗑 {time}',
            f'delete_reminder_time:{payment_id}:{time}'
        )
        for time in times
    ]

    buttons.append(
        ('⬅️ Back', f'reminder_times:{payment_id}')
    )

    await show(
        callback,
        "🗑 Remove Reminder Time\n\n"
        "Choose the time you want to remove.",
        buttons
    )

@router.callback_query(F.data.startswith('delete_reminder_time:'))
async def delete_reminder_time(callback):
    _, payment_id, reminder_time = callback.data.split(':', 2)

    payment_id = int(payment_id)

    await require_payment_admin(
        callback.bot,
        callback.from_user.id,
        payment_id
    )

    result = remove_reminder_time(
        payment_id,
        reminder_time
    )

    if result == 'last':
        await callback.answer(
            'You must keep at least one reminder time.',
            show_alert=True
        )
        return

    if result == 'missing':
        await callback.answer(
            'Reminder time not found.',
            show_alert=True
        )
        return

    await callback.answer(
        f'{reminder_time} removed.'
    )

    times = get_reminder_times(payment_id)

    schedule_text = "\n".join(
        f"• {time}"
        for time in times
    )

    buttons = []

    if len(times) < 3:
        buttons.append(
            ('➕ Add Time', f'add_reminder_time:{payment_id}')
        )

    if len(times) > 1:
        buttons.append(
            ('🗑 Remove Time', f'remove_reminder_time:{payment_id}')
        )

    buttons.append(
        ('⬅️ Back', f'payment:{payment_id}')
    )

    await show(
        callback,
        f"🔔 Reminder Schedule\n\n"
        f"{schedule_text}\n\n"
        f"Maximum: 3 reminders per day.",
        buttons
    )


@router.callback_query(F.data.startswith('edit_payment:'))
async def edit_menu(callback, state: FSMContext):
    p = await require_payment_admin(
        callback.bot,
        callback.from_user.id,
        int(callback.data.split(':')[1])
    )

    await state.clear()
    await callback.answer()

    await show(
        callback,
        f"✏️ Edit {p['name']}\n"
        f"Changes affect future evaluations; "
        f"paid status and past history remain unchanged.",
        [
            ('📝 Name', f"edit_field:{p['id']}:name"),
            ('💰 Amount', f"edit_field:{p['id']}:amount"),
            ('💵 Currency', f"edit_field:{p['id']}:currency"),
            ('📅 Due Day', f"edit_field:{p['id']}:due_day"),
            ('⬅️ Back', f"payment:{p['id']}")
        ]
    )


@router.callback_query(F.data.startswith('edit_field:'))
async def edit_field(callback, state: FSMContext):
    _, raw, field = callback.data.split(':')

    if field not in {
        'name',
        'amount',
        'currency',
        'due_day',
    }:
        raise ValueError('Unknown field')

    p = await require_payment_admin(
        callback.bot,
        callback.from_user.id,
        int(raw)
    )

    await callback.answer()

    await state.set_state(
        EditPaymentState.value
    )

    await state.set_data({
        'chat_id': p['chat_id'],
        'payment_id': p['id'],
        'field': field
    })

    await show(
        callback,
        f"Current {field.replace('_', ' ')}: {p[field]}\n"
        f"Enter the new value.",
        [
            ('⬅️ Back', f"edit_payment:{p['id']}"),
            ('❌ Cancel', 'cancel')
        ]
    )


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
