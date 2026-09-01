import asyncio
import html
import logging
import re
from decimal import Decimal

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from config import TRACKING_ID
from core.api import prepare_api_params, send_api_request_with_retry
from core.coupons import (
    get_available_coupons,
    parse_coupon_value,
    parse_numeric_value,
)
from core.db import get_db_connection
from services.queue_manager import enqueue_url
from utils.parser import extract_aliexpress_url

logger = logging.getLogger(__name__)

SELLER_COUPON_IMAGE_URL = "https://iili.io/CyapHdP.jpg"
SELLER_DISCOUNT_IMAGE_URL = "https://iili.io/CyamX0N.jpg"
CURRENCY_DISCOUNT_IMAGE_URL = "https://iili.io/Cyajigt.jpg"


def _query_rows(query, params=()):
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute(query, params)
            columns = [description[0] for description in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]
    except Exception as exc:
        logger.warning("Smart cart database query failed: %s", exc)
        return []
    finally:
        if conn:
            conn.close()


def get_cart_products():
    rows = _query_rows(
        "SELECT linkcart, pricecart, pricefinalecart, ship, stor FROM cart "
        "WHERE linkcart IS NOT NULL ORDER BY ctid"
    )
    products = []
    for index, row in enumerate(rows):
        original = parse_numeric_value(row.get("pricecart"))
        final = parse_numeric_value(row.get("pricefinalecart"))
        if original is None or original <= 0:
            logger.warning("Ignoring invalid cart row at position %s", index + 1)
            continue
        if final is None or final < 0:
            # pricecart is the value used to find a qualifying combination.
            # Keep the row usable and use the original value for the final
            # allocation until the admin fills pricefinalecart.
            logger.warning(
                "Cart row %s has no valid pricefinalecart; using pricecart for allocation",
                index + 1,
            )
            final = original
        stor = row.get("stor")
        stor_text = str(stor).strip() if stor is not None else ""
        if not stor_text:
            # Keep rows with missing data usable without creating a false
            # conflict, while making the missing value visible to operators.
            stor_key = f"missing:{index + 1}"
            logger.warning("Cart row %s has no stor value", index + 1)
        else:
            stor_number = parse_numeric_value(stor_text)
            stor_key = (
                f"number:{stor_number}"
                if stor_number is not None
                else f"text:{stor_text.casefold()}"
            )
        shipping = parse_numeric_value(row.get("ship"))
        if shipping is None or shipping < 0:
            if row.get("ship") not in (None, ""):
                logger.warning(
                    "Cart row %s has no valid ship value; using zero",
                    index + 1,
                )
            shipping = Decimal("0")
        products.append({
            "link": row["linkcart"],
            "price": original,
            "final_price": final,
            "shipping": shipping,
            "position": index + 1,
            "stor": stor_text or None,
            "stor_key": stor_key,
        })
    return products


def fetch_current_price(product_id):
    params = prepare_api_params("aliexpress.affiliate.productdetail.get", {
        "product_ids": product_id,
        "target_currency": "USD",
        "target_language": "EN",
        "country": "DZ",
        "tracking_id": TRACKING_ID,
        "fields": "product_title,product_main_image_url,target_sale_price,app_sale_price",
    })
    data = send_api_request_with_retry(params, max_retries=2)
    raw = (
        data.get("aliexpress_affiliate_productdetail_get_response", {})
        .get("resp_result", {}).get("result", {}).get("products", {}).get("product")
    )
    if not raw:
        return None
    product = raw[0] if isinstance(raw, list) else raw
    return parse_numeric_value(
        product.get("target_sale_price", product.get("app_sale_price"))
    )


