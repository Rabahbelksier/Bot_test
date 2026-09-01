from telegram import InlineKeyboardMarkup


def markup_without_callback(markup, callback_data):
    """Return a keyboard without the pressed callback button."""
    if not markup:
        return None

    remaining_rows = [
        [
            button
            for button in row
            if getattr(button, "callback_data", None) != callback_data
        ]
        for row in markup.inline_keyboard
    ]
    remaining_rows = [row for row in remaining_rows if row]
    return InlineKeyboardMarkup(remaining_rows) if remaining_rows else None


async def remove_pressed_button(query):
    """Remove only the callback button used by the current query."""
    markup = markup_without_callback(
        getattr(query.message, "reply_markup", None),
        query.data,
    )
    if markup is not None or getattr(query.message, "reply_markup", None):
        await query.edit_message_reply_markup(reply_markup=markup)