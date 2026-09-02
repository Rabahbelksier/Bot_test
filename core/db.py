import logging
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
    """Search processed posts using structured, parameterized intent data."""
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
        if not keywords:
            return []

    conditions = ["processing_status = 'processed'"]
    params = []

    if keywords:
        keyword_clauses = []
        for keyword in keywords:
            pattern = f"%{keyword}%"
            if request_type in _PRODUCT_REQUEST_TYPES:
                keyword_clauses.append("title ILIKE %s")
                params.append(pattern)
            else:
                keyword_clauses.append("(title ILIKE %s OR content ILIKE %s)")
                params.extend([pattern, pattern])
        conditions.append("(" + " OR ".join(keyword_clauses) + ")")

    min_price = intent.get("min_price")
    max_price = intent.get("max_price")
    if min_price is not None:
        conditions.append("price >= %s")
        params.append(min_price)
    if max_price is not None:
        conditions.append("price <= %s")
        params.append(max_price)

    if request_type == "trending":
        ordering = (
            "COUNT(*) OVER (PARTITION BY COALESCE(aliexpress_product_id, title)) DESC, "
            "published_at DESC NULLS LAST"
        )
    elif request_type in {"category_cheapest", "product_cheapest", "product_price_range"}:
        ordering = "price ASC NULLS LAST, published_at DESC NULLS LAST"
    else:
        ordering = "published_at DESC NULLS LAST, price ASC NULLS LAST"

    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT id, title, price, content, processing_status,
                       source_link, published_at, photo_file_id,
                       source_channel_id, source_message_id,
                       aliexpress_product_id
                FROM statu
                WHERE {' AND '.join(conditions)}
                ORDER BY {ordering}
                LIMIT %s
                """,
                [*params, max(1, min(int(limit), 20))],
            )
            columns = [description[0] for description in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]
    finally:
        if conn:
            conn.close()


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
