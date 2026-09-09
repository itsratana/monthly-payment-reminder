"""Serialize rendering and mutations for one payment within the single bot owner."""
import asyncio
from weakref import WeakValueDictionary
_locks=WeakValueDictionary()


def payment_lock(payment_id):
    return _locks.setdefault(payment_id,asyncio.Lock())
