import os
import logging
import asyncio
import threading
import requests
from flask import Flask, request, Response, jsonify
from telegram import BotCommand, Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackQueryHandler

from config import TOKEN, PORT, RENDER_EXTERNAL_URL
from core.db import init_db
from handlers.help import help_command, help_topic_callback
from handlers.start import start
from handlers.coupons import coupons_callback, coupons_command
from handlers.admin import admin_callback, admin_command
from handlers.messages import handle_message
from handlers.callbacks import (
    other_smart_cart_button_callback,
    app_promotion_callback,
    product_details_callback,
    select_coupon,
    smart_cart_callback,
)
from core.scraper import get_product_details_scraping

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

SCRAPE_API_KEY = os.getenv('SCRAPE_API_KEY', '')

telegram_app = Application.builder().token(TOKEN).updater(None).build()
telegram_app.add_handler(CommandHandler("start", start))
telegram_app.add_handler(CommandHandler("help", help_command))
telegram_app.add_handler(CommandHandler("coupons", coupons_command))
telegram_app.add_handler(CommandHandler("admin", admin_command))
telegram_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
telegram_app.add_handler(CallbackQueryHandler(product_details_callback, pattern="^details_"))
telegram_app.add_handler(CallbackQueryHandler(smart_cart_callback, pattern="^smart_cart_"))
telegram_app.add_handler(CallbackQueryHandler(select_coupon, pattern="^smart_coupon_"))
telegram_app.add_handler(CallbackQueryHandler(app_promotion_callback, pattern="^app_promotion$"))
telegram_app.add_handler(
    CallbackQueryHandler(other_smart_cart_button_callback, pattern="^smart_other_")
)
telegram_app.add_handler(
    CallbackQueryHandler(coupons_callback, pattern="^show_coupons$")
)
telegram_app.add_handler(
    CallbackQueryHandler(help_topic_callback, pattern="^help_(basic|smart_cart)$")
)
telegram_app.add_handler(
    CallbackQueryHandler(admin_callback, pattern="^admin_(edit|add|exit)(_[0-9]+)?$")
)

_loop = None
_initialized = False
_init_lock = threading.Lock()

BOT_COMMANDS = [
    BotCommand("start", "بدء استخدام البوت"),
    BotCommand("help", "شرح طريقة استعمال البوت"),
    BotCommand("coupons", "عرض الكوبونات والرموز الترويجية"),
]


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
        try:
            f = asyncio.run_coroutine_threadsafe(
                telegram_app.bot.set_my_commands(BOT_COMMANDS),
                _loop,
            )
            f.result(timeout=30)
        except Exception:
            logger.exception("Failed to configure Telegram command menu")
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


@app.route('/scrape', methods=['GET'])
def scrape_product():
    key = request.args.get('key', '')
    if SCRAPE_API_KEY and key != SCRAPE_API_KEY:
        return jsonify({'error': 'Unauthorized'}), 401

    product_id = request.args.get('product_id', '').strip()
    if not product_id:
        return jsonify({'error': 'product_id required'}), 400

    logger.info(f"Scrape request for product_id: {product_id}")
    result = get_product_details_scraping(product_id)
    return jsonify({
        'title': result.get('title'),
        'image_url': result.get('image_url')
    })


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
