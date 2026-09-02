# AliExpress Telegram Bot

## Overview
Telegram bot that generates affiliate links for AliExpress products. Users send product URLs and receive discount offers with affiliate links. Configured to run on Render.com using Webhook mode with Flask and PostgreSQL.

## Project Structure (Modular Architecture)

```
├── main.py                    # Entry point only: Flask app, Telegram handlers registration, webhook
├── config.py                  # All environment variables and constants
│
├── core/
│   ├── api.py                 # AliExpress API: signature, params, retry requests
│   ├── product.py             # Product data: fetch and parse from API
│   ├── affiliate.py           # Affiliate link generation (batched, ThreadPoolExecutor)
│   ├── scraper.py             # Scraping fallback (BeautifulSoup + regex)
│   ├── cache.py               # TTLCache instances and locks
│   ├── coupons.py             # Shared coupon query and value/code grouping
│   └── db.py                  # PostgreSQL: init_db, users, and admin cart mutations
│
├── handlers/
│   ├── start.py               # /start command handler
│   ├── coupons.py             # /coupons command and coupon callback
│   ├── admin.py               # Protected cart management flow and admin callbacks
│   ├── messages.py            # Incoming message handler
│   └── callbacks.py           # Inline button callbacks (product details and Smart Cart)
│
├── services/
│   ├── worker.py              # process_link_for_user: full pipeline for one URL
│   └── queue_manager.py       # Per-user asyncio queues, enqueue_url, worker loop
│
└── utils/
    ├── http.py                # Shared requests.Session with connection pooling
    ├── parser.py              # extract_product_id (regex + manual short-link resolution, HEAD fallback)
    └── formatter.py           # format_product_message (Markdown output)
```

## Smart Cart AI
- The existing offer flow remains unchanged; its result now includes a separate Smart Cart AI button.
- Smart Cart uses the `coupon_codes` rows where `country = 'dz'` and thresholds exceed the main product price.
- It guides the user through seller discount, automatic discount, and shipping inputs, then generates every qualifying combination from `cart` in a worker thread.
- Each combination uses `pricecart` for coupon eligibility, must total from the coupon threshold through threshold + $15, and cannot contain two products with the same `stor`.
- The first cart row is reserved for the $1 item and may be used in quantities from 1 to 5; all other products can be used once per combination.
- Products may be reused across different combinations. Results are ranked by the main product's partial coupon, with one result shown at a time and a `تجميعة أخرى` button for the remaining results.
- `cart.pricefinalecart` stores the additional product price after the seller coupon and remains the value used for partial-coupon allocation.
- The feature requires the existing `DATABASE_URL`; no new credentials are needed.

## Admin Cart Management
- `/admin` without the access code replies with the existing admin contact message.
- `/admin <access code>` enables a per-user admin session and sends one message per `cart` row.
- Each row is displayed as `id | link | pricecart | pricefinalcart | stor | ship`; the `link` label is a clickable blue link and the stored URL is shown below it.
- The `تعديل` button requests a complete row, while `إضافة` inserts a complete new row. Both operations refresh the displayed cart after a successful database commit.
- `خروج` clears the admin session so subsequent text follows the normal product-link flow.
- The existing database column `pricefinalecart` is used internally for the `pricefinalcart` value to preserve Smart Cart compatibility.

## Architecture
- **main.py**: Lean Flask entry point — only app setup, handler registration, webhook config
- **API**: AliExpress Affiliate API (`api-sg.aliexpress.com/sync`)
- **Scraping**: BeautifulSoup fallback for product info (cached 3600s)
- **Database**: PostgreSQL via psycopg2 for user storage
- **Deployment**: Render.com with gunicorn

## Flow
1. User sends AliExpress URL → `handlers/messages.py` → `services/queue_manager.py`
2. Queue worker calls `services/worker.py` → `process_link_for_user`
3. `utils/parser.py` extracts product ID (regex first, manual short-link redirects, then HEAD fallback)
4. `core/product.py` fetches title & image via API concurrently with `core/affiliate.py`
5. Falls back to `core/scraper.py` if API returns no useful info
6. Sends message with product image, title, and 8 offer links
7. User clicks "تفاصيل المنتج الكاملة" → `handlers/callbacks.py` → full product API response