def generate_qualifying_combinations(products, required):
    """Generate every valid additional-products combination.

    The first cart row is special: it may be selected with a quantity from
    one to five. Every other row can be selected once. A product can appear in
    multiple different combinations; the stor constraint applies only inside
    one combination.
    """
    if required <= 0 or not products:
        return []

    maximum = required + Decimal("15")
    fallback = next((product for product in products if product["position"] == 1), None)
    candidates = [product for product in products if product is not fallback]
    combinations = []

    def add_if_qualifying(selected, total):
        if required <= total <= maximum:
            combinations.append({
                "additions": list(selected),
                "added_original_total": total,
            })

    def search(index, total, selected, used_stors):
        if total > maximum:
            return
        if index == len(candidates):
            if fallback is None or fallback["stor_key"] in used_stors:
                add_if_qualifying(selected, total)
                return

            # Quantity zero represents a combination without the fallback.
            add_if_qualifying(selected, total)
            for quantity in range(1, 6):
                fallback_total = fallback["price"] * quantity
                if total + fallback_total > maximum:
                    break
                add_if_qualifying(
                    selected + [{"product": fallback, "quantity": quantity}],
                    total + fallback_total,
                )
            return

        product = candidates[index]
        # Excluding a product is always valid and allows it in other results.
        search(index + 1, total, selected, used_stors)

        if product["stor_key"] in used_stors:
            return
        included_total = total + product["price"]
        if included_total <= maximum:
            search(
                index + 1,
                included_total,
                selected + [{"product": product, "quantity": 1}],
                used_stors | {product["stor_key"]},
            )

    search(0, Decimal("0"), [], set())
    if not combinations:
        logger.info(
            "No smart cart combinations found: required=%s maximum=%s candidate_prices=%s",
            required,
            maximum,
            [product["price"] for product in candidates],
        )
    return combinations


def choose_additional_products(products, required):
    """Backward-compatible wrapper returning the first generated combination."""
    combinations = generate_qualifying_combinations(products, required)
    if not combinations:
        return None
    first = combinations[0]
    return first["additions"], first["added_original_total"]


def _sum_additional_shipping(additions):
    """Return shipping for selected extra products, including quantities."""
    total = Decimal("0")
    for item in additions:
        shipping = parse_numeric_value(item["product"].get("shipping"))
        if shipping is None or shipping < 0:
            continue
        total += shipping * item["quantity"]
    return total


def calculate_offer(main_after_discount, coupon, additions, shipping):
    extra_final_total = sum(item["product"]["final_price"] * item["quantity"] for item in additions)
    extra_shipping_total = _sum_additional_shipping(additions)
    coupon_base = main_after_discount + extra_final_total
    if coupon_base <= 0:
        return None
    # Shipping is not part of the goods total used to divide the coupon.
    partial_coupon = (main_after_discount / coupon_base) * coupon["discount"]
    main_after_coupon = main_after_discount - partial_coupon
    final_price = main_after_coupon + shipping
    total_after_discount = (
        coupon_base - coupon["discount"] + shipping + extra_shipping_total
    )
    return {
        "extra_final_total": extra_final_total,
        "extra_shipping_total": extra_shipping_total,
        "partial_coupon": partial_coupon,
        "final_price": final_price,
        "total_after_discount": total_after_discount,
    }


def _extract_main_product_links(message_text):
    """Read the two main-product links from the original bot response."""
    links = {}
    for link_type, label in (
        ("coins", "عرض المنتج في صفحة العملات"),
        ("direct", "رابط مباشر للمنتج"),
    ):
        match = re.search(
            rf"{re.escape(label)}\s*:\s*(https?://[^\s<]+)",
            message_text or "",
        )
        if match:
            links[link_type] = html.unescape(match.group(1)).rstrip(".,")
    return links


def _get_initial_offer_image_id(message):
    """Keep the image already delivered with the initial offer."""
    photos = getattr(message, "photo", None) or []
    if not photos:
        return None
    return photos[-1].file_id


def _get_saved_initial_offer_image(context, product_id, message):
    """Return the initial offer image, preferring Telegram's stored file."""
    initial_offer_file_id = _get_initial_offer_image_id(message)
    if initial_offer_file_id:
        return initial_offer_file_id
    product_image_file_ids = context.user_data.get("product_image_file_ids", {})
    saved_file_id = product_image_file_ids.get(str(product_id))
    if saved_file_id:
        return saved_file_id
    product_images = context.user_data.get("product_images", {})
    return product_images.get(str(product_id))


