import asyncio
import logging

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputFile,
    InputMediaPhoto,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    Update,
)
from telegram.ext import ContextTypes

from core.ai import GeminiError, parse_user_request
from core.db import (
    get_channel_post,
    save_channel_photo_file_id,
    search_channel_posts,
)
from utils.parser import extract_aliexpress_url

logger = logging.getLogger(__name__)

AI_SEARCH_BUTTON_TEXT = "اسأل الذكاء الاصطناعي"
AI_SEARCH_HELP_TEXT = """يمكنك أن تطلب مني البحث في العروض المحفوظة، مثل:

• أفضل عرض على منتج معين
• أرخص الهواتف
• هواتف بين 50 و100 دولار
• أرخص عرض لمنتج محدد
• العروض الرائجة اليوم

اكتب طلبك الآن. يبقى وضع الذكاء الاصطناعي فعالاً حتى ترسل رابط AliExpress."""

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


def _navigation_lock(context):
    """Serialize navigation clicks for one user's current search."""
    lock = context.user_data.get("ai_search_navigation_lock")
    if lock is None:
        lock = asyncio.Lock()
        context.user_data["ai_search_navigation_lock"] = lock
    return lock


def ask_ai_button():
    return InlineKeyboardButton(
        AI_SEARCH_BUTTON_TEXT,
        callback_data="ask_ai",
    )


def ai_search_reply_keyboard():
    return ReplyKeyboardMarkup(
        [[KeyboardButton(AI_SEARCH_BUTTON_TEXT)]],
        resize_keyboard=True,
        is_persistent=True,
    )


async def _activate_ai_search(message, context):
    _clear_ai_search_state(context)
    context.user_data["ai_search_active"] = True
    await message.reply_text(
        AI_SEARCH_HELP_TEXT,
        reply_markup=ReplyKeyboardRemove(),
    )


def _restore_ai_search_keyboard(context):
    """Ask the next normal-mode reply to restore the persistent keyboard."""
    context.user_data["restore_ai_search_keyboard"] = True


async def _cache_photo_file_id(post_id, photo_file_id):
    try:
        await asyncio.to_thread(
            save_channel_photo_file_id,
            post_id,
            photo_file_id,
        )
    except Exception:
        logger.exception("Could not cache photo file_id for post %s", post_id)


def _navigation_keyboard(has_previous=False, has_next=False):
    buttons = []
    if has_previous:
        buttons.append(
            InlineKeyboardButton("السابق", callback_data="ai_previous")
        )
    if has_next:
        buttons.append(
            InlineKeyboardButton("التالي", callback_data="ai_next")
        )
    if not buttons:
        return None
    return InlineKeyboardMarkup([buttons])


def _post_content(post):
    content = (post.get("content") or post.get("title") or "").strip()
    return content or "لا يوجد نص محفوظ لهذا العرض."


def _split_text(text, limit=4096):
    return [
        text[index:index + limit]
        for index in range(0, len(text), limit)
    ] or [""]


async def _send_text_chunks(bot, chat_id, chunks, reply_markup=None):
    sent_messages = []
    for index, chunk in enumerate(chunks):
        sent_messages.append(
            await bot.send_message(
                chat_id=chat_id,
                text=chunk,
                reply_markup=reply_markup if index == 0 else None,
            )
        )
    return sent_messages


async def _send_text_post(bot, chat_id, content, reply_markup=None):
    return await _send_text_chunks(
        bot,
        chat_id,
        _split_text(content),
        reply_markup,
    )


async def _download_source_photo(post, context):
    monitor = context.application.bot_data.get("channel_monitor")
    if not monitor:
        return None
    try:
        return await monitor.download_photo(
            post["source_channel_id"],
            post["source_message_id"],
        )
    except Exception:
        logger.exception("Could not download source photo for post %s", post.get("id"))
        return None


async def _load_post_photo(post, context, allow_source_download=True):
    photo = post.get("photo_file_id")
    if photo:
        return photo, False
    if not allow_source_download:
        return None, False
    photo = await _download_source_photo(post, context)
    return photo, photo is not None


def _photo_to_input_file(photo, post, downloaded_source):
    if not downloaded_source:
        return photo
    return InputFile(
        photo,
        filename=f"channel-post-{post.get('id', 'image')}.jpg",
    )


def _caption_for_content(content):
    return content if len(content) <= 1024 else "📦"


async def _record_auxiliary_messages(context, messages):
    context.user_data["ai_search_auxiliary_message_ids"] = [
        message.message_id
        for message in messages
        if getattr(message, "message_id", None)
    ]


async def _delete_auxiliary_messages(bot, chat_id, context):
    message_ids = context.user_data.pop("ai_search_auxiliary_message_ids", [])
    for message_id in message_ids:
        try:
            await bot.delete_message(chat_id=chat_id, message_id=message_id)
        except Exception:
            logger.debug(
                "Could not delete auxiliary AI result message %s",
                message_id,
                exc_info=True,
            )