## Environment Variables
- `APP_KEY`: AliExpress API key
- `APP_SECRET`: AliExpress API secret
- `TRACKING_ID`: Affiliate tracking ID
- `TELEGRAM_TOKEN`: Telegram bot token
- `EXTERNAL_DATABASE_URL`: Preferred PostgreSQL connection string for the
  external application database
- `DATABASE_URL`: Fallback PostgreSQL connection string
- `PORT`: Server port (default 5000)
- `RENDER_EXTERNAL_URL`: Render external URL for webhook setup
- `GEMINI_API_KEY`: Gemini API key for channel analysis and natural-language offer search
- `GEMINI_MODEL`: Optional Gemini model name (default: `gemini-2.0-flash`)
- `TELEGRAM_API_ID`: Telegram API ID for the dedicated monitoring account
- `TELEGRAM_API_HASH`: Telegram API hash for the dedicated monitoring account
- `TELEGRAM_SESSION_STRING`: Authorized StringSession for the dedicated monitoring account
- `CHANNEL_TELEGRAM_REPLACEMENT_LINK`: Optional replacement for Telegram links in stored copies

## Database Schema
- **user_bot** table: first_name (TEXT), last_name (TEXT), chat_id (BIGINT PRIMARY KEY)

## Deployment Files
- `requirements.txt`: Python dependencies
- `Procfile`: `web: gunicorn main:app`

## Performance Optimizations
- **ThreadPoolExecutor(5)**: Reduced from 10 → less CPU pressure
- **Batched link generation**: 8 requests split into 2 batches of 4 (no burst)
- **TTLCache**: maxsize=400 / ttl=600s for main cache; maxsize=200 / ttl=3600s for scraping
- **Lock-free reads**: cache reads use no lock (Python GIL safe), writes are locked
- **Direct regex matching**: product ID extracted from URL before any HTTP call
- **Shared HTTP session**: connection pooling with keep-alive reuse
- **Queue cleanup**: user queues deleted after draining to prevent memory leaks
- **Concurrent fetch**: product info + link generation run via asyncio.gather simultaneously

## Recent Changes
- 2026-02-12: Converted from polling to Webhook mode with Flask
- 2026-02-12: Added PostgreSQL database integration for user storage
- 2026-02-12: Added save_user function with ON CONFLICT DO NOTHING for duplicate prevention
- 2026-04-11: Major performance optimization — parallel link generation + concurrent product fetch/links
- 2026-04-16: Performance optimizations: reduced threads, improved cache, batched requests, lock-free reads
- 2026-04-16: Refactored to modular architecture (core/, handlers/, services/, utils/)

## Channel monitoring and AI search
- `telegram_channels` intentionally contains only `id` and `link`; links are resolved by
  the MTProto monitor at startup.
- `statu` stores the modified post copy, processing state, source identifiers, publication
  date, and `photo_file_id`. Duplicate source channel/message pairs are ignored.
- The original channel post is never edited. Telegram links in the stored copy are replaced
  with `CHANNEL_TELEGRAM_REPLACEMENT_LINK`, and every AliExpress URL is affiliate-generated.
- A Telegram user `StringSession` is required because Bot API membership is not used for
  monitoring. The bot remains responsible for user messages and replies.
- With MTProto monitoring, the source account's media identifier is not a Bot API
  `file_id`. The monitor downloads a photo on first user delivery; the bot then caches
  the returned Bot API `photo_file_id` in `statu` for later deliveries.
- If `TELEGRAM_SESSION_STRING` is not available yet, run
  `python scripts/create_telegram_session.py` after setting `TELEGRAM_API_ID` and
  `TELEGRAM_API_HASH`; complete the one-time Telegram login, then copy the generated
  file contents into the secret and delete the local file.
