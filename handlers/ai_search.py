import asyncio
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from core.ai import GeminiError, parse_user_request
from core.db import (
    get_channel_post,
    save_channel_photo_file_id,
    search_channel_posts,
)
from utils.telegram import remove_pressed_button

logger = logging.getLogger(__name__)

AI_SEARCH_BUTTON_TEXT = "اسأل الذكاء الاصطناعي"
AI_SEARCH_HELP_TEXT = """يمكنك أن تطلب مني البحث في العروض المحفوظة، مثل:

• أفضل عرض على منتج معين
• أرخص الهواتف
• هواتف بين 50 و100 دولار
• أرخص عرض لمنتج محدد
• العروض الرائجة اليوم

اكتب طلبك الآن، أو أرسل /cancel للعودة إلى البحث العادي."""

AI_SEARCH_SUPPORTED_TEXT = """هذه الأداة تدعم البحث عن:
• أفضل عرض على منتج معين
• أرخص عروض فئة أو نوع معين
• عروض فئة ضمن سعر محدد
• منتج معين بأرخص سعر
• منتج معين ضمن نطاق سعري
• العروض الرائجة أو المتكررة اليوم"""


def _clear_ai_search_state(context):
    context.user_data.pop("ai_search_active", None)
    context.user_data.pop("ai_search_results", None)
    context.user_data.pop("ai_search_index", None)


def ask_ai_button():
    return InlineKeyboardButton(
        AI_SEARCH_BUTTON_TEXT,
        callback_data="ask_ai",
    )


def _next_keyboard(has_next):
    if not has_next:
        return None
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("عرض آخر", callback_data="ai_next"),
    ]])


def _split_text(text, limit=4096):
    return [
        text[index:index + limit]
        for index in range(0, len(text), limit)
    ] or [""]


async def _send_text_post(bot, chat_id, content, has_next):
    chunks = _split_text(content)
    for index, chunk in enumerate(chunks):
        await bot.send_message(
            chat_id=chat_id,
            text=chunk,
            reply_markup=_next_keyboard(has_next and index == len(chunks) - 1),
        )


async def _download_source_photo(post, context):
    monitor = context.application.bot_data.get("channel_monitor")
    if not monitor:
        return None
    return await monitor.download_photo(
        post["source_channel_id"],
        post["source_message_id"],
    )


async def send_stored_post(chat_id, context, post, has_next=False):
    """Send the stored post without adding a custom content template."""
    bot = context.bot
    content = (post.get("content") or post.get("title") or "").strip()
    if not content:
        content = "لا يوجد نص محفوظ لهذا العرض."

    photo = post.get("photo_file_id")
    downloaded_source = False
    if not photo:
        photo = await _download_source_photo(post, context)
        downloaded_source = photo is not None

    if photo:
        try:
            caption = content if len(content) <= 1024 else "📦"
            sent = await bot.send_photo(
                chat_id=chat_id,
                photo=photo,
                caption=caption,
                reply_markup=_next_keyboard(has_next) if len(content) <= 1024 else None,
            )
            if sent.photo:
                file_id = sent.photo[-1].file_id
                if downloaded_source or not post.get("photo_file_id"):
                    await asyncio.to_thread(
                        save_channel_photo_file_id,
                        post["id"],
                        file_id,
                    )
            if len(content) > 1024:
                await _send_text_post(bot, chat_id, content, has_next)
            return sent
        except Exception:
            logger.exception("Could not send stored photo for post %s", post.get("id"))
            if post.get("photo_file_id"):
                fallback = await _download_source_photo(post, context)
                if fallback:
                    try:
                        sent = await bot.send_photo(
                            chat_id=chat_id,
                            photo=fallback,
                            caption=content if len(content) <= 1024 else "📦",
                            reply_markup=(
                                _next_keyboard(has_next)
                                if len(content) <= 1024
                                else None
                            ),
                        )
                        if sent.photo:
                            await asyncio.to_thread(
                                save_channel_photo_file_id,
                                post["id"],
                                sent.photo[-1].file_id,
                            )
                        if len(content) > 1024:
                            await _send_text_post(bot, chat_id, content, has_next)
                        return sent
                    except Exception:
                        logger.exception(
                            "Could not send downloaded fallback photo for post %s",
                            post.get("id"),
                        )

    await _send_text_post(bot, chat_id, content, has_next)
    return None


async def ask_ai_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await remove_pressed_button(query)
    context.user_data["ai_search_active"] = True
    context.user_data.pop("ai_search_results", None)
    context.user_data.pop("ai_search_index", None)
    await query.message.reply_text(AI_SEARCH_HELP_TEXT)


async def cancel_ai_search_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    has_ai_state = any(
        key in context.user_data
        for key in ("ai_search_active", "ai_search_results", "ai_search_index")
    )
    if not has_ai_state:
        return

    _clear_ai_search_state(context)
    await update.effective_message.reply_text(
        "تم إلغاء البحث والعودة إلى الوضع العادي."
    )


async def handle_ai_search_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("ai_search_active"):
        return False

    text = (update.effective_message.text or "").strip()
    if text.lower() in {"/cancel", "cancel", "إلغاء"}:
        _clear_ai_search_state(context)
        await update.effective_message.reply_text("تم إلغاء البحث والعودة إلى الوضع العادي.")
        return True

    try:
        intent = await asyncio.to_thread(parse_user_request, text)
    except GeminiError:
        logger.exception("AI search request failed")
        await update.effective_message.reply_text(
            "تعذر تشغيل البحث بالذكاء الاصطناعي حاليًا، حاول مرة أخرى لاحقًا."
        )
        return True
    except Exception:
        logger.exception("Unexpected AI search error")
        await update.effective_message.reply_text(
            "حدث خطأ أثناء فهم طلب البحث."
        )
        return True

    if intent["request_type"] == "unsupported":
        await update.effective_message.reply_text(AI_SEARCH_SUPPORTED_TEXT)
        return True

    try:
        posts = await asyncio.to_thread(search_channel_posts, intent)
    except Exception:
        logger.exception("AI search database query failed")
        await update.effective_message.reply_text(
            "تعذر الوصول إلى العروض المحفوظة حاليًا، حاول مرة أخرى لاحقًا."
        )
        return True
    if not posts:
        await update.effective_message.reply_text(
            "لم أجد عروضًا محفوظة تطابق طلبك. حاول تغيير اسم المنتج أو نطاق السعر."
        )
        return True

    context.user_data["ai_search_results"] = [post["id"] for post in posts]
    context.user_data["ai_search_index"] = 0
    context.user_data["ai_search_active"] = False
    await send_stored_post(
        update.effective_chat.id,
        context,
        posts[0],
        has_next=len(posts) > 1,
    )
    return True


async def ai_next_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await remove_pressed_button(query)

    result_ids = context.user_data.get("ai_search_results", [])
    index = context.user_data.get("ai_search_index", 0) + 1
    if index >= len(result_ids):
        await query.message.reply_text("لا توجد عروض أخرى لهذا البحث.")
        return

    post = await asyncio.to_thread(get_channel_post, result_ids[index])
    if not post:
        await query.message.reply_text("تعذر العثور على العرض التالي.")
        return

    context.user_data["ai_search_index"] = index
    await send_stored_post(
        query.message.chat.id,
        context,
        post,
        has_next=index < len(result_ids) - 1,
    )