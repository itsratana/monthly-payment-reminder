from aiogram import Router, F

router = Router()


@router.callback_query()
async def expired(callback):
    await callback.answer(
        'This action expired. Open /start to continue.',
        show_alert=True
    )


@router.message(~F.text.startswith('/'))
async def help_message(message):
    await message.answer(
        'Use /start to open your dashboard, /join in a group to register, '
        '/onboard in a group to post the Join Payment Tracking button, '
        'or /cancel to cancel a wizard.'
    )