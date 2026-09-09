from database.payment_status_repository import (
    create_payment_status,
    initialize_for_assigned_members,
    get_unpaid_members,
    get_status,
    mark_as_paid,
)


def create_monthly_status(payment_id, user_id, year, month):
    create_payment_status(
        payment_id,
        user_id,
        year,
        month
    )


def initialize_monthly_status_for_payment(payment_id, year, month):
    """Idempotent: create a status row for every currently assigned member."""

    initialize_for_assigned_members(payment_id, year, month)


def get_pending_members(payment_id, year, month):
    return get_unpaid_members(
        payment_id,
        year,
        month
    )


def get_member_status(payment_id, user_id, year, month):
    return get_status(payment_id, user_id, year, month)


def set_member_paid(payment_id, user_id, year, month) -> bool:
    """Returns True if this call actually changed the row (spec 4.4)."""

    return mark_as_paid(
        payment_id,
        user_id,
        year,
        month
    )


def correct_current_status(payment_id,user_id,year,month,paid,actor_id,now=None):
    from database.payment_repository import get_payment
    from database.payment_status_repository import change_status
    from services.settings_service import group_now
    payment=get_payment(payment_id)
    if payment is None or not payment['active']: raise ValueError('Payment is missing or disabled.')
    local=group_now(payment['chat_id'],now)
    if (year,month)!=(local.year,local.month): raise ValueError('This screen expired. Open current Status again.')
    initialize_monthly_status_for_payment(payment_id,year,month)
    return change_status(payment_id,user_id,year,month,paid,actor_id)