async def send_stored_post(
    chat_id,
    context,
    post,
    has_previous=False,
    has_next=False,
    allow_source_download=True,
):
    """Send the stored post without adding a custom content template."""
    bot = context.bot
    content = _post_content(post)
    photo, downloaded_source = await _load_post_photo(
        post,
        context,
        allow_source_download=allow_source_download,
    )
    navigation = _navigation_keyboard(has_previous, has_next)

    if photo:
        try:
            photo_to_send = _photo_to_input_file(photo, post, downloaded_source)
            sent = await bot.send_photo(
                chat_id=chat_id,
                photo=photo_to_send,
                caption=_caption_for_content(content),
                reply_markup=navigation,
            )
            if sent.photo:
                file_id = sent.photo[-1].file_id
                if downloaded_source or not post.get("photo_file_id"):
                    await _cache_photo_file_id(post["id"], file_id)
            if len(content) > 1024:
                auxiliary = await _send_text_post(bot, chat_id, content)
                await _record_auxiliary_messages(context, auxiliary)
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
                            caption=_caption_for_content(content),
                            reply_markup=navigation,
                        )
                        if sent.photo:
                            await _cache_photo_file_id(
                                post["id"],
                                sent.photo[-1].file_id,
                            )
                        if len(content) > 1024:
                            auxiliary = await _send_text_post(
                                bot,
                                chat_id,
                                content,
                            )
                            await _record_auxiliary_messages(context, auxiliary)
                        return sent
                    except Exception:
                        logger.exception(
                            "Could not send downloaded fallback photo for post %s",
                            post.get("id"),
                        )

    sent_messages = await _send_text_post(bot, chat_id, content, navigation)
    if len(sent_messages) > 1:
        await _record_auxiliary_messages(context, sent_messages[1:])
    return None


async def _replace_stored_post_message(query, context, post, has_previous, has_next):
    bot = context.bot
    message = query.message
    chat_id = message.chat.id
    message_id = message.message_id
    content = _post_content(post)
    # Navigation must never wait for a new MTProto media download. A cached
    # Bot API file_id is still used, while uncached posts are shown as text.
    photo, downloaded_source = await _load_post_photo(
        post,
        context,
        allow_source_download=False,
    )
    navigation = _navigation_keyboard(has_previous, has_next)

    await _delete_auxiliary_messages(bot, chat_id, context)

    if photo and getattr(message, "photo", None):
        edited = await bot.edit_message_media(
            chat_id=chat_id,
            message_id=message_id,
            media=InputMediaPhoto(
                media=_photo_to_input_file(photo, post, downloaded_source),
                caption=_caption_for_content(content),
            ),
            reply_markup=navigation,
        )
        if getattr(edited, "photo", None):
            if downloaded_source or not post.get("photo_file_id"):
                await _cache_photo_file_id(
                    post["id"],
                    edited.photo[-1].file_id,
                )
    elif not photo and not getattr(message, "photo", None):
        chunks = _split_text(content)
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=chunks[0],
            reply_markup=navigation,
        )
        if len(chunks) > 1:
            auxiliary = await _send_text_chunks(bot, chat_id, chunks[1:])
            await _record_auxiliary_messages(context, auxiliary)
    else:
        # Telegram cannot convert a text message to media (or vice versa) in
        # place. Delete only this exceptional type-changing message, then
        # render the replacement once.
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
        sent = await send_stored_post(
            chat_id,
            context,
            post,
            has_previous=has_previous,
            has_next=has_next,
            allow_source_download=False,
        )
        return sent

    if photo and len(content) > 1024:
        auxiliary = await _send_text_post(bot, chat_id, content)
        await _record_auxiliary_messages(context, auxiliary)
    return None


async def ask_ai_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await _activate_ai_search(query.message, context)


async def handle_ai_search_button_message(update, context):
    if context.user_data.get("ai_search_active"):
        return False

    text = (update.effective_message.text or "").strip()
    if text != AI_SEARCH_BUTTON_TEXT:
        return False

    await _activate_ai_search(update.effective_message, context)
    return True


async def handle_ai_search_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("ai_search_active"):
        return False

    text = (update.effective_message.text or "").strip()
    if extract_aliexpress_url(text):
        _clear_ai_search_state(context)
        _restore_ai_search_keyboard(context)
        return False

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

    # Keep the ranked posts in memory for the whole search session. Re-reading
    # each result by id made every navigation click wait for a new DB
    # connection, and could also fail when the retention cleanup ran between
    # the search and a later click.
    context.user_data["ai_search_results"] = posts
    context.user_data["ai_search_index"] = 0
    await send_stored_post(
        update.effective_chat.id,
        context,
        posts[0],
        has_previous=False,
        has_next=len(posts) > 1,
    )
    return True


async def _navigate_ai_results(update, context, direction):
    query = update.callback_query
    await query.answer()

    async with _navigation_lock(context):
        results = context.user_data.get("ai_search_results", [])
        current_index = context.user_data.get("ai_search_index", 0)
        index = current_index + direction
        if index < 0 or index >= len(results):
            return

        result = results[index]
        # Accept the former id-only state as a compatibility path for an
        # update already in flight during a deployment. New searches store
        # complete posts and avoid this database round trip.
        if isinstance(result, dict):
            post = result
        else:
            post = await asyncio.to_thread(get_channel_post, result)
        if not post:
            await query.message.reply_text("تعذر العثور على العرض التالي.")
            return

        try:
            await _replace_stored_post_message(
                query,
                context,
                post,
                has_previous=index > 0,
                has_next=index < len(results) - 1,
            )
        except Exception:
            logger.exception("Could not display AI search result at index %s", index)
            await query.message.reply_text(
                "تعذر عرض هذا العرض حاليًا، حاول الضغط على التالي مرة أخرى."
            )
            return

        # Advance only after the new result has been rendered successfully.
        context.user_data["ai_search_index"] = index


async def ai_next_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _navigate_ai_results(update, context, 1)


async def ai_previous_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _navigate_ai_results(update, context, -1)