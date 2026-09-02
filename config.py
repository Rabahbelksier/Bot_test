import os

APP_KEY = os.getenv('APP_KEY')
APP_SECRET = os.getenv('APP_SECRET')
TRACKING_ID = os.getenv('TRACKING_ID')
TOKEN = os.getenv('TELEGRAM_TOKEN')
# Prefer the explicitly configured external database when available. Replit's
# DATABASE_URL is the built-in development database in this workspace.
DATABASE_URL = os.getenv('EXTERNAL_DATABASE_URL') or os.getenv('DATABASE_URL')
PORT = int(os.getenv('PORT', 5000))
RENDER_EXTERNAL_URL = os.getenv('RENDER_EXTERNAL_URL', '')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY', '')
GEMINI_MODEL = os.getenv('GEMINI_MODEL', 'gemini-2.0-flash')
TELEGRAM_API_ID = int(os.getenv('TELEGRAM_API_ID', '0') or 0)
TELEGRAM_API_HASH = os.getenv('TELEGRAM_API_HASH', '')
TELEGRAM_SESSION_STRING = os.getenv('TELEGRAM_SESSION_STRING', '')
CHANNEL_TELEGRAM_REPLACEMENT_LINK = os.getenv(
    'CHANNEL_TELEGRAM_REPLACEMENT_LINK',
    'https://t.me/rabahcopons/7366',
)
API_URL = "https://api-sg.aliexpress.com/sync"

if not all([APP_KEY, APP_SECRET, TRACKING_ID, TOKEN]):
    raise EnvironmentError("Missing required environment variables")
