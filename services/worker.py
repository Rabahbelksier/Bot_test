import html
import logging
import asyncio
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from utils.parser import extract_product_id
from core.product import get_product_info_from_api
from core.affiliate import generate_affiliate_links
from core.scraper import get_product_details_scraping
from utils.app_promotion import app_promotion_button
from handlers.ai_search import ai_search_reply_keyboard, ask_ai_button

logger = logging.getLogger(__name__)


async def process_link_for_user(chat_id: int, url: str, context):
    bot = context.bot
    restore_ai_keyboard = context.user_data.pop(
        "restore_ai_search_keyboard",
        False,
    )
    reply_keyboard = ai_search_reply_keyboard() if restore_ai_keyboard else None
    keyboard_was_restored = False
    loading_msg = None

    try:
        product_id = await asyncio.to_thread(extract_product_id, url)
    except Exception:
        logger.exception("Could not extract the product id from %s", url)
        await bot.send_message(
            chat_id=chat_id,
            text="❌ تعذر قراءة رابط المنتج، حاول إرسال الرابط مرة أخرى.",
            reply_markup=reply_keyboard,
        )
        keyboard_was_restored = bool(reply_keyboard)
        return
    if not product_id:
        await bot.send_message(
            chat_id=chat_id,
            text="❌ انسخ رابط المنتج من تطبيق aliexpress او الموقع",
            reply_markup=reply_keyboard,
        )
        keyboard_was_restored = bool(reply_keyboard)
        return

    loading_msg = await bot.send_message(
        chat_id=chat_id,
        text="⏳ جاري البحث عن العروض",
        reply_markup=reply_keyboard,
    )

    try:
        product_task = asyncio.to_thread(get_product_info_from_api, product_id)
        links_task = asyncio.to_thread(generate_affiliate_links, product_id)

        product, links = await asyncio.gather(product_task, links_task)

        if not product or (not product.get('title') or product.get('title') == 'غير متوفر'):
            logger.info(f"API returned insufficient data for {product_id}, trying scraping...")
            scraped = await asyncio.to_thread(get_product_details_scraping, product_id)
            if not product:
                product = {'title': None, 'image_url': None}
            if scraped.get('title'):
                product['title'] = (
                    product.get('title')
                    if product.get('title') and product.get('title') != 'غير متوفر'
                    else scraped['title']
                )
            if scraped.get('image_url') and not product.get('image_url'):
                product['image_url'] = scraped['image_url']

        title = product.get('title') if product and product.get('title') else None
        image_url = product.get('image_url') if product else None
        if image_url:
            product_images = context.user_data.setdefault("product_images", {})
            product_images.pop(str(product_id), None)
            product_images[str(product_id)] = image_url
            while len(product_images) > 20:
                product_images.pop(next(iter(product_images)))

        keyboard = [
            [InlineKeyboardButton("📋 تفاصيل المنتج الكاملة", callback_data=f"details_{product_id}")],
            [InlineKeyboardButton("🛒 استعمال طريقة السلة الذكية AI", callback_data=f"smart_cart_{product_id}")],
            [ask_ai_button()],
            [InlineKeyboardButton("الكوبونات", callback_data="show_coupons")],
            [app_promotion_button()],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        if title:
            response_text = f"📦تخفيض على:\n<code>{html.escape(title)}</code>\n\n" + "\n\n".join(links)
        else:
            response_text = "📦 تخفيض على منتج AliExpress\n\n" + "\n\n".join(links)

        sent_photo = None
        if image_url:
            try:
                sent_photo = await bot.send_photo(
                    chat_id=chat_id,
                    photo=image_url,
                    caption=response_text,
                    parse_mode="HTML",
                    reply_markup=reply_markup,
                )
            except Exception as photo_err:
                logger.error(f"Failed to send photo: {photo_err}")
                await bot.send_message(chat_id=chat_id, text=response_text, parse_mode="HTML", reply_markup=reply_markup)
        else:
            await bot.send_message(chat_id=chat_id, text=response_text, parse_mode="HTML", reply_markup=reply_markup)

        if sent_photo and getattr(sent_photo, "photo", None):
            product_image_file_ids = context.user_data.setdefault(
                "product_image_file_ids", {}
            )
            product_image_file_ids.pop(str(product_id), None)
            product_image_file_ids[str(product_id)] = sent_photo.photo[-1].file_id
            while len(product_image_file_ids) > 20:
                product_image_file_ids.pop(next(iter(product_image_file_ids)))

    except Exception as e:
        logger.error(f"Error processing link {url}: {e}")
        await bot.send_message(chat_id=chat_id, text="❌ حدث خطأ أثناء معالجة طلبك، اتصل بالأدمن @Rabahbelksier")

    finally:
        try:
            if loading_msg:
                await bot.delete_message(
                    chat_id=chat_id,
                    message_id=loading_msg.message_id,
                )
        except Exception:
            pass
        if reply_keyboard and not keyboard_was_restored:
            try:
                await bot.send_message(
                    chat_id=chat_id,
                    text="عاد البوت إلى الوضع العادي، ويمكنك استخدام زر «اسأل الذكاء الاصطناعي».",
                    reply_markup=reply_keyboard,
                )
            except Exception:
                logger.exception("Could not restore the AI search keyboard")
