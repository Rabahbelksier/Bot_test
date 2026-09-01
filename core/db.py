import logging
import psycopg2
from config import DATABASE_URL

logger = logging.getLogger(__name__)


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
        conn.commit()
        cur.close()
        conn.close()
        logger.info("Database initialized successfully")
    except Exception as e:
        logger.error(f"Database initialization error: {e}")


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
