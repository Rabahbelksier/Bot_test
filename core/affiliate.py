import logging
import time
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

from config import APP_KEY, APP_SECRET, TRACKING_ID, API_URL
from core.api import generate_api_signature
from core.cache import cache, cache_lock
from utils.http import _http_session

logger = logging.getLogger(__name__)

_link_executor = ThreadPoolExecutor(max_workers=5)


def _generate_single_link(url_to_try, max_retries=2):
    for attempt in range(max_retries):
        try:
            params = {
                "method": "aliexpress.affiliate.link.generate",
                "app_key": APP_KEY,
                "sign_method": "sha256",
                "timestamp": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
                "v": "2.0",
                "format": "json",
                "tracking_id": TRACKING_ID,
                "promotion_link_type": "0",
                "source_values": url_to_try
            }
            params['sign'] = generate_api_signature(params, APP_SECRET)

            response = _http_session.get(API_URL, params=params, timeout=8)
            response.raise_for_status()
            data = response.json()

            if 'error_response' in data:
                err = data['error_response']
                code = err.get('code', '')
                msg = err.get('msg', '')
                logger.warning(f"API error on link generation (attempt {attempt + 1}): [{code}] {msg}")
                if code == 'ApiCallLimit':
                    wait = 5.5 if '5 seconds' in msg else 1.5
                    if attempt < max_retries - 1:
                        time.sleep(wait)
                        continue
                return None

            result = (
                data.get('aliexpress_affiliate_link_generate_response', {})
                    .get('resp_result', {})
                    .get('result', {})
            )
            if result.get('promotion_links'):
                return result['promotion_links']['promotion_link'][0]['promotion_link']
            return None

        except requests.exceptions.Timeout:
            logger.warning(f"Timeout generating link (attempt {attempt + 1}): {url_to_try}")
            if attempt < max_retries - 1:
                time.sleep(0.5)
                continue
        except Exception as e:
            logger.error(f"Error generating link (attempt {attempt + 1}): {e}")
            if attempt < max_retries - 1:
                time.sleep(0.5)
                continue

    return None


def generate_affiliate_link(url):
    """Generate one affiliate link for a product or store URL."""
    if not url or not isinstance(url, str):
        return None
    return _generate_single_link(url)


def _generate_one_offer(index, name, primary_url, secondary_url):
    affiliate_link = _generate_single_link(primary_url)
    if affiliate_link is None and secondary_url:
        affiliate_link = _generate_single_link(secondary_url)
    if affiliate_link:
        return index, f"{name}:\n{affiliate_link}"
    return index, f"{name}:\n❌ فشل التوليد من المصدر"


def generate_affiliate_links(product_id):
    cache_key = f"links_{product_id}"

    try:
        cached = cache.get(cache_key)
    except Exception:
        cached = None
    if cached is not None:
        return cached

    offers = [
        (
            "💥عرض المنتج في صفحة العملات",
            f"https://m.aliexpress.com/p/coin-index/index.html?_immersiveMode=true&tabname=configTab_1926001&productIds={product_id}",
            f"https://m.aliexpress.com/p/coin-index/index.html?_immersiveMode=true&tabname=configTab_1926001&productIds={product_id}",
        ),
        (
            "💥رابط مباشر للمنتج",
            f"https://www.aliexpress.com/item/{product_id}.html?sourceType=620",
            f"https://star.aliexpress.com/share/share.htm?redirectUrl=https://www.aliexpress.com/item/{product_id}.html?sourceType=620",
        ),
        (
            "💥عرض Super Deals",
            f"https://www.aliexpress.com/item/{product_id}.html?sourceType=562",
            f"https://star.aliexpress.com/share/share.htm?redirectUrl=https://www.aliexpress.com/item/{product_id}.html?sourceType=562",
        ),
        (
            "💥عرض تخفيض Big Save",
            f"https://www.aliexpress.com/item/{product_id}.html?sourceType=680",
            f"https://star.aliexpress.com/share/share.htm?redirectUrl=https://www.aliexpress.com/item/{product_id}.html?sourceType=680",
        ),
        (
            "💥عرض التخفيض المحدود",
            f"https://www.aliexpress.com/item/{product_id}.html?sourceType=561",
            f"https://star.aliexpress.com/share/share.htm?redirectUrl=https://www.aliexpress.com/item/{product_id}.html?sourceType=561",
        ),
        (
            "💥عرض التخفيض المحتمل",
            f"https://www.aliexpress.com/item/{product_id}.html?sourceType=504",
            f"https://star.aliexpress.com/share/share.htm?redirectUrl=https://www.aliexpress.com/item/{product_id}.html?sourceType=504",
        ),
        (
            "💥عرض مباشر للباندل ",
            f"https://www.aliexpress.com/item/{product_id}.html?sourceType=570",
            f"https://star.aliexpress.com/share/share.htm?redirectUrl=https://www.aliexpress.com/item/{product_id}.html?sourceType=570",
        ),
        (
            "💥عرض المنتج في صفحة الباندل",
            f"https://www.aliexpress.com/ssr/300000512/BundleDeals2?&pha_manifest=ssr&productIds={product_id}",
            f"https://star.aliexpress.com/share/share.htm?redirectUrl=https://www.aliexpress.com/ssr/300000512/BundleDeals2?&pha_manifest=ssr&productIds={product_id}",
        ),
    ]

    results_map = {}
    batch_size = 4

    for batch_start in range(0, len(offers), batch_size):
        batch = offers[batch_start:batch_start + batch_size]
        futures = {
            _link_executor.submit(_generate_one_offer, batch_start + j, name, primary, secondary): batch_start + j
            for j, (name, primary, secondary) in enumerate(batch)
        }
        for future in as_completed(futures):
            try:
                index, text = future.result()
                results_map[index] = text
            except Exception as e:
                idx = futures[future]
                name = offers[idx][0]
                results_map[idx] = f"{name}:\n❌ فشل التوليد من المصدر"
                logger.error(f"Unexpected error for offer {idx}: {e}")

    results = [results_map[i] for i in range(len(offers))]

    with cache_lock:
        cache[cache_key] = results
    return results