def _offer_lines(state, offer, offer_number, total_offers):
    result = offer["result"]
    price_total_cart = (
        state["current_price"]
        + offer["added_original_total"]
        + state["shipping"]
        + result.get("extra_shipping_total", Decimal("0"))
    )
    price_total_final_cart = result["total_after_discount"]

    def main_product_link(link_type):
        link = state.get("main_links", {}).get(link_type)
        if not link:
            return "المنتج الرئيسي"
        return f'<a href="{html.escape(link, quote=True)}">المنتج الرئيسي</a>'

    lines = [
        "🛒 <b>عرض السلة الذكية AI</b>",
        f"📦 التجميعة: <b>{offer_number} من {total_offers}</b>",
        f"💰 السعر النهائي للمنتج الرئيسي: <b>{result['final_price']:.2f}$</b>",
        f"🎟️ الكوبون: <b>{state['coupon']['label']}</b>",
        f"💸 نصيب المنتج الرئيسي من الكوبون: {result['partial_coupon']:.2f}$",
        "➕ أضف منتجك الرئيسي الى السلة",
        f"🔗 رابط عملات: {main_product_link('coins')}",
        f"🔗 رابط مباشر: {main_product_link('direct')}",
        "",
        "➕ أضف المنتجات التالية إلى السلة:",
    ]
    for item in offer["additions"]:
        product = item["product"]
        quantity = item["quantity"]
        quantity_text = f" — الكمية: {quantity}" if quantity > 1 else " — الكمية: 1"
        lines.append(
            f"• <a href=\"{html.escape(product['link'], quote=True)}\">"
            f"منتج إضافي</a>{quantity_text}"
        )
    lines.extend([
        "",
        f"📦 اجمالي أسعار المنتجات قبل التخفيض: {price_total_cart:.2f}$",
        f"📦 اجمالي أسعار المنتجات بعد التخفيض: {price_total_final_cart:.2f}$",
        "",
        "📎رابط بوت طريقة السلة الذكية (منشئ التجميعات):",
        "http://t.me/rabahcoupons1bot",
        "",
        "🛑 خطوات تطبيق طريقة السلة الذكية:",
        "🔸قم بوضع الهاتف والمنتجات الاضافية مع بعض في السلة",
        "🔸انتقل الى صفحة الدفع",
        "🔸ادفع ببطاقة فارغة او مجمدة",
        "🔸بعدها قم بالرجوع الى الطلبات المعلقة وقم بدفع منتجك الرئيسي فقط والغي المنتجات الاضافية",
        "🔸لاتنسى حجز كوبونات البائع للمنتجات الاضافية والمنتج الرئيسي ان وجدت",
        "🔸اذا استعملت رابط العملات لمنتجك الرئيسي بدلا من الرابط المباشر قم بتغيير دولة التطبيق دولة اجنبية للاستفادة من تخفيض العملات",
        "🔸عند تغيير الدولة يجب التاكد من ان المنتجات الاضافية والمنتج الرئيسي تتوفر على شحن الى تلك الدول وذالك فقط لتستطيع الدخول الى صفحة الدفع",
    ])
    return lines


def _offer_keyboard(offer_number, total_offers):
    if offer_number >= total_offers:
        return None
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(
            "🔄 تجميعة أخرى",
            callback_data=f"smart_other_{offer_number}",
        )
    ]])


