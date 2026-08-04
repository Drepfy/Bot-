import os

from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv(
    "DISCORD_TOKEN",
    "MTUzNDAwODA2MjE3NDU2NDM5Mw.Gh5QtM.ZiphcqTiENNycIZnQ6wOP9W4NzpSKjek9eCzzU",
)
PREFIX = os.getenv("BOT_PREFIX", "!")

OWNER_ID = int(os.getenv("OWNER_ID", "0"))

AI_ENABLED = os.getenv("AI_ENABLED", "true").lower() == "true"
AI_MODEL = os.getenv("AI_MODEL", "gpt-4o-mini")
AI_VISION_MODEL = os.getenv("AI_VISION_MODEL", "gpt-4o-mini")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")

WELCOME_CHANNEL_ID = int(os.getenv("WELCOME_CHANNEL_ID", "0")) or None
ADMIN_ROLE_NAME = os.getenv("ADMIN_ROLE_NAME", "Admin")
STAFF_ROLE_NAME = os.getenv("STAFF_ROLE_NAME", "Admin")
TICKET_CATEGORY_NAME = os.getenv("TICKET_CATEGORY_NAME", "Tickets")
PARTNER_CHANNEL_ID = int(os.getenv("PARTNER_CHANNEL_ID", "0")) or None
