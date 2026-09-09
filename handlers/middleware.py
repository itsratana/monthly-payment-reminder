"""Serialize each actor's updates; contain errors without leaking update data."""
import asyncio
import logging
from weakref import WeakValueDictionary
from aiogram import BaseMiddleware
from aiogram.exceptions import TelegramAPIError
from handlers.ui import keyboard
logger=logging.getLogger(__name__)


class InteractionMiddleware(BaseMiddleware):
    def __init__(self): self.locks=WeakValueDictionary()

    async def __call__(self,handler,event,data):
        actor=getattr(event,'from_user',None)
        if actor is None: return
        lock=self.locks.setdefault(actor.id,asyncio.Lock())
        async with lock:
            callback=hasattr(event,'data')
            message=event.message if callback else event
            if message is None: return
            public=(event.data or '').startswith('paid:') or event.data=='join_tracking' if callback else (event.text or '').split('@')[0].split(' ')[0] in ('/join','/start')
            if message.chat.type!='private' and not public:
                if callback: await event.answer('Open /start in a private chat to manage payments.',show_alert=True)
                else: await event.answer('Open /start privately to manage payments.')
                return
            try:
                return await handler(event,data)
            except (PermissionError,ValueError) as error:
                text=str(error)
            except TelegramAPIError as error:
                logger.warning('Telegram interaction failed type=%s',type(error).__name__)
                text='Telegram is unavailable or the bot lacks permission. Your saved changes remain saved; reopen the screen to check.'
            except Exception:
                logger.exception('Unexpected interaction failure actor=%s',actor.id)
                text='Something went wrong. Please reopen /start or cancel the current step and try again.'
            if callback:
                try: await event.answer(text[:190],show_alert=True)
                except TelegramAPIError: pass
            else:
                await event.answer(text,reply_markup=keyboard([('❌ Cancel','cancel')]))
