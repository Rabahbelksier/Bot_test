import asyncio
import html
import logging
from decimal import Decimal, InvalidOperation

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from core.db import (
    get_admin_cart_rows,
    insert_cart_row,
    update_cart_row,
)

logger = logging.getLogger(__name__)

ADMIN_ACCESS_CODE = "Rabah06651024221997"
ADMIN_CONTACT_TEXT = "تواصل مع الادمن @Rabahbelksier"
ADMIN_ROW_TEMPLATE = "id | link | pricecart | pricefinalcart | stor | ship"


def _format_value(value):
    if value is None:
        return "-"
    if isinstance(value, Decimal):
        text = format(value, "f")
        text = text.rstrip("0").rstrip(".")
        return text or "0"
    return str(value)


def format_cart_row(row):
    """Format one row using HTML so the fixed `link` label is clickable and blue."""
    url = str(row.get("linkcart") or "").strip()
    escaped_url = html.escape(url, quote=True)
    escaped_visible_url = html.escape(url)
    link_value = f'<a href="{escaped_url}">link</a>'
    if not url:
        link_value = "link"
        escaped_visible_url = "-"

    values = [
        _format_value(row.get("id")),
        link_value,
        _format_value(row.get("pricecart")),
        _format_value(row.get("pricefinalecart")),
        _format_value(row.get("stor")),
        _format_value(row.get("ship")),
    ]
    row_line = (
        f"{values[0]} | {values[1]} | {values[2]} | {values[3]} | "
        f"{values[4]} | {values[5]}"
    )
    url_line = (
        f'<a href="{escaped_url}">{escaped_visible_url}</a>'
        if url
        else escaped_visible_url
    )
    return f"{row_line}\n{url_line}"


def _row_keyboard(row_id):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("تعديل", callback_data=f"admin_edit_{row_id}")
    ]])


def admin_actions_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("إضافة", callback_data="admin_add")],
        [InlineKeyboardButton("خروج", callback_data="admin_exit")],
    ])


async def send_admin_cart(message):
    """Send the current cart rows followed by the admin actions message."""
    rows = await asyncio.to_thread(get_admin_cart_rows)
    if not rows:
        await message.reply_text("لا توجد أسطر حاليا في جدول cart.")
    else:
        for row in rows:
            await message.reply_text(
                format_cart_row(row),
                parse_mode="HTML",
                disable_web_page_preview=True,
                reply_markup=_row_keyboard(row["id"]),
            )

    await message.reply_text(
        "اختر الإجراء المطلوب:",
        reply_markup=admin_actions_keyboard(),
    )


def _parse_cart_line(text):
    parts = [part.strip() for part in text.split("|")]
    if len(parts) != 6:
        raise ValueError(
            "أرسل السطر بهذا الشكل:\n"
            f"{ADMIN_ROW_TEMPLATE}\n"
            "مثال: 1 | https://example.com | 45.2 | 20 | 2 | 0"
        )

    if not parts[0]:
        raise ValueError("قيمة id مطلوبة.")
    try:
        row_id = int(parts[0])
    except ValueError as exc:
        raise ValueError("قيمة id يجب أن تكون رقما صحيحا.") from exc
    if row_id <= 0:
        raise ValueError("قيمة id يجب أن تكون أكبر من صفر.")

    if not parts[1]:
        raise ValueError("الرابط مطلوب.")

    numeric_values = []
    for label, raw_value in zip(
        ("pricecart", "pricefinalcart", "stor", "ship"),
        parts[2:],
    ):
        try:
            value = Decimal(raw_value)
        except (InvalidOperation, ValueError) as exc:
            raise ValueError(f"قيمة {label} يجب أن تكون رقما.") from exc
        if not value.is_finite() or value < 0:
            raise ValueError(f"قيمة {label} يجب أن تكون رقما موجبا أو صفرا.")
        numeric_values.append(value)

    if numeric_values[0] == 0:
        raise ValueError("قيمة pricecart يجب أن تكون أكبر من صفر.")

    return {
        "id": row_id,
        "link": parts[1],
        "price": numeric_values[0],
        "final_price": numeric_values[1],
        "stor": numeric_values[2],
        "shipping": numeric_values[3],
    }


