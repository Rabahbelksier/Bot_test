import logging
import re
from decimal import Decimal, InvalidOperation

logger = logging.getLogger(__name__)

_COUPON_PATTERN = re.compile(r"(\d+(?:[.,]\d+)?)\s*[/|]\s*(\d+(?:[.,]\d+)?)")
_COUPON_CODE_PATTERN = re.compile(r"^cod_(\d+)$")


def parse_numeric_value(value):
    """Parse a decimal value from prices and coupon fields."""
    try:
        if isinstance(value, Decimal):
            return value
        text = str(value or "").strip().replace("\u066c", "").replace("\u066b", ".")
        match = re.search(r"-?\d[\d\s.,]*", text)
        if not match:
            return None
        number = match.group(0).replace(" ", "")
        if "," in number and "." in number:
            # Treat the last separator as the decimal separator.
            decimal_separator = "," if number.rfind(",") > number.rfind(".") else "."
            thousands_separator = "." if decimal_separator == "," else ","
            number = number.replace(thousands_separator, "").replace(decimal_separator, ".")
        elif "," in number:
            number = number.replace(",", ".")
        return Decimal(number)
    except (InvalidOperation, TypeError, ValueError):
        return None


def parse_coupon_value(value):
    match = _COUPON_PATTERN.search(str(value or ""))
    if not match:
        return None
    discount = parse_numeric_value(match.group(1))
    threshold = parse_numeric_value(match.group(2))
    if discount is None or threshold is None or discount <= 0 or threshold <= 0:
        return None
    return {
        "discount": discount,
        "threshold": threshold,
        "label": f"{match.group(1)}/{match.group(2)}$",
    }


def _query_rows(query, params=()):
    conn = None
    try:
        from core.db import get_db_connection

        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute(query, params)
            columns = [description[0] for description in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]
    except Exception as exc:
        logger.warning("Coupon database query failed: %s", exc)
        return []
    finally:
        if conn:
            conn.close()


def _coupon_codes_from_row(row):
    code_columns = sorted(
        (
            (int(match.group(1)), column)
            for column in row
            if (match := _COUPON_CODE_PATTERN.match(column))
        ),
        key=lambda item: item[0],
    )
    return [
        str(row[column]).strip()
        for _, column in code_columns
        if row.get(column) is not None and str(row[column]).strip()
    ]


def get_available_coupons():
    """Return DZ coupons grouped by value, including every available code."""
    rows = _query_rows(
        "SELECT * FROM coupon_codes "
        "WHERE LOWER(COALESCE(country, '')) = 'dz' AND value IS NOT NULL "
        "ORDER BY id"
    )
    coupons_by_label = {}
    for row in rows:
        parsed = parse_coupon_value(row.get("value"))
        if not parsed:
            continue

        coupon = coupons_by_label.setdefault(
            parsed["label"],
            {**parsed, "codes": [], "_seen_codes": set()},
        )
        for code in _coupon_codes_from_row(row):
            if code not in coupon["_seen_codes"]:
                coupon["codes"].append(code)
                coupon["_seen_codes"].add(code)

    coupons = []
    for coupon in coupons_by_label.values():
        coupon.pop("_seen_codes", None)
        coupons.append(coupon)
    return coupons


def get_best_coupon_for_price(coupons, current_price):
    """Return the highest-value DZ coupon applicable to the current price.

    A coupon is applicable when its threshold is less than or equal to the
    product's current sale price. Coupons without promotional codes are
    ignored because the details message must include usable codes.
    """
    price = parse_numeric_value(current_price)
    if price is None:
        return None

    eligible = [
        coupon
        for coupon in coupons
        if coupon.get("codes")
        and coupon.get("threshold") is not None
        and coupon["threshold"] <= price
    ]
    if not eligible:
        return None

    return max(
        eligible,
        key=lambda coupon: (
            coupon.get("discount", Decimal("0")),
            coupon.get("threshold", Decimal("0")),
        ),
    )