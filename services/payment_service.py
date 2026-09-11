from database.payment_repository import (
    create_payment,
    get_payments,
    get_payment,
    get_payment_members,
    is_member_assigned,
    add_payment_member,
    remove_payment_member,
    get_payment_chat_id,
    get_due_payments,
    get_active_payments,
    get_payment_reminder_times,
    add_payment_reminder_time,
    remove_payment_reminder_time,
)


def save_payment(data):
    payment_id = create_payment(
        chat_id=data["chat_id"],
        name=data["payment_name"],
        amount=data["amount"],
        currency=data["currency"],
        due_day=data["due_day"],
        reminder_time=data["reminder_time"]
    )
    # Every new payment starts with its original reminder time
    # as reminder slot #1.
    result = add_payment_reminder_time(
        payment_id,
        data["reminder_time"]
    )

    if result not in ("added", "exists"):
        raise RuntimeError(
            "Payment was created but its reminder time could not be saved."
        )

    return payment_id

def get_group_payments(chat_id: int):
    return get_payments(chat_id)

def get_payment_detail(payment_id: int):
    return get_payment(payment_id)

def get_reminder_times(payment_id: int):
    rows = get_payment_reminder_times(payment_id)

    return [
        row["reminder_time"]
        for row in rows
    ]


def add_reminder_time(
    payment_id: int,
    text: str
):
    from utils.validators import VALIDATORS

    reminder_time = VALIDATORS["reminder_time"](text)

    if reminder_time is None:
        raise ValueError(
            "Invalid reminder time. Use HH:MM, for example 09:00 or 18:30."
        )

    return add_payment_reminder_time(
        payment_id,
        reminder_time
    )


def remove_reminder_time(
    payment_id: int,
    reminder_time: str
):
    return remove_payment_reminder_time(
        payment_id,
        reminder_time
    )

def get_selected_members(payment_id: int):
    return get_payment_members(payment_id)

def is_assigned(payment_id: int, user_id: int) -> bool:
    return is_member_assigned(payment_id, user_id)

def assign_member(payment_id: int, user_id: int):
    from database.member_repository import get_member
    chat_id = get_payment_chat_id(payment_id)
    if chat_id is None or get_member(user_id, chat_id) is None:
        raise ValueError('Member is not registered in this group.')
    add_payment_member(payment_id, user_id)

def unassign_member(payment_id: int, user_id: int):
    remove_payment_member(payment_id, user_id)

def get_payment_group(payment_id: int):
    return get_payment_chat_id(payment_id)

def get_today_payments(day: int):
    return get_due_payments(day)

def get_all_active_payments():
    return get_active_payments()


def edit_payment(payment_id, chat_id, field, text):
    from utils.validators import VALIDATORS
    from database.payment_repository import update_payment
    if field not in {
        'name',
        'amount',
        'currency',
        'due_day',
    }:
        raise ValueError('Unknown payment field')
    value = VALIDATORS[field](text)
    if value is None:
        raise ValueError('Invalid value. Use a name up to 100 characters, a positive amount with at most 2 decimals, a 3-letter currency, day 1–31, or HH:MM time.')
    return update_payment(payment_id, chat_id, field, value)


def set_active(payment_id, chat_id, active):
    from database.payment_repository import update_payment
    return update_payment(payment_id, chat_id, 'active', int(bool(active)))


def delete_payment(payment_id, chat_id):
    from database.payment_repository import delete_payment_completely
    return delete_payment_completely(payment_id, chat_id)
