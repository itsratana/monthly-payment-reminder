from services.group_service import group_title
from aiogram import Router,F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State,StatesGroup
from services.authorization import require_admin
from services.settings_service import group_settings,save_setting
from handlers.ui import show
router=Router()


class SettingsState(StatesGroup):
    value=State()


@router.callback_query(F.data.startswith('settings:'))
async def settings(callback,state:FSMContext):
    chat_id=int(callback.data.split(':')[1]);await require_admin(callback.bot,callback.from_user.id,chat_id)
    await state.clear();await callback.answer()
    values=group_settings(chat_id)
    await show(callback,f"🏠 {group_title(chat_id)}\n⚙️ Group Settings\nCurrency: {values['currency']}\nTimezone: {values['timezone']}\nDefault time: {values['reminder_time']}\nPolicy: Daily until paid\n\nCurrency/time defaults prefill new payments. Existing payment values stay unchanged. Timezone changes affect future evaluations.",
               [(label,f'setting_field:{chat_id}:{field}') for label,field in [('💵 Default Currency','currency'),('🌍 Timezone','timezone'),('⏰ Default Reminder Time','reminder_time')]]+
               [('🔔 Daily until paid','policy_info'),('⬅️ Dashboard',f'group:{chat_id}')])


@router.callback_query(F.data=='policy_info')
async def policy_info(callback):
    await callback.answer('Daily until paid is the supported v1 policy.',show_alert=True)


@router.callback_query(F.data.startswith('setting_field:'))
async def setting_field(callback,state:FSMContext):
    _,raw,field=callback.data.split(':');chat_id=int(raw)
    if field not in {'currency','timezone','reminder_time'}: raise ValueError('Invalid setting')
    await require_admin(callback.bot,callback.from_user.id,chat_id);await callback.answer()
    await state.set_state(SettingsState.value);await state.set_data({'chat_id':chat_id,'field':field})
    await show(callback,f"Current {field}: {group_settings(chat_id)[field]}\nEnter new value (e.g. USD, Asia/Phnom_Penh, 09:00).",[('⬅️ Back',f'settings:{chat_id}'),('❌ Cancel','cancel')])


@router.message(SettingsState.value)
async def setting_value(message,state:FSMContext):
    data=await state.get_data();await require_admin(message.bot,message.from_user.id,data['chat_id'])
    if not message.text or message.text.startswith('/'):
        await show(message,'Enter a value or /cancel.',[('❌ Cancel','cancel')]);return
    save_setting(data['chat_id'],data['field'],message.text);await state.clear()
    await show(message,'✅ Group setting updated.',[('⬅️ Settings',f"settings:{data['chat_id']}")])
