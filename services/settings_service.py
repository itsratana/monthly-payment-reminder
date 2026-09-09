from datetime import datetime
from zoneinfo import ZoneInfo
import config
from database.settings_repository import read_settings, write_setting
from utils.validators import VALIDATORS


def group_settings(chat_id):
    values={'currency':config.DEFAULT_CURRENCY,'timezone':config.APP_TIMEZONE,
            'reminder_time':config.DEFAULT_REMINDER_TIME,'reminder_policy':config.REMINDER_POLICY}
    values.update({k:v for k,v in read_settings(chat_id).items() if v is not None})
    return values


def save_setting(chat_id, field, text):
    if field=='reminder_policy':
        if text!='daily_until_paid': raise ValueError('Only daily_until_paid is supported.')
        value=text
    elif field in {'currency','timezone','reminder_time'}:
        value=VALIDATORS[field](text)
        if value is None: raise ValueError('Invalid setting. Use a 3-letter currency, IANA timezone, or HH:MM time.')
    else: raise ValueError('Unknown setting')
    write_setting(chat_id,field,value)


def group_now(chat_id, now=None):
    zone=ZoneInfo(group_settings(chat_id)['timezone'])
    return datetime.now(zone) if now is None else now.astimezone(zone)