async def _send_saved_offer(message, state, offer_number):
    total_offers = len(state["offers"])
    lines = _offer_lines(
        state,
        state["offers"][offer_number],
        offer_number + 1,
        total_offers,
    )
    reply_markup = _offer_keyboard(offer_number + 1, total_offers)
    image_url = state.get("image_url")
    offer_text = "\n".join(lines)
    if image_url:
        bot_link = "http://t.me/rabahcoupons1bot"
        try:
            split_index = lines.index(bot_link)
        except ValueError:
            split_index = None

        photo_lines = lines if split_index is None else lines[:split_index + 1]
        continuation_lines = [] if split_index is None else lines[split_index + 1:]
        photo_caption = "\n".join(photo_lines)
        continuation_text = "\n".join(continuation_lines).lstrip("\n")

        try:
            await message.reply_photo(
                photo=image_url,
                caption=photo_caption,
                parse_mode="HTML",
            )
        except Exception as photo_error:
            logger.error("Failed to send smart cart photo: %s", photo_error)
        else:
            if continuation_text:
                await message.reply_text(
                    continuation_text,
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                    reply_markup=reply_markup,
                )
            return

    await message.reply_text(
        offer_text,
        parse_mode="HTML",
        disable_web_page_preview=True,
        reply_markup=reply_markup,
    )


async def _reply_with_image(message, text, image_url, parse_mode=None):
    """Send an instructional prompt with a safe text fallback."""
    try:
        return await message.reply_photo(
            photo=image_url,
            caption=text,
            parse_mode=parse_mode,
        )
    except Exception as photo_error:
        logger.error("Failed to send smart cart instruction image: %s", photo_error)
        return await message.reply_text(
            text,
            parse_mode=parse_mode,
            disable_web_page_preview=True,
        )


def _track_input_prompt(state, prompt_message):
    """Remember bot messages that belong to the current value prompt."""
    if prompt_message is None:
        return
    state.setdefault("input_prompt_message_ids", []).append(prompt_message.message_id)


async def _delete_input_prompts(context, state):
    """Delete the active value prompt and any correction messages."""
    chat_id = state.get("chat_id")
    message_ids = state.pop("input_prompt_message_ids", [])
    if chat_id is None:
        return

    for message_id in message_ids:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
        except Exception:
            # The user may have already deleted a message or Telegram may have
            # expired the deletion window. Neither case should interrupt the flow.
            logger.debug("Unable to delete smart cart prompt %s", message_id)


async def _send_input_prompt(message, state, text, image_url=None, parse_mode=None):
    """Send and track a smart cart value prompt."""
    if image_url:
        prompt_message = await _reply_with_image(
            message,
            text,
            image_url,
            parse_mode=parse_mode,
        )
    else:
        prompt_message = await message.reply_text(
            text,
            parse_mode=parse_mode,
            disable_web_page_preview=True,
        )
    _track_input_prompt(state, prompt_message)
    return prompt_message


async def start_smart_cart(update, context, product_id):
    query = update.callback_query
    await query.answer()
    coupons = await asyncio.to_thread(get_available_coupons)
    if not coupons:
        await query.message.reply_text("في انتظار توفر كوبونات علي اكسبراس لتشتغل طريقة السلة الذكية⏳")
        return

    products = await asyncio.to_thread(get_cart_products)
    if not products:
        await query.message.reply_text("⚠️🛒 طريقة السلة الذكية AI متوقفة مؤقتًا\nسيتم تفعيلها خلال تخفيضات مناسبة لها وعند توفر كوبونات فعّالة 🎟️🔥")
        return

    try:
        current_price = await asyncio.to_thread(fetch_current_price, product_id)
    except Exception:
        current_price = None
    message_text = query.message.caption or query.message.text or ""
    context.user_data["smart_cart"] = {
        "product_id": product_id,
        "current_price": current_price,
        "coupons": coupons,
        "products": products,
        "main_links": _extract_main_product_links(message_text),
        "image_url": _get_saved_initial_offer_image(context, product_id, query.message),
        "chat_id": query.message.chat_id,
        "input_prompt_message_ids": [],
    }
    if current_price is not None and current_price <= 50:
        await query.message.reply_text("لا يمكن استعمال طريقة السلة الذكية على هذا المنتج")
        context.user_data.pop("smart_cart", None)
        return

    if current_price is None:
        context.user_data["smart_cart"]["state"] = "price"
        await _send_input_prompt(
            query.message,
            context.user_data["smart_cart"],
            "لم أستطع استخراج سعر المنتج. أرسل سعر المنتج الرئيسي بالدولار:",
        )
        return
    await _show_coupon_choices(query.message, context)


