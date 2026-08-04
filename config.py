import os

from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("MTUzNDAwODA2MjE3NDU2NDM5Mw.GvOixW.3V4p8jVEbGXOLkehMXCEr4cFxaYVZK1d8E2bIs", "")
PREFIX = os.getenv("BOT_PREFIX", "!")

OWNER_ID = int(os.getenv("1529173179900104915", "0"))

AI_ENABLED = os.getenv("AI_ENABLED", "true").lower() == "true"
AI_MODEL = os.getenv("AI_MODEL", "gpt-4o-mini")
AI_VISION_MODEL = os.getenv("AI_VISION_MODEL", "gpt-4o-mini")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")

WELCOME_CHANNEL_ID = int(os.getenv("WELCOME_CHANNEL_ID", "0")) or None
ADMIN_ROLE_NAME = os.getenv("ADMIN_ROLE_NAME", "Admin")
STAFF_ROLE_NAME = os.getenv("STAFF_ROLE_NAME", "Staff")
TICKET_CATEGORY_NAME = os.getenv("TICKET_CATEGORY_NAME", "Tickets")
PARTNER_CHANNEL_ID = int(os.getenv("PARTNER_CHANNEL_ID", "0")) or None
