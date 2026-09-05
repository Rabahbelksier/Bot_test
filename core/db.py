import logging
import re
import unicodedata
from difflib import SequenceMatcher

import psycopg2
from config import DATABASE_URL

logger = logging.getLogger(__name__)

_PRODUCT_REQUEST_TYPES = {
    "product_best",
    "product_cheapest",
    "product_price_range",
}
_GENERIC_PRODUCT_KEYWORDS = {
    "product",
    "products",
    "phone",
    "phones",
    "smartphone",
    "smartphones",
    "هاتف",
    "هواتف",
    "جوال",
    "جوالات",
    "موبايل",
    "موبايلات",
    "منتج",
    "منتجات",
}
_CATEGORY_ALIASES = {
    "phones": {
        "phone", "phones", "smartphone", "smartphones", "mobile", "mobiles",
        "هاتف", "هواتف", "جوال", "جوالات", "موبايل", "موبايلات",
    },
    "headphones": {
        "headphone", "headphones", "earphone", "earphones", "earbuds",
        "headset", "سماعة", "سماعات", "ايربودز", "إيربودز",
    },
    "tablets": {"tablet", "tablets", "ipad", "تابلت", "لوحي", "أجهزة لوحية"},
    "laptops": {
        "laptop", "laptops", "notebook", "macbook", "chromebook",
        "حاسوب", "لابتوب", "كمبيوتر محمول",
    },
    "watches": {
        "watch", "watches", "smartwatch", "ساعة", "ساعات", "ذكية",
    },
    "cameras": {"camera", "cameras", "كاميرا", "كاميرات", "تصوير"},
    "gaming": {
        "gaming", "game", "console", "playstation", "xbox", "نينتندو",
        "بلايستيشن", "اكس بوكس", "ألعاب",
    },
    "home": {"home", "kitchen", "منزل", "مطبخ", "منزلية"},
}
_SEARCH_TOKEN_PATTERN = re.compile(r"[\w\u0600-\u06ff]+", re.UNICODE)
_FUZZY_TOKEN_THRESHOLD = 0.72
_SEARCH_CANDIDATE_LIMIT = 500
_MAX_TRENDING_RESULTS = 10
_CATEGORY_BRANDS = {
    "phones": {
        "iphone",
        "samsung", "galaxy", "xiaomi", "redmi", "poco", "pixel",
        "oneplus", "oppo", "realme", "vivo", "honor", "blackview",
        "tcl", "alcatel", "nokia", "motorola", "infinix", "tecno",
    },
}
_ACCESSORY_OR_CONFLICT_TERMS = {
    "watch", "watches", "smartwatch", "tablet", "tablets",
    "headphone", "headphones", "earphone", "earphones", "earbuds",
    "headset", "adapter", "charger", "case", "cover", "cable", "cord",
    "usb", "charging", "power", "hub", "سلك", "كابل", "سماعة",
    "سماعات", "ساعة", "ساعات", "تابلت", "شاحن", "شواحن",
    "جراب", "أغطية",
}


def get_db_connection():
    return psycopg2.connect(DATABASE_URL)


