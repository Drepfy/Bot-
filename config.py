import os

from dotenv import load_dotenv

load_dotenv()


def _get(name: str, default: str) -> str:
    value = os.getenv(name)
    return value if value and value.strip() else default


TOKEN = _get(
    "DISCORD_TOKEN",
    "MTUzNDAwODA2MjE3NDU2NDM5Mw.Gh5QtM.ZiphcqTiENNycIZnQ6wOP9W4NzpSKjek9eCzzU",
)
PREFIX = _get("BOT_PREFIX", "!")

OWNER_ID = int(_get("OWNER_ID", "0"))

ADMIN_ROLE_NAME = _get("ADMIN_ROLE_NAME", "Admin")
STAFF_ROLE_NAME = _get("STAFF_ROLE_NAME", "Admin")
TICKET_CATEGORY_NAME = _get("TICKET_CATEGORY_NAME", "Tickets")
TICKET_PANEL_CHANNEL_ID = int(
    _get("TICKET_PANEL_CHANNEL_ID", "1529177586054205562")
) or None
TRANSCRIPT_CHANNEL_ID = int(_get("TRANSCRIPT_CHANNEL_ID", "0")) or None
TICKET_LOG_CHANNELS = {
    "report": int(_get("TICKET_LOG_CHANNEL_REPORT", "1533932546297954345")) or None,
    "restore": int(_get("TICKET_LOG_CHANNEL_RESTORE", "1533933306922668144")) or None,
    "other": int(_get("TICKET_LOG_CHANNEL_OTHER", "1533933357069500517")) or None,
}
PARTNER_CHANNEL_ID = int(_get("PARTNER_CHANNEL_ID", "0")) or None
