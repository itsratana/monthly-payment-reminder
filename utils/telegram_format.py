"""Telegram-safe text helpers: HTML escaping and member mentions (spec 4.5).

Every value that came from the database or from Telegram user profiles must
be escaped before it is concatenated into an HTML message. Never build HTML
by inserting raw payment names, full names, usernames, or currency strings.
"""

import html


def escape_html(value) -> str:
    """Escape a value for use inside a Telegram parse_mode="HTML" message."""

    if value is None:
        return ""
    return html.escape(str(value), quote=False)


def format_mention(user_id: int, username: str | None, full_name: str | None) -> str:
    """Render a safe mention for a member.

    Prefers a visible @username. Falls back to an HTML tg://user link using
    the numeric id and the escaped full name (or the id itself if no name is
    on record) so every assigned member is mentionable.
    """

    if username:
        return f"@{escape_html(username)}"

    display_name = str(full_name or user_id)[:128]
    return f'<a href="tg://user?id={user_id}">{escape_html(display_name)}</a>'


def format_amount(amount: float, currency: str) -> str:
    return f"{amount:.2f} {escape_html(currency)}"
