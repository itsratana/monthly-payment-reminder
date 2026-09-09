from services.group_service import group_title
from aiogram import Router,F
from aiogram.fsm.context import FSMContext
from models.states import AddPaymentState
from services.authorization import require_admin
from services.payment_service import save_payment
from services.settings_service import group_settings
from utils.validators import VALIDATORS
from handlers.ui import show
router=Router()
FIELDS=['name','amount','currency','due_day','reminder_time']
STATES=[AddPaymentState.waiting_for_name,AddPaymentState.waiting_for_amount,AddPaymentState.waiting_for_currency,AddPaymentState.waiting_for_due_day,AddPaymentState.waiting_for_reminder_time]
PROMPTS=['💳 Payment name (up to 100 characters)','💰 Positive amount, at most 2 decimals','💵 Three-letter currency','📅 Due day (1–31)','⏰ Reminder time (HH:MM, 24-hour)']


async def prompt(event,state):
    data=await state.get_data();index=data['step'];field=FIELDS[index]
    await state.set_state(STATES[index])
    current=data.get('values',{}).get(field)
    buttons=[]
    if current is not None: buttons.append((f'Use {current}',f'create_default:{index}'))
    buttons += [('⬅️ Back',f'create_back:{index}'),('❌ Cancel','cancel')]
    await show(event,f"🏠 {group_title(data['chat_id'])}\n"+PROMPTS[index]+(f'\nCurrent/default: {current}' if current is not None else ''),buttons)


@router.callback_query(F.data.startswith('add_payment:'))
async def add_payment(callback,state:FSMContext):
    chat_id=int(callback.data.split(':')[1]);await require_admin(callback.bot,callback.from_user.id,chat_id)
    defaults=group_settings(chat_id);await state.clear()
    await state.set_data({'chat_id':chat_id,'step':0,'values':{'currency':defaults['currency'],'reminder_time':defaults['reminder_time']}})
    await callback.answer();await prompt(callback,state)


async def accept(event,state,text):
    data=await state.get_data()
    if 'step' not in data: raise ValueError('Wizard expired. Use /start.')
    await require_admin(event.bot,event.from_user.id,data['chat_id'])
    index=data['step'];field=FIELDS[index]
    if text is None or str(text).startswith('/'): raise ValueError('Enter a value or use /cancel.')
    value=VALIDATORS[field](str(text))
    if value is None: raise ValueError('Invalid value. '+PROMPTS[index])
    values=data['values'];values[field]=value
    await state.update_data(values=values)
    if index<len(FIELDS)-1:
        await state.update_data(step=index+1);await prompt(event,state);return
    # Creation is a single final write. No partial payment is persisted.
    payment_id=save_payment({'chat_id':data['chat_id'],'payment_name':values['name'],**values})
    await state.clear()
    await show(event,f"✅ Payment Created\n💳 {values['name']}\n💰 {values['amount']:.2f} {values['currency']}\n📅 Every {values['due_day']}\n⏰ {values['reminder_time']}\nAssign members to enable reminders.",
               [('👥 Manage Members',f'manage_members:{payment_id}'),('⬅️ Dashboard',f"group:{data['chat_id']}")])


# Register each existing state with the same validated progression.
async def input_value(message,state:FSMContext): await accept(message,state,message.text)
for wizard_state in STATES: router.message.register(input_value,wizard_state)


@router.callback_query(F.data.startswith('create_default:'))
async def use_default(callback,state:FSMContext):
    data=await state.get_data();index=int(callback.data.split(':')[1])
    if not 0<=index<len(STATES) or data.get('step')!=index or await state.get_state()!=STATES[index].state: raise ValueError('This step expired. Use /cancel.')
    await callback.answer();await accept(callback,state,data['values'].get(FIELDS[index]))


@router.callback_query(F.data.startswith('create_back:'))
async def back(callback,state:FSMContext):
    data=await state.get_data();index=int(callback.data.split(':')[1])
    if not 0<=index<len(STATES) or data.get('step')!=index or await state.get_state()!=STATES[index].state: raise ValueError('This step expired. Use /cancel.')
    await require_admin(callback.bot,callback.from_user.id,data['chat_id']);await callback.answer()
    if index==0:
        from handlers.dashboard import render_dashboard
        await state.clear();await render_dashboard(callback,data['chat_id'])
    else:
        await state.update_data(step=index-1);await prompt(callback,state)