def init_db():
    if not DATABASE_URL:
        logger.warning("DATABASE_URL not set, skipping database initialization")
        return
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS user_bot (
                first_name TEXT,
                last_name TEXT,
                chat_id BIGINT PRIMARY KEY
            )
        """)
        # cart is managed by the administrator. Keep older installations
        # compatible while adding the final seller-coupon price used by AI cart.
        cur.execute("""
            ALTER TABLE IF EXISTS cart
            ADD COLUMN IF NOT EXISTS pricefinalecart NUMERIC(12, 2)
        """)
        cur.execute("""
            ALTER TABLE IF EXISTS cart
            ADD COLUMN IF NOT EXISTS ship NUMERIC(12, 2)
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS telegram_channels (
                id BIGSERIAL PRIMARY KEY,
                link TEXT NOT NULL UNIQUE
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS statu (
                id BIGSERIAL PRIMARY KEY,
                title TEXT,
                price NUMERIC(12, 2),
                content TEXT,
                processing_status TEXT NOT NULL DEFAULT 'pending',
                source_link TEXT,
                published_at TIMESTAMPTZ,
                photo_file_id TEXT,
                source_channel_id BIGINT,
                source_message_id BIGINT,
                aliexpress_product_id TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (source_channel_id, source_message_id)
            )
        """)
        # Keep imported databases compatible with the new channel-post schema.
        for column_definition in (
            "title TEXT",
            "price NUMERIC(12, 2)",
            "content TEXT",
            "processing_status TEXT NOT NULL DEFAULT 'pending'",
            "source_link TEXT",
            "published_at TIMESTAMPTZ",
            "photo_file_id TEXT",
            "source_channel_id BIGINT",
            "source_message_id BIGINT",
            "aliexpress_product_id TEXT",
            "created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP",
        ):
            column_name = column_definition.split()[0]
            cur.execute(
                f"ALTER TABLE IF EXISTS statu ADD COLUMN IF NOT EXISTS "
                f"{column_name} {column_definition[len(column_name) + 1:]}"
            )
        cur.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_statu_source_message
            ON statu (source_channel_id, source_message_id)
        """)
        cur.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_telegram_channels_link
            ON telegram_channels (link)
        """)
        conn.commit()
        cur.close()
        conn.close()
        logger.info("Database initialized successfully")
    except Exception as e:
        logger.error(f"Database initialization error: {e}")


def get_telegram_channel_links():
    """Return configured channel links in database order."""
    if not DATABASE_URL:
        return []
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("SELECT id, link FROM telegram_channels ORDER BY id")
            return [
                {"id": row[0], "link": row[1]}
                for row in cursor.fetchall()
            ]
    finally:
        if conn:
            conn.close()


def get_retryable_channel_posts():
    """Return source identifiers for posts that should be retried."""
    if not DATABASE_URL:
        return []
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT source_channel_id, source_message_id
                FROM statu
                WHERE source_channel_id IS NOT NULL
                  AND source_message_id IS NOT NULL
                  AND (
                      processing_status IN ('failed', 'pending')
                      OR (
                          processing_status = 'processing'
                          AND created_at < CURRENT_TIMESTAMP - INTERVAL '10 minutes'
                      )
                  )
                ORDER BY id
                """
            )
            return [
                {
                    "source_channel_id": row[0],
                    "source_message_id": row[1],
                }
                for row in cursor.fetchall()
            ]
    finally:
        if conn:
            conn.close()


