from aiogram.fsm.state import State, StatesGroup


class AddPaymentState(StatesGroup):
    waiting_for_name = State()
    waiting_for_amount = State()
    waiting_for_currency = State()
    waiting_for_due_day = State()
    waiting_for_reminder_time = State()

    selecting_members = State()
