import json
import logging
import re
from decimal import Decimal, InvalidOperation

import requests

from config import GEMINI_API_KEY, GEMINI_MODEL

logger = logging.getLogger(__name__)

_GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "{model}:generateContent"
)
_FALLBACK_GEMINI_MODEL = "gemini-2.5-flash"
_REQUEST_TYPES = {
    "product_best",
    "category_cheapest",
    "category_price_range",
    "product_cheapest",
    "product_price_range",
    "trending",
    "unsupported",
}


class GeminiError(RuntimeError):
    """Raised when Gemini cannot return a valid analysis."""


def _parse_json_response(text):
    cleaned = (text or "").strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise GeminiError("Gemini returned invalid JSON") from exc


def _call_gemini(prompt):
    if not GEMINI_API_KEY:
        raise GeminiError("GEMINI_API_KEY is not configured")

    models = [GEMINI_MODEL]
    if GEMINI_MODEL != _FALLBACK_GEMINI_MODEL:
        models.append(_FALLBACK_GEMINI_MODEL)

    for model in models:
        response = requests.post(
            _GEMINI_URL.format(model=model),
            params={"key": GEMINI_API_KEY},
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    "temperature": 0.1,
                    "responseMimeType": "application/json",
                },
            },
            timeout=30,
        )
        if response.status_code == 404 and model != models[-1]:
            logger.warning(
                "Gemini model %s is unavailable; retrying with %s",
                model,
                _FALLBACK_GEMINI_MODEL,
            )
            continue
        response.raise_for_status()
        data = response.json()
        try:
            text = "".join(
                part.get("text", "")
                for part in data["candidates"][0]["content"]["parts"]
            )
        except (KeyError, IndexError, TypeError) as exc:
            raise GeminiError("Gemini returned no usable content") from exc
        result = _parse_json_response(text)
        if not isinstance(result, dict):
            raise GeminiError("Gemini returned a JSON value instead of an object")
        return result


def _coerce_price(value):
    if value in (None, ""):
        return None
    try:
        normalized = re.sub(r"[^\d.-]", "", str(value).replace(",", "."))
        price = Decimal(normalized)
    except (InvalidOperation, ValueError):
        return None
    if price < 0 or price > Decimal("1000000"):
        return None
    return float(price)


def analyze_channel_post(text):
    """Classify a Telegram post and extract its final discounted price."""
    prompt = f"""
حلل منشور Telegram التالي. أعد JSON فقط دون أي شرح.

المطلوب:
- is_offer: true فقط إذا كان المنشور عرضًا حقيقيًا على منتج.
- title: عنوان المنتج المختصر، أو null.
- discounted_price: السعر النهائي بعد التخفيض بالدولار، أو null.
- Ignore posts that are announcements, general news, coupon-only posts,
  or do not describe a specific product offer.
- When several prices exist, choose the final discounted product price,
  not the old price, coupon threshold, shipping cost, or percentage.

النموذج الإجباري:
{{"is_offer": true, "title": "عنوان", "discounted_price": 12.5}}

المنشور:
{text[:12000]}
"""
    result = _call_gemini(prompt)
    return {
        "is_offer": bool(result.get("is_offer")),
        "title": str(result.get("title")).strip()[:500]
        if result.get("title")
        else None,
        "price": _coerce_price(result.get("discounted_price")),
    }


def parse_user_request(text):
    """Turn an Arabic search request into safe database-filter data."""
    prompt = f"""
حوّل طلب البحث العربي التالي إلى JSON فقط دون شرح.

الأنواع المسموحة في request_type:
- product_best: أفضل عرض لمنتج محدد
- category_cheapest: أرخص عروض فئة أو نوع
- category_price_range: عروض فئة ضمن نطاق سعر
- product_cheapest: منتج محدد بأرخص سعر
- product_price_range: منتج محدد ضمن نطاق سعر
- trending: عروض رائجة أو متكررة اليوم
- unsupported: أي طلب خارج هذه الأنواع

أعد النموذج التالي:
{{
  "request_type": "unsupported",
  "keywords": [],
  "min_price": null,
  "max_price": null
}}

ضع كلمات البحث بالعربية والإنجليزية عند الحاجة داخل keywords.
لا تنشئ SQL ولا تضف مفاتيح أخرى.

طلب المستخدم:
{text[:4000]}
"""
    result = _call_gemini(prompt)
    request_type = result.get("request_type")
    if request_type not in _REQUEST_TYPES:
        request_type = "unsupported"

    keywords = result.get("keywords")
    if not isinstance(keywords, list):
        keywords = []

    min_price = _coerce_price(result.get("min_price"))
    max_price = _coerce_price(result.get("max_price"))
    if min_price is not None and max_price is not None and min_price > max_price:
        min_price, max_price = max_price, min_price

    return {
        "request_type": request_type,
        "keywords": [str(item).strip()[:100] for item in keywords[:6] if str(item).strip()],
        "min_price": min_price,
        "max_price": max_price,
    }