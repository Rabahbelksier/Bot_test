import logging
import asyncio
import threading
import requests
from flask import Flask, request, Response
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackQueryHandler

from config import TOKEN, PORT, RENDER_EXTERNAL_URL
from core.db import init_db
from handlers.start import start
from handlers.messages import handle_message
from handlers.callbacks import product_details_callback

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

telegram_app = Application.builder().token(TOKEN).updater(None).build()
telegram_app.add_handler(CommandHandler("start", start))
telegram_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
telegram_app.add_handler(CallbackQueryHandler(product_details_callback, pattern="^details_"))

_loop = None
_initialized = False
_init_lock = threading.Lock()


def _ensure_ready():
    global _loop, _initialized
    if _initialized:
        return _loop
    with _init_lock:
        if _initialized:
            return _loop
        _loop = asyncio.new_event_loop()
        t = threading.Thread(target=_loop.run_forever, daemon=True)
        t.start()
        f = asyncio.run_coroutine_threadsafe(telegram_app.initialize(), _loop)
        f.result(timeout=30)
        f = asyncio.run_coroutine_threadsafe(telegram_app.start(), _loop)
        f.result(timeout=30)
        _initialized = True
        logger.info("Telegram app ready in worker process")
        return _loop


@app.route('/')
def index():
    return 'Bot is running'


@app.route(f'/{TOKEN}', methods=['POST'])
def webhook():
    try:
        loop = _ensure_ready()
        json_data = request.get_json(force=True)
        update = Update.de_json(json_data, telegram_app.bot)
        asyncio.run_coroutine_threadsafe(
            telegram_app.process_update(update), loop
        )
        return Response(status=200)
    except Exception as e:
        logger.error(f"Webhook error: {e}", exc_info=True)
        return Response(status=200)


def set_webhook():
    if RENDER_EXTERNAL_URL:
        webhook_url = f"{RENDER_EXTERNAL_URL}/{TOKEN}"
        url = f"https://api.telegram.org/bot{TOKEN}/setWebhook?url={webhook_url}"
        response = requests.get(url)
        logger.info(f"Webhook set response: {response.json()}")
    else:
        logger.warning("RENDER_EXTERNAL_URL not set, webhook not configured")


init_db()
set_webhook()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=PORT)
