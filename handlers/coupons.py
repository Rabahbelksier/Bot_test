import asyncio
import html

from utils.telegram import remove_pressed_button


NO_COUPONS_TEXT = "❌ لا تتوفر رموز ترويجية حاليا، يرجى المحاولة لاحقا."
TELEGRAM_TEXT_LIMIT = 4000


def _coupon_sections(coupons):
    sections = []
    for coupon in coupons:
        codes = coupon.get("codes", [])
        if not codes:
            continue
        lines = [f"🎟️<b>{html.escape(str(coupon['label']))}</b>🎟️"]
        lines.extend(f"✂️ <code>{html.escape(str(code))}</code>" for code in codes)
        sections.append("\n".join(lines))
    return sections


def format_coupons_message(coupons):
    return "\n\n".join(_coupon_sections(coupons))


def format_coupons_messages(coupons, max_length=TELEGRAM_TEXT_LIMIT):
    """Split a long coupon response without splitting a code line."""
    sections = _coupon_sections(coupons)
    messages = []
    current_lines = []
    current_length = 0

    for section_index, section in enumerate(sections):
        section_lines = section.splitlines()
        if section_index > 0 and current_lines:
            current_length += 1
            current_lines.append("")

        for line in section_lines:
            extra_length = len(line) + (1 if current_lines else 0)
            if current_lines and current_length + extra_length > max_length:
                if current_lines and current_lines[-1] == "":
                    current_lines.pop()
                    current_length -= 1
                messages.append("\n".join(current_lines))
                current_lines = []
                current_length = 0
                extra_length = len(line)
            current_lines.append(line)
            current_length += extra_length

    if current_lines:
        messages.append("\n".join(current_lines))
    return messages


async def send_coupons(message):
    from core.coupons import get_available_coupons

    coupons = await asyncio.to_thread(get_available_coupons)
    messages = format_coupons_messages(coupons)
    if not messages:
        messages = [NO_COUPONS_TEXT]
    for response_text in messages:
        await message.reply_text(
            response_text,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )


async def coupons_command(update, context):
    await send_coupons(update.message)


async def coupons_callback(update, context):
    query = update.callback_query
    await query.answer()
    await remove_pressed_button(query)
    await send_coupons(query.message)