async def _show_coupon_choices(message, context):
    state = context.user_data["smart_cart"]
    state["state"] = "coupon"
    eligible = [coupon for coupon in state["coupons"] if coupon["threshold"] > state["current_price"]]
    if not eligible:
        await message.reply_text("لا توجد كوبونات مناسبة لسعر هذا المنتج حاليا")
        context.user_data.pop("smart_cart", None)
        return
    state["coupons"] = eligible
    keyboard = [
        [InlineKeyboardButton(coupon["label"], callback_data=f"smart_coupon_{index}")]
        for index, coupon in enumerate(eligible)
    ]
    await message.reply_text(
        "🎟️ اختر الكوبون الذي تريد استعماله:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def select_coupon(update, context):
    query = update.callback_query
    await query.answer()
    state = context.user_data.get("smart_cart")
    if not state:
        await query.message.reply_text("انتهت جلسة السلة الذكية. أرسل رابط المنتج من جديد.")
        return
    index = int(query.data.rsplit("_", 1)[1])
    if index >= len(state["coupons"]):
        await query.message.reply_text("هذا الكوبون لم يعد متاحا. أعد المحاولة.")
        return
    state["coupon"] = state["coupons"][index]
    state["state"] = "seller_discount"
    await query.edit_message_reply_markup(reply_markup=None)
    codes = state["coupon"]["codes"][:3]
    codes_text = "\n".join(f"• <code>{html.escape(str(code))}</code>" for code in codes) or "غير متوفرة"
    await _send_input_prompt(
        query.message,
        state,
        f"✅ اخترت الكوبون <b>{state['coupon']['label']}</b>\n"
        f"الأكواد التابعة للكوبون:\n{codes_text}\n\n"
        "أرسل الآن قيمة كوبون البائع بالدولار (أرسل 0 إذا لم يوجد).",
        SELLER_COUPON_IMAGE_URL,
        parse_mode="HTML",
    )


async def handle_smart_cart_message(update, context):
    state = context.user_data.get("smart_cart")
    if not state:
        return False

    target_url = extract_aliexpress_url(update.message.text or "")
    if target_url:
        await _delete_input_prompts(context, state)
        context.user_data.pop("smart_cart", None)
        context.user_data.pop("smart_cart_offers", None)
        await enqueue_url(update.effective_chat.id, target_url, context)
        return True

    if state.get("state") == "coupon":
        await update.message.reply_text(
            "🎟️ <b>اختيار الكوبون</b>\n\n"
            "يرجى اختيار أحد أزرار الكوبونات الظاهرة في الرسالة السابقة.\n"
            "لا تقم بكتابة قيمة أو رقم الكوبون في هذه المرحلة.\n\n"
            "بعد اختيار الكوبون سيطلب منك البوت إدخال قيمة كوبون البائع.",
            parse_mode="HTML",
        )
        return True

    text = (update.message.text or "").strip().replace(",", ".").replace("$", "")
    value = parse_numeric_value(text)
    if value is None or value < 0:
        await _send_input_prompt(
            update.message,
            state,
            "⚠️ أرسل قيمة رقمية صحيحة بالدولار.",
        )
        return True
    if state["state"] == "price":
        if value <= 50:
            await _send_input_prompt(
                update.message,
                state,
                "لا يمكن استعمال طريقة السلة الذكية على هذا المنتج",
            )
            context.user_data.pop("smart_cart", None)
            return True
        await _delete_input_prompts(context, state)
        state["current_price"] = value
        state["state"] = "coupon"
        await _show_coupon_choices(update.message, context)
    elif state["state"] == "seller_discount":
        await _delete_input_prompts(context, state)
        state["seller_discount"] = value
        state["state"] = "automatic_discount"
        await _send_input_prompt(
            update.message,
            state,
            "أرسل الآن قيمة التخفيض التلقائي بالدولار (أرسل 0 إذا لم يوجد).",
            SELLER_DISCOUNT_IMAGE_URL,
        )
    elif state["state"] == "automatic_discount":
        await _delete_input_prompts(context, state)
        state["automatic_discount"] = value
        state["state"] = "currency_discount"
        await _send_input_prompt(
            update.message,
            state,
            "أرسل الآن قيمة تخفيض العملات بالدولار (أرسل 0 إذا لم يوجد).",
            CURRENCY_DISCOUNT_IMAGE_URL,
        )
    elif state["state"] == "currency_discount":
        await _delete_input_prompts(context, state)
        state["currency_discount"] = value
        state["state"] = "shipping"
        await _send_input_prompt(
            update.message,
            state,
            "أرسل قيمة رسوم الشحن بالدولار (أرسل 0 إذا لم توجد).",
        )
    elif state["state"] == "shipping":
        await _delete_input_prompts(context, state)
        state["shipping"] = value
        await _build_smart_cart_offer(update, context)
    return True


def _calculate_smart_cart_offers(state, main_after_discount):
    combinations = generate_qualifying_combinations(
        state["products"],
        state["coupon"]["threshold"] - state["current_price"],
    )
    offers = []
    for combination in combinations:
        result = calculate_offer(
            main_after_discount,
            state["coupon"],
            combination["additions"],
            state["shipping"],
        )
        if result:
            offers.append({**combination, "result": result})
    offers.sort(key=lambda offer: offer["result"]["partial_coupon"], reverse=True)
    return offers


async def _build_smart_cart_offer(update, context):
    state = context.user_data["smart_cart"]
    loading = await update.message.reply_text("⏳ جاري تجهيز العرض AI")
    try:
        main_after_discount = (
            state["current_price"]
            - state["seller_discount"]
            - state["automatic_discount"]
            - state.get("currency_discount", Decimal("0"))
        )
        if main_after_discount <= 0:
            await loading.edit_text("⚠️ يجب أن يكون السعر بعد التخفيضات الأولية أكبر من صفر.")
            return
        offers = await asyncio.to_thread(
            _calculate_smart_cart_offers,
            state,
            main_after_discount,
        )
        if not offers:
            await loading.edit_text("لا توجد منتجات اضافية مناسبة لمنتجك")
            return

        await loading.delete()
        saved_state = {
            **state,
            "offers": offers,
            "next_offer_index": 1,
        }
        if len(offers) == 1:
            await _send_saved_offer(update.message, saved_state, 0)
            context.user_data.pop("smart_cart_offers", None)
        else:
            context.user_data["smart_cart_offers"] = saved_state
            await _send_saved_offer(update.message, saved_state, 0)
    except Exception:
        logger.exception("Smart cart offer failed")
        await loading.edit_text("❌ حدث خطأ أثناء تجهيز عرض السلة الذكية.")
    finally:
        context.user_data.pop("smart_cart", None)


async def other_smart_cart_callback(update, context):
    query = update.callback_query
    state = context.user_data.get("smart_cart_offers")
    if not state:
        await query.answer("انتهت جلسة التجميعات.", show_alert=True)
        return

    try:
        requested_index = int(query.data.rsplit("_", 1)[1])
    except (IndexError, ValueError):
        await query.answer("تعذر تحديد التجميعة المطلوبة.", show_alert=True)
        return

    next_index = state.get("next_offer_index", 0)
    if requested_index != next_index or requested_index >= len(state["offers"]):
        await query.answer("هذه التجميعة لم تعد متاحة.", show_alert=True)
        return

    await query.answer()
    await query.edit_message_reply_markup(reply_markup=None)
    await _send_saved_offer(query.message, state, requested_index)
    state["next_offer_index"] = requested_index + 1
    if state["next_offer_index"] >= len(state["offers"]):
        context.user_data.pop("smart_cart_offers", None)
