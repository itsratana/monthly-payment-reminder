"""Real aiogram routing with a fake Telegram transport; never network."""
from datetime import datetime,timezone
import pytest
from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.types import Update,Message,ChatMemberOwner,User,ChatMemberMember
from aiogram.methods import GetChatMember,SendMessage,EditMessageText,AnswerCallbackQuery

class Transport(BaseSession):
    def __init__(self):
        super().__init__();self.calls=[];self.admin=True;self.count=100
    async def close(self): pass
    async def stream_content(self,*args,**kwargs):
        if False: yield b''
    async def make_request(self,bot,method,timeout=None):
        self.calls.append(method)
        if isinstance(method,GetChatMember):
            user=User(id=7,is_bot=False,first_name='Admin')
            return ChatMemberOwner(user=user,is_anonymous=False) if self.admin else ChatMemberMember(user=user)
        if isinstance(method,(SendMessage,EditMessageText)):
            self.count+=1
            return Message(message_id=self.count,date=datetime.now(timezone.utc),chat={'id':int(method.chat_id),'type':'private' if int(method.chat_id)>0 else 'supergroup'},text=method.text)
        if isinstance(method,AnswerCallbackQuery): return True
        raise AssertionError(type(method).__name__)

async def feed(bot,content,callback=False):
    from app import dp
    actor={'id':7,'is_bot':False,'first_name':'Admin'}
    message={'message_id':123,'date':int(datetime.now(timezone.utc).timestamp()),'chat':{'id':7,'type':'private'},'from':actor,'text':content}
    update={'update_id':123}
    if callback:
        update['callback_query']={'id':'abc','from':actor,'chat_instance':'test','data':content,'message':message}
    else:
        if content.startswith('/'): message['entities']=[{'type':'bot_command','offset':0,'length':len(content.split()[0])}]
        update['message']=message
    await dp.feed_update(bot,Update.model_validate(update))

@pytest.mark.asyncio
async def test_dashboard_all_routes_and_create_cancel(seeded_payment):
    transport=Transport();bot=Bot('123456789:TEST_TOKEN_NOT_FOR_NETWORK',session=transport)
    p=seeded_payment;pid=p['payment_id'];chat=p['chat_id']
    await feed(bot,'/start')
    for value in [f'group:{chat}',f'payments:{chat}',f'payment:{pid}',f'manage_members:{pid}',f'members:{chat}',f'member_detail:{chat}:{p["member_a"]}',f'status:{chat}',f'reports:{chat}',f'settings:{chat}',f'edit_payment:{pid}',f'edit_field:{pid}:name']:
        await feed(bot,value,True)
    await feed(bot,'Renamed TV')
    from database.payment_repository import get_payment,get_payments
    assert get_payment(pid)['name']=='Renamed TV'
    await feed(bot,f'add_payment:{chat}',True);await feed(bot,'Internet');await feed(bot,'/cancel')
    assert len(get_payments(chat))==1
    await feed(bot,'switch_group',True)
    assert not any('went wrong' in str(getattr(c,'text','')) for c in transport.calls)
    transport.admin=False;await feed(bot,f'active_payment:{pid}:0',True)
    assert get_payment(pid)['active']==1
    assert any(isinstance(c,AnswerCallbackQuery) and 'admin' in (c.text or '') for c in transport.calls)


@pytest.mark.asyncio
async def test_all_management_callbacks_deny_non_admin(seeded_payment):
    transport=Transport();transport.admin=False
    bot=Bot('123456789:TEST_TOKEN_NOT_FOR_NETWORK',session=transport)
    p=seeded_payment;pid=p['payment_id'];chat=p['chat_id'];uid=p['member_a']
    actions=[f'group:{chat}',f'payments:{chat}',f'payment:{pid}',f'members:{chat}',f'member_detail:{chat}:{uid}',f'status:{chat}',f'reports:{chat}',f'settings:{chat}',f'edit_payment:{pid}',f'edit_field:{pid}:name',f'active_payment:{pid}:0',f'delete_payment:{pid}',f'confirm_delete:{pid}',f'manage_members:{pid}',f'assign_member:{pid}:{uid}:0:0',f'add_payment:{chat}',f'onboard:{chat}',f'setting_field:{chat}:currency',f'correct:{pid}:{uid}:2026:9:1',f'cycle:{pid}:2026:9:current:0']
    for action in actions:
        transport.calls.clear();await feed(bot,action,True)
        assert any(isinstance(c,AnswerCallbackQuery) and 'admin' in (c.text or '') for c in transport.calls),action
        assert not any(isinstance(c,(SendMessage,EditMessageText)) for c in transport.calls),action


@pytest.mark.asyncio
async def test_creation_defaults_settings_and_switch_abandon_wizard(seeded_payment):
    transport=Transport();bot=Bot('123456789:TEST_TOKEN_NOT_FOR_NETWORK',session=transport)
    p=seeded_payment;chat=p['chat_id']
    await feed(bot,f'setting_field:{chat}:currency',True);await feed(bot,'EUR')
    await feed(bot,f'add_payment:{chat}',True)
    await feed(bot,'Internet');await feed(bot,'25');await feed(bot,'create_default:2',True)
    await feed(bot,'12');await feed(bot,'create_default:4',True)
    from database.payment_repository import get_payments
    rows=get_payments(chat)
    assert any(row['name']=='Internet' and row['currency']=='EUR' for row in rows)
    await feed(bot,f'add_payment:{chat}',True);await feed(bot,'Abandoned')
    await feed(bot,'switch_group',True);await feed(bot,'99')
    assert len(get_payments(chat))==2
