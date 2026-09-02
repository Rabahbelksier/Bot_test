import logging
from telegram import Update
from telegram.ext import ContextTypes

from services.queue_manager import enqueue_url
from core.smart_cart import handle_smart_cart_message
from handlers.admin import handle_admin_message
from handlers.ai_search import (
    handle_ai_search_button_message,
    handle_ai_search_message,
)
from utils.parser import extract_aliexpress_url

logger = logging.getLogger(__name__)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await handle_admin_message(update, context):
        return
    if await handle_smart_cart_message(update, context):
        return
    if await handle_ai_search_button_message(update, context):
        return
    if await handle_ai_search_message(update, context):
        return
    user_input = update.message.text
    chat_id = update.effective_chat.id
    target_url = extract_aliexpress_url(user_input)
    if not target_url:
        await update.message.reply_text("⚠️ من فضلك قم بإرسال روابط منتجات Aliexpress فقط 😕")
        return

    await enqueue_url(chat_id, target_url, context)
