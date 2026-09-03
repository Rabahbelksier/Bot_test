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
RAILWAY_PUBLIC_DOMAIN = os.getenv('RAILWAY_PUBLIC_DOMAIN', '')
PUBLIC_URL = (
    os.getenv('PUBLIC_URL')
    or RENDER_EXTERNAL_URL
    or (
        f"https://{RAILWAY_PUBLIC_DOMAIN}"
        if RAILWAY_PUBLIC_DOMAIN
        else ''
    )
).rstrip('/')
_channel_monitor_setting = os.getenv('CHANNEL_MONITOR_ENABLED')
_running_on_replit = bool(os.getenv('REPLIT_ENVIRONMENT') or os.getenv('REPL_ID'))
CHANNEL_MONITOR_ENABLED = (
    _channel_monitor_setting.strip().lower() in {'1', 'true', 'yes', 'on'}
    if _channel_monitor_setting is not None
    else not _running_on_replit
)
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY', '')
GEMINI_MODEL = os.getenv('GEMINI_MODEL', 'gemini-3.5-flash-lite')
TELEGRAM_API_ID = int(os.getenv('TELEGRAM_API_ID', '0') or 0)
TELEGRAM_API_HASH = os.getenv('TELEGRAM_API_HASH', '')
TELEGRAM_SESSION_STRING = os.getenv('TELEGRAM_SESSION_STRING', '')
try:
    CHANNEL_HISTORY_LIMIT = max(0, int(os.getenv('CHANNEL_HISTORY_LIMIT', '10') or 10))
except ValueError:
    CHANNEL_HISTORY_LIMIT = 10
CHANNEL_TELEGRAM_REPLACEMENT_LINK = os.getenv(
    'CHANNEL_TELEGRAM_REPLACEMENT_LINK',
    'https://t.me/rabahcopons/7366',
)
API_URL = "https://api-sg.aliexpress.com/sync"

if not all([APP_KEY, APP_SECRET, TRACKING_ID, TOKEN]):
    raise EnvironmentError("Missing required environment variables")