async def _send_admin_input_prompt(message, action):
    operation = "تعديل" if action == "edit" else "إضافة"
    await message.reply_text(
        f"أرسل سطر {operation} كاملا بهذا القالب:\n"
        f"{ADMIN_ROW_TEMPLATE}\n"
        "ضع الرابط الحقيقي مكان كلمة link.\n"
        "مثال: 1 | https://example.com | 45.2 | 20 | 2 | 0"
    )


async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    supplied_code = " ".join(context.args).strip()
    if supplied_code != ADMIN_ACCESS_CODE:
        await update.message.reply_text(ADMIN_CONTACT_TEXT)
        return

    context.user_data["admin_mode"] = True
    context.user_data.pop("admin_state", None)
    try:
        await send_admin_cart(update.message)
    except Exception:
        logger.exception("Failed to load cart for admin")
        await update.message.reply_text(
            "تعذر استخراج محتوى جدول cart حاليا، حاول مرة أخرى."
        )


async def handle_admin_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text only while the current user is in an admin session."""
    if not context.user_data.get("admin_mode"):
        return False

    message = update.message
    state = context.user_data.get("admin_state")
    if not state:
        await message.reply_text(
            "أنت في وضع الإدارة. استخدم زر تعديل أو إضافة أو اضغط خروج."
        )
        return True

    try:
        parsed = _parse_cart_line(message.text)
        if state["action"] == "edit":
            if parsed["id"] != state["row_id"]:
                raise ValueError(
                    f"يجب أن يبقى id مساويا للسطر الذي اخترته ({state['row_id']})."
                )
            await asyncio.to_thread(
                update_cart_row,
                parsed["id"],
                parsed["link"],
                parsed["price"],
                parsed["final_price"],
                parsed["stor"],
                parsed["shipping"],
            )
            success_text = "تم تعديل السطر وحفظه في قاعدة البيانات."
        else:
            await asyncio.to_thread(
                insert_cart_row,
                parsed["id"],
                parsed["link"],
                parsed["price"],
                parsed["final_price"],
                parsed["stor"],
                parsed["shipping"],
            )
            success_text = "تمت إضافة السطر وحفظه في قاعدة البيانات."
    except ValueError as exc:
        await message.reply_text(f"⚠️ {exc}")
        return True
    except Exception:
        logger.exception("Failed to save admin cart row")
        await message.reply_text(
            "❌ تعذر حفظ السطر. تأكد من أن id غير مكرر عند الإضافة ثم حاول مجددا."
        )
        return True

    context.user_data.pop("admin_state", None)
    await message.reply_text(success_text)
    try:
        await send_admin_cart(message)
    except Exception:
        logger.exception("Failed to refresh cart after admin mutation")
        await message.reply_text(
            "تم الحفظ، لكن تعذر إعادة عرض جدول cart حاليا."
        )
    return True


async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    action_parts = query.data.split("_")
    action = action_parts[1] if len(action_parts) > 1 else ""

    if not context.user_data.get("admin_mode"):
        await query.answer("انتهت جلسة الإدارة، أرسل الأمر من جديد.", show_alert=True)
        return

    await query.answer()
    if action == "exit":
        context.user_data.pop("admin_mode", None)
        context.user_data.pop("admin_state", None)
        try:
            await query.message.edit_reply_markup(reply_markup=None)
        except Exception:
            logger.debug("Could not remove admin action keyboard", exc_info=True)
        await query.message.reply_text("تم الخروج من وضع الإدارة.")
        return

    if action == "add":
        context.user_data["admin_state"] = {"action": "add"}
        await _send_admin_input_prompt(query.message, "add")
        return

    if action == "edit" and len(action_parts) == 3:
        try:
            row_id = int(action_parts[2])
        except ValueError:
            await query.message.reply_text("رقم السطر غير صالح.")
            return
        context.user_data["admin_state"] = {
            "action": "edit",
            "row_id": row_id,
        }
        await _send_admin_input_prompt(query.message, "edit")