from aiogram import Router,F
from aiogram.filters import Command
from services.member_service import (
    register_member,
    is_member_registered,
)
from database.group_repository import (
    is_onboarding_posted,
    mark_onboarding_posted
)

from services.authorization import require_admin
from handlers.ui import keyboard
router=Router()


@router.message(Command('join'))
async def join(message):
    user = message.from_user
    chat = message.chat

    if chat.type not in ('group', 'supergroup'):
        await message.answer(
            'Use /join inside a Telegram group.'
        )
        return

    already_member = is_member_registered(
        user.id,
        chat.id
    )

    register_member(user, chat)

    if already_member:
        await message.answer(
            "You're already registered for payment tracking."
        )
    else:
        await message.answer(
            f'✅ {user.full_name} joined payment tracking.'
        )

    if not is_onboarding_posted(chat.id):
        await message.answer(
            '👋 This group uses BongLuy for payment tracking.\n\n'
            'Tap below to register so admins can assign you to payments.',
            reply_markup=keyboard([
                ('✅ Join Payment Tracking', 'join_tracking')
            ])
        )

        mark_onboarding_posted(chat.id)


@router.callback_query(F.data == 'join_tracking')
async def join_button(callback):
    user = callback.from_user
    chat = callback.message.chat

    if is_member_registered(user.id, chat.id):
        await callback.answer(
            "You're already registered.",
            show_alert=True
        )
        return

    register_member(user, chat)

    await callback.answer(
        '✅ Joined payment tracking.'
    )

    await callback.message.answer(
        f'✅ {user.full_name} joined payment tracking.'
    )


@router.message(Command('onboard'))
async def onboard_group(message):
    chat = message.chat

    if chat.type not in ('group', 'supergroup'):
        await message.answer(
            'Use /onboard inside a group.'
        )
        return

    await require_admin(
        message.bot,
        message.from_user.id,
        chat.id
    )

    await message.answer(
        '👋 This group uses BongLuy for payment tracking.\n\n'
        'Tap below to register so admins can assign you to payments.',
        reply_markup=keyboard([
            ('✅ Join Payment Tracking', 'join_tracking')
        ])
    )

    mark_onboarding_posted(chat.id)

@router.callback_query(F.data.startswith('onboard:'))
async def onboarding(callback):
    chat_id = int(callback.data.split(':')[1])

    await require_admin(
        callback.bot,
        callback.from_user.id,
        chat_id
    )

    await callback.answer()

    await callback.bot.send_message(
        chat_id,
        '👋 This group uses BongLuy for payment tracking.\n\n'
        'Tap below to register so admins can assign you to payments.',
        reply_markup=keyboard([
            ('✅ Join Payment Tracking', 'join_tracking')
        ])
    )

    mark_onboarding_posted(chat_id)

    await callback.message.answer(
        '✅ Join button posted to the group.'
    )
