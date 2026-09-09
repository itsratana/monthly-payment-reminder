from dotenv import load_dotenv
import os
import logging
from zoneinfo import ZoneInfo

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")

DEFAULT_CURRENCY = "USD"
DEFAULT_REMINDER_TIME = "09:00"

APP_TIMEZONE = os.getenv("APP_TIMEZONE", "Asia/Phnom_Penh")
try:
    REMINDER_CHECK_SECONDS = int(os.getenv("REMINDER_CHECK_SECONDS", "60"))
except ValueError:
    REMINDER_CHECK_SECONDS = 0  # Report a useful error during runtime validation.
DATABASE_PATH = os.getenv("DATABASE_PATH", "reminder.db")
REMINDER_POLICY = os.getenv("REMINDER_POLICY", "daily_until_paid")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# Backward-compatible alias (previous name used by the original scheduler wiring).
DEFAULT_TIMEZONE = APP_TIMEZONE
REMINDER_CHECK_INTERVAL = REMINDER_CHECK_SECONDS


def validate_config():
    """Fail fast with a useful message if required configuration is missing.

    Called explicitly at application startup (not at import time) so the
    module can still be imported safely by tests and tooling without a
    BOT_TOKEN set.
    """

    if not BOT_TOKEN:
        raise RuntimeError(
            "BOT_TOKEN is not set. Create a .env file (or set the "
            "environment variable) with BOT_TOKEN=<your telegram bot token>."
        )

    if REMINDER_CHECK_SECONDS <= 0:
        raise RuntimeError('REMINDER_CHECK_SECONDS must be positive.')
    try:
        ZoneInfo(APP_TIMEZONE)
    except (ValueError, KeyError) as error:
        raise RuntimeError('APP_TIMEZONE must be a valid IANA timezone.') from error
    if REMINDER_POLICY != 'daily_until_paid':
        raise RuntimeError('Only REMINDER_POLICY=daily_until_paid is supported.')
    if LOG_LEVEL.upper() not in logging.getLevelNamesMapping():
        raise RuntimeError('LOG_LEVEL is invalid.')
    if not DATABASE_PATH.strip():
        raise RuntimeError('DATABASE_PATH must not be empty.')

DATABASE_REQUIRE_EXISTING = os.getenv('DATABASE_REQUIRE_EXISTING', 'false').lower() == 'true'
HEALTH_PATH = os.getenv('HEALTH_PATH', DATABASE_PATH + '.health.json')
BACKUP_DIRECTORY = os.getenv('BACKUP_DIRECTORY', '')
