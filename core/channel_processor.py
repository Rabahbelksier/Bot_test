import asyncio
import logging
import re

from core.ai import GeminiRateLimitError, analyze_channel_post
from core.affiliate import generate_affiliate_link
from core.db import create_channel_post, update_channel_post
from config import CHANNEL_TELEGRAM_REPLACEMENT_LINK
from utils.parser import extract_aliexpress_urls, extract_product_id

logger = logging.getLogger(__name__)

_TELEGRAM_LINK_PATTERN = re.compile(
    r"https?://(?:t\.me|telegram\.me)/[^\s<>()]+",
    re.IGNORECASE,
)


def rewrite_post_text(text, affiliate_links):
    """Replace Telegram and AliExpress links without changing other text."""
    rewritten = _TELEGRAM_LINK_PATTERN.sub(
        CHANNEL_TELEGRAM_REPLACEMENT_LINK,
        text or "",
    )
    for original, replacement in affiliate_links.items():
        rewritten = rewritten.replace(original, replacement)
    return rewritten


def build_source_link(channel_username, message_id, channel_id=None):
    if not channel_username:
        if channel_id and str(channel_id).startswith("-100"):
            return f"https://t.me/c/{str(channel_id)[4:]}/{message_id}"
        return None
    return f"https://t.me/{channel_username.lstrip('@')}/{message_id}"


async def _generate_affiliate_replacements(urls):
    semaphore = asyncio.Semaphore(3)

    async def generate(url):
        async with semaphore:
            return url, await asyncio.to_thread(generate_affiliate_link, url)

    generated = await asyncio.gather(*(generate(url) for url in urls))
    failed = [url for url, replacement in generated if not replacement]
    if failed:
        raise RuntimeError(f"Affiliate link generation failed for {len(failed)} URL(s)")
    return dict(generated)


async def process_channel_message(
    message,
    channel_id,
    channel_username=None,
):
    """Analyze one MTProto channel post and persist its modified copy."""
    text = getattr(message, "message", None) or getattr(message, "raw_text", "") or ""
    message_id = getattr(message, "id", None)
    if not channel_id or not message_id:
        logger.warning("Ignoring channel post without source identifiers")
        return None

    urls = extract_aliexpress_urls(text)
    if not urls:
        logger.info(
            "Skipping channel post %s/%s because it has no AliExpress link",
            channel_id,
            message_id,
        )
        return None

    source_link = build_source_link(channel_username, message_id, channel_id)
    photo_file_id = getattr(message, "photo_file_id", None)
    post_id = create_channel_post(
        source_channel_id=channel_id,
        source_message_id=message_id,
        source_link=source_link,
        published_at=getattr(message, "date", None),
        photo_file_id=photo_file_id,
    )
    if post_id is None:
        logger.info("Skipping already processed channel post %s/%s", channel_id, message_id)
        return None

    try:
        analysis = await asyncio.to_thread(analyze_channel_post, text)
        if not analysis["is_offer"]:
            update_channel_post(
                post_id,
                content=text,
                processing_status="ignored",
            )
            return post_id

        replacements = await _generate_affiliate_replacements(urls)
        modified_text = rewrite_post_text(text, replacements)
        product_id = (
            await asyncio.to_thread(extract_product_id, urls[0])
            if urls
            else None
        )
        update_channel_post(
            post_id,
            title=analysis["title"],
            price=analysis["price"],
            content=modified_text,
            processing_status="processed",
            aliexpress_product_id=product_id,
        )
        return post_id
    except GeminiRateLimitError:
        # A quota response is retryable; keep the source text and let the next
        # history sync retry it instead of permanently marking it as failed.
        update_channel_post(
            post_id,
            content=text,
            processing_status="pending",
        )
        logger.warning(
            "Gemini rate limit for channel post %s/%s; queued for retry",
            channel_id,
            message_id,
        )
        return post_id
    except Exception:
        # Keep the original Telegram text available for diagnosis/retry even
        # when AI or affiliate-link processing fails.
        update_channel_post(
            post_id,
            content=text,
            processing_status="failed",
        )
        logger.exception("Failed to process channel post %s/%s", channel_id, message_id)
        return post_id