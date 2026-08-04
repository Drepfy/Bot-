import os

from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv(
    "DISCORD_TOKEN",
    "MTUzNDAwODA2MjE3NDU2NDM5Mw.Gh5QtM.ZiphcqTiENNycIZnQ6wOP9W4NzpSKjek9eCzzU",
)
PREFIX = os.getenv("BOT_PREFIX", "!")

OWNER_ID = int(os.getenv("OWNER_ID", "0"))

WELCOME_CHANNEL_ID = int(os.getenv("WELCOME_CHANNEL_ID", "0")) or None
ADMIN_ROLE_NAME = os.getenv("ADMIN_ROLE_NAME", "Admin")
STAFF_ROLE_NAME = os.getenv("STAFF_ROLE_NAME", "Admin")
TICKET_CATEGORY_NAME = os.getenv("TICKET_CATEGORY_NAME", "Tickets")
TICKET_PANEL_CHANNEL_ID = int(
    os.getenv("TICKET_PANEL_CHANNEL_ID", "1529177586054205562")
) or None
PARTNER_CHANNEL_ID = int(os.getenv("PARTNER_CHANNEL_ID", "0")) or None
