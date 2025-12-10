import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "0"))
MODERATION_ENABLED = os.getenv("MODERATION_ENABLED", "true").lower() == "true"

# Rate limiting
RATE_LIMIT_MESSAGES = int(os.getenv("RATE_LIMIT_MESSAGES", "10"))
RATE_LIMIT_WINDOW_MINUTES = int(os.getenv("RATE_LIMIT_WINDOW_MINUTES", "60"))
SPAM_THRESHOLD = int(os.getenv("SPAM_THRESHOLD", "20"))
