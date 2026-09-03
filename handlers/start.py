import logging
from telegram import Update
from telegram.ext import ContextTypes

from core.db import save_user
from handlers.ai_search import ai_search_reply_keyboard, _clear_ai_search_state
from handlers.help import START_TEXT, help_keyboard

logger = logging.getLogger(__name__)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _clear_ai_search_state(context)
    user = update.effective_user
    save_user(user.id, user.first_name, user.last_name or '')
    await update.message.reply_text(
        START_TEXT,
        reply_markup=ai_search_reply_keyboard(),
    )
    await update.message.reply_text(
        "اختر الموضوع الذي تريد معرفة تفاصيله:",
        reply_markup=help_keyboard(),
    )