def create_channel_post(
    source_channel_id,
    source_message_id,
    source_link,
    published_at,
    photo_file_id=None,
):
    """Claim a channel post for processing, returning its id once."""
    if not DATABASE_URL:
        return None
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO statu (
                    source_channel_id,
                    source_message_id,
                    source_link,
                    published_at,
                    photo_file_id,
                    processing_status
                )
                VALUES (%s, %s, %s, %s, %s, 'processing')
                ON CONFLICT (source_channel_id, source_message_id)
                DO UPDATE SET processing_status = 'processing'
                WHERE statu.processing_status IN ('failed', 'pending')
                RETURNING id
                """,
                (
                    source_channel_id,
                    source_message_id,
                    source_link,
                    published_at,
                    photo_file_id,
                ),
            )
            row = cursor.fetchone()
        conn.commit()
        return row[0] if row else None
    finally:
        if conn:
            conn.close()


def update_channel_post(post_id, **fields):
    """Update an allow-listed set of processed channel post fields."""
    allowed_fields = {
        "title",
        "price",
        "content",
        "processing_status",
        "source_link",
        "published_at",
        "photo_file_id",
        "aliexpress_product_id",
    }
    updates = [(name, value) for name, value in fields.items() if name in allowed_fields]
    if not updates or not DATABASE_URL:
        return

    assignments = ", ".join(f"{name} = %s" for name, _ in updates)
    values = [value for _, value in updates]
    values.append(post_id)
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute(
                f"UPDATE statu SET {assignments} WHERE id = %s",
                values,
            )
        conn.commit()
    finally:
        if conn:
            conn.close()


def get_channel_post(post_id):
    if not DATABASE_URL:
        return None
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, title, price, content, processing_status,
                       source_link, published_at, photo_file_id,
                       source_channel_id, source_message_id,
                       aliexpress_product_id
                FROM statu
                WHERE id = %s AND processing_status = 'processed'
                """,
                (post_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None
            columns = [description[0] for description in cursor.description]
            return dict(zip(columns, row))
    finally:
        if conn:
            conn.close()


def search_channel_posts(intent, limit=10):
    """Search processed posts with category-aware and typo-tolerant ranking."""
    if not DATABASE_URL:
        return []

    request_type = intent.get("request_type")
    keywords = [
        str(keyword).strip()
        for keyword in intent.get("keywords", [])
        if str(keyword).strip()
    ][:6]
    if request_type in _PRODUCT_REQUEST_TYPES:
        specific_keywords = [
            keyword
            for keyword in keywords
            if keyword.casefold() not in _GENERIC_PRODUCT_KEYWORDS
        ]
        keywords = specific_keywords or keywords

    conditions = ["processing_status = 'processed'"]
    params = []

    min_price = intent.get("min_price")
    max_price = intent.get("max_price")
    if min_price is not None:
        conditions.append("price >= %s")
        params.append(min_price)
    if max_price is not None:
        conditions.append("price <= %s")
        params.append(max_price)

    trending_has_content_filters = (
        request_type == "trending"
        and bool(
            intent.get("category")
            or intent.get("required_specs")
            or _infer_category(None, keywords)
            or any(
                keyword.casefold() not in _GENERIC_PRODUCT_KEYWORDS
                for keyword in keywords
            )
        )
    )

    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            if request_type == "trending" and not trending_has_content_filters:
                # Return one representative offer per product. The product
                # with the most occurrences comes first, and its cheapest
                # processed offer is the representative shown to the user.
                product_key = (
                    "COALESCE("
                    "NULLIF(aliexpress_product_id, ''), "
                    "NULLIF(LOWER(TRIM(title)), ''), "
                    "'post:' || id::text"
                    ")"
                )
                cursor.execute(
                    f"""
                    WITH ranked_posts AS (
                        SELECT id, title, price, content, processing_status,
                               source_link, published_at, photo_file_id,
                               source_channel_id, source_message_id,
                               aliexpress_product_id,
                               COUNT(*) OVER (
                                   PARTITION BY {product_key}
                               ) AS product_occurrences,
                               ROW_NUMBER() OVER (
                                   PARTITION BY {product_key}
                                   ORDER BY price ASC NULLS LAST,
                                            published_at DESC NULLS LAST,
                                            id DESC
                               ) AS product_rank
                        FROM statu
                        WHERE {' AND '.join(conditions)}
                    )
                    SELECT id, title, price, content, processing_status,
                           source_link, published_at, photo_file_id,
                           source_channel_id, source_message_id,
                           aliexpress_product_id
                    FROM ranked_posts
                    WHERE product_rank = 1
                    ORDER BY product_occurrences DESC,
                             price ASC NULLS LAST,
                             published_at DESC NULLS LAST,
                             id DESC
                    LIMIT %s
                    """,
                    [*params, max(1, min(int(limit), _MAX_TRENDING_RESULTS))],
                )
            else:
                cursor.execute(
                    f"""
                    SELECT id, title, price, content, processing_status,
                           source_link, published_at, photo_file_id,
                           source_channel_id, source_message_id,
                           aliexpress_product_id
                    FROM statu
                    WHERE {' AND '.join(conditions)}
                    ORDER BY published_at DESC NULLS LAST
                    LIMIT %s
                    """,
                    [*params, _SEARCH_CANDIDATE_LIMIT],
                )
            columns = [description[0] for description in cursor.description]
            posts = [dict(zip(columns, row)) for row in cursor.fetchall()]
    finally:
        if conn:
            conn.close()

    if request_type == "trending":
        if trending_has_content_filters:
            return _rank_filtered_trending_posts(
                posts,
                intent,
                keywords,
                limit,
            )
        return posts[: max(1, min(int(limit), _MAX_TRENDING_RESULTS))]

    ranked_posts = []
    for position, post in enumerate(posts):
        match_score = _post_match_score(post, intent, keywords)
        if match_score is None:
            continue
        ranked_posts.append((match_score, position, post))

    if request_type in {"category_cheapest", "product_cheapest", "product_price_range"}:
        ranked_posts.sort(
            key=lambda item: (
                -item[0],
                item[2].get("price") is None,
                item[2].get("price") or 0,
                item[1],
            )
        )
    else:
        ranked_posts.sort(key=lambda item: (-item[0], item[1]))

    return [
        post
        for _, _, post in ranked_posts[: max(1, min(int(limit), 20))]
    ]


def _normalize_search_text(value):
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    text = re.sub(r"[\u064b-\u065f\u0670]", "", text)
    text = text.translate(str.maketrans("أإآىة", "ااايت"))
    text = re.sub(r"[_\-/.]+", " ", text)
    return " ".join(_SEARCH_TOKEN_PATTERN.findall(text))


def _search_tokens(value):
    return _normalize_search_text(value).split()


def _similarity_to_title(token, title_tokens):
    if not title_tokens:
        return 0.0
    return max(
        SequenceMatcher(None, token, title_token).ratio()
        for title_token in title_tokens
    )


def _specific_product_score(keywords, title):
    title_normalized = _normalize_search_text(title)
    title_tokens = title_normalized.split()
    if not title_tokens:
        return None

    specific_keywords = [
        keyword
        for keyword in keywords
        if keyword.casefold() not in _GENERIC_PRODUCT_KEYWORDS
    ]
    specific_keywords = specific_keywords or keywords
    if not specific_keywords:
        return None

    scores = []
    for keyword in specific_keywords:
        normalized_keyword = _normalize_search_text(keyword)
        keyword_tokens = [
            token
            for token in normalized_keyword.split()
            if token not in _GENERIC_PRODUCT_KEYWORDS
        ]
        if not keyword_tokens:
            continue
        if normalized_keyword and normalized_keyword in title_normalized:
            scores.append(1.0)
            continue
        token_scores = [
            _similarity_to_title(token, title_tokens)
            for token in keyword_tokens
        ]
        if token_scores and min(token_scores) >= _FUZZY_TOKEN_THRESHOLD:
            scores.append(sum(token_scores) / len(token_scores))

    if not scores:
        return None
    return max(scores)


def _category_score(category, keywords, title):
    title_tokens = set(_search_tokens(title))
    if not title_tokens:
        return None

    if category == "phones" and title_tokens.intersection(
        {
            token
            for term in _ACCESSORY_OR_CONFLICT_TERMS
            for token in _search_tokens(term)
        }
    ):
        return None

    category_terms = _CATEGORY_ALIASES.get(category)
    if category_terms is None:
        category_terms = set(keywords)
    normalized_terms = {
        token
        for term in category_terms
        for token in _search_tokens(term)
    }
    if title_tokens.intersection(normalized_terms):
        return 1.0

    brand_terms = {
        token
        for brand in _CATEGORY_BRANDS.get(category, set())
        for token in _search_tokens(brand)
    }
    if (
        title_tokens.intersection(brand_terms)
        and not title_tokens.intersection(
            {
                token
                for term in _ACCESSORY_OR_CONFLICT_TERMS
                for token in _search_tokens(term)
            }
        )
    ):
        return 0.8
    return None


def _required_specs_match(title, required_specs):
    """Require every explicit RAM/storage condition to appear in the title."""
    if not required_specs:
        return True

    title_text = _normalize_search_text(title)
    compact_title_text = unicodedata.normalize(
        "NFKC",
        str(title or ""),
    ).casefold()
    for spec in required_specs:
        if not isinstance(spec, dict):
            return False
        spec_type = str(spec.get("type") or "").casefold()
        value = str(spec.get("value") or "").casefold()
        match = re.search(r"(\d+(?:\.\d+)?)(gb|tb|g|t)?", value)
        if not match:
            return False
        number = match.group(1)
        unit = match.group(2) or "gb"
        unit_aliases = {
            "gb": r"(?:gb|g|جيجا|جيجابايت)",
            "g": r"(?:gb|g|جيجا|جيجابايت)",
            "tb": r"(?:tb|t|تيرا)",
            "t": r"(?:tb|t|تيرا)",
        }
        unit_pattern = unit_aliases.get(unit, r"(?:gb|g|tb|t)")
        number_pattern = rf"(?<!\d){re.escape(number)}(?:\.0)?"

        if spec_type == "storage":
            if not re.search(
                rf"{number_pattern}\s*{unit_pattern}\b",
                title_text,
            ):
                return False
            continue

        if spec_type != "ram":
            return False

        ram_before = re.search(
            rf"(?:ram|ذاكرة\s*عشوائية|رام)\s*[:+\-/]?\s*"
            rf"{number_pattern}\s*{unit_pattern}?\b",
            title_text,
        )
        ram_after = re.search(
            rf"{number_pattern}\s*{unit_pattern}?\s*"
            rf"(?:ram|ذاكرة\s*عشوائية|رام)\b",
            title_text,
        )
        if not ram_before and not ram_after:
            # Common compact phone-title formats: 12+256GB or 12/256GB.
            compact_ram = re.search(
                rf"{number_pattern}\s*(?:gb|g)?\s*[+/]\s*\d+"
                rf"\s*(?:gb|g)?\b",
                compact_title_text,
            )
            if not compact_ram:
                return False
    return True


def _infer_category(category, keywords):
    if category in _CATEGORY_ALIASES:
        return category

    keyword_tokens = {
        token
        for keyword in keywords
        for token in _search_tokens(keyword)
    }
    for candidate, aliases in _CATEGORY_ALIASES.items():
        normalized_aliases = {
            token
            for alias in aliases
            for token in _search_tokens(alias)
        }
        if keyword_tokens.intersection(normalized_aliases):
            return candidate
    return None


def _post_match_score(post, intent, keywords):
    request_type = intent.get("request_type")
    if not _required_specs_match(
        post.get("title"),
        intent.get("required_specs", []),
    ):
        return None
    if request_type in _PRODUCT_REQUEST_TYPES:
        return _specific_product_score(keywords, post.get("title"))
    if request_type in {"category_cheapest", "category_price_range"}:
        return _category_score(
            _infer_category(intent.get("category"), keywords),
            keywords,
            post.get("title"),
        )
    if request_type == "trending":
        category = _infer_category(intent.get("category"), keywords)
        score = 1.0
        if category:
            category_score = _category_score(
                category,
                keywords,
                post.get("title"),
            )
            if category_score is None:
                return None
            score *= category_score

        specific_keywords = [
            keyword
            for keyword in keywords
            if keyword.casefold() not in _GENERIC_PRODUCT_KEYWORDS
        ]
        if specific_keywords:
            product_score = _specific_product_score(
                specific_keywords,
                post.get("title"),
            )
            if product_score is None:
                return None
            score *= product_score
        return score
    return 1.0


def _rank_filtered_trending_posts(posts, intent, keywords, limit):
    """Apply semantic filters before grouping trending product offers."""
    groups = {}
    for position, post in enumerate(posts):
        if _post_match_score(post, intent, keywords) is None:
            continue
        product_key = (
            post.get("aliexpress_product_id")
            or _normalize_search_text(post.get("title"))
            or f"post:{post.get('id', position)}"
        )
        groups.setdefault(product_key, []).append(post)

    representatives = []
    for group in groups.values():
        representative = min(
            group,
            key=lambda post: (
                post.get("price") is None,
                post.get("price") if post.get("price") is not None else 0,
                -(post.get("id") or 0),
            ),
        )
        representatives.append((len(group), representative))

    representatives.sort(
        key=lambda item: (
            -item[0],
            item[1].get("price") is None,
            item[1].get("price")
            if item[1].get("price") is not None
            else 0,
            -(item[1].get("id") or 0),
        )
    )
    return [
        post
        for _, post in representatives[
            : max(1, min(int(limit), _MAX_TRENDING_RESULTS))
        ]
    ]


def save_channel_photo_file_id(post_id, photo_file_id):
    update_channel_post(post_id, photo_file_id=photo_file_id)


def delete_expired_channel_posts():
    """Delete every channel post older than the three-day retention window."""
    if not DATABASE_URL:
        return 0

    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute(
                """
                DELETE FROM statu
                WHERE created_at < CURRENT_TIMESTAMP - INTERVAL '3 days'
                """
            )
            deleted_rows = cursor.rowcount
        conn.commit()
        return deleted_rows
    except Exception:
        if conn:
            conn.rollback()
        raise
    finally:
        if conn:
            conn.close()


def save_user(chat_id, first_name, last_name):
    if not DATABASE_URL:
        return
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO user_bot (chat_id, first_name, last_name)
            VALUES (%s, %s, %s)
            ON CONFLICT (chat_id) DO NOTHING
        """, (chat_id, first_name, last_name))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        logger.error(f"Error saving user: {e}")


def get_admin_cart_rows():
    """Return cart rows in the order and shape used by the admin interface."""
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT id, linkcart, pricecart, pricefinalecart, stor, ship
                FROM cart
                ORDER BY id
            """)
            columns = [description[0] for description in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]
    finally:
        if conn:
            conn.close()


def _run_cart_mutation(query, params):
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute(query, params)
            affected_rows = cursor.rowcount
        conn.commit()
        return affected_rows
    except Exception:
        if conn:
            conn.rollback()
        raise
    finally:
        if conn:
            conn.close()


def update_cart_row(row_id, link, price, final_price, stor, shipping):
    """Update one cart row and fail if the requested id does not exist."""
    affected_rows = _run_cart_mutation(
        """
            UPDATE cart
            SET linkcart = %s,
                pricecart = %s,
                pricefinalecart = %s,
                stor = %s,
                ship = %s
            WHERE id = %s
        """,
        (link, price, final_price, stor, shipping, row_id),
    )
    if affected_rows != 1:
        raise ValueError("Cart row was not found")


def insert_cart_row(row_id, link, price, final_price, stor, shipping):
    """Insert a cart row using the id supplied in the admin template."""
    _run_cart_mutation(
        """
            INSERT INTO cart
                (id, linkcart, pricecart, pricefinalecart, stor, ship)
            VALUES (%s, %s, %s, %s, %s, %s)
        """,
        (row_id, link, price, final_price, stor, shipping),
    )
