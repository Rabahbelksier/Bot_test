import re
import logging
from urllib.parse import parse_qs, unquote, urljoin, urlparse

from core.cache import cache, cache_lock
from utils.http import _http_session

logger = logging.getLogger(__name__)

_URL_PATTERNS = [
    r'[?&]productIds=(\d+)',
    r'[?&]productId=(\d+)',
    r'/item/(\d+)\.(?:html|htm)',
    r'/item/(\d+)(?:\?|$)',
    r'/product/(\d+)',
    r'/i/(\d+)',
    r'/p/[^/]+/index\.html[?&]productIds=(\d+)',
    r'/ssr/.*?[?&]productIds=(\d+)',
    r'/[a-z0-9]+\.html\?.*?productId(?:s)?=(\d+)',
]

_ALIEXPRESS_URL_PATTERN = re.compile(
    r'https?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\(\),]|'
    r'(?:%[0-9a-fA-F][0-9a-fA-F]))+'
)
_ALIEXPRESS_DOMAINS = ('aliexpress.com', 'alix.live', 's.click.aliexpress.com')
_SHORT_LINK_HOSTS = {'a.aliexpress.com', 's.click.aliexpress.com', 'alix.live'}
_REDIRECT_STATUSES = {301, 302, 303, 307, 308}
_SHORT_LINK_HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Linux; Android 13; Pixel 7) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/120.0.0.0 Mobile Safari/537.36'
    ),
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.5',
}


def extract_aliexpress_urls(text):
    """Return all unique AliExpress URLs in their original order."""
    urls = []
    seen = set()
    for url in _ALIEXPRESS_URL_PATTERN.findall(text or ""):
        if not any(domain in url for domain in _ALIEXPRESS_DOMAINS):
            continue
        normalized = url.rstrip('.,!?;:)]}\'"')
        if normalized and normalized not in seen:
            seen.add(normalized)
            urls.append(normalized)
    return urls


def extract_aliexpress_url(text):
    return next(iter(extract_aliexpress_urls(text)), None)


def _match_product_id_from_url(url):
    for pattern in _URL_PATTERNS:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


def _is_short_link(url):
    try:
        hostname = (urlparse(url).hostname or '').lower()
    except ValueError:
        return False
    return hostname in _SHORT_LINK_HOSTS


def _decode_redirect_value(value):
    decoded = value
    # AliExpress sometimes nests the destination URL more than once.
    for _ in range(3):
        next_value = unquote(decoded)
        if next_value == decoded:
            break
        decoded = next_value
    return decoded


def _extract_product_id_from_redirect(url):
    """Extract a product ID from a URL or an embedded redirect destination."""
    product_id = _match_product_id_from_url(url)
    if product_id:
        return product_id

    try:
        query = parse_qs(urlparse(url).query)
    except ValueError:
        return None

    for parameter in ('xman_goto', 'redirectUrl', 'redirect_url', 'url'):
        for value in query.get(parameter, ()):
            decoded = _decode_redirect_value(value)
            product_id = _match_product_id_from_url(decoded)
            if product_id:
                return product_id
    return None


def _extract_product_id_from_short_link(url):
    """Follow AliExpress short links one redirect at a time.

    A regular requests redirect-follow can end in an AliExpress cookie-sync
    loop. Manual hops let us stop as soon as the product ID is available while
    preserving the session cookies that AliExpress sets between hops.
    """
    current_url = url
    visited_urls = set()

    for _ in range(12):
        if current_url in visited_urls:
            logger.warning("Redirect loop while resolving AliExpress URL: %s", current_url)
            break
        visited_urls.add(current_url)

        try:
            response = _http_session.get(
                current_url,
                headers=_SHORT_LINK_HEADERS,
                allow_redirects=False,
                timeout=8,
            )
        except Exception as exc:
            logger.warning("Could not resolve AliExpress short link %s: %s", url, exc)
            break

        location = response.headers.get('location')
        if location:
            next_url = urljoin(current_url, location)

            # Check embedded destinations before generic URL matching. This
            # avoids mistaking tracking numbers for a product ID.
            product_id = _extract_product_id_from_redirect(next_url)
            if product_id:
                return product_id

            current_url = next_url
            if response.status_code not in _REDIRECT_STATUSES:
                break
            continue

        # Some AliExpress endpoints return a 200 page instead of a Location
        # header. The product URL is then often present in the HTML.
        product_id = _extract_product_id_from_redirect(response.url)
        if not product_id:
            product_id = _extract_product_id_from_redirect(response.text or '')
        if product_id:
            return product_id
        break

    return None


def extract_product_id(text):
    cache_key = f"pid_{text}"

    try:
        cached = cache.get(cache_key)
    except Exception:
        cached = None
    if cached is not None:
        return cached

    if not any(domain in text for domain in ['aliexpress.com', 'alix.live', 's.click.aliexpress.com']):
        return None

    direct_match = _match_product_id_from_url(text)
    if direct_match:
        with cache_lock:
            cache[cache_key] = direct_match
        return direct_match

    if _is_short_link(text):
        short_link_match = _extract_product_id_from_short_link(text)
        if short_link_match:
            with cache_lock:
                cache[cache_key] = short_link_match
            return short_link_match

    try:
        response = _http_session.head(
            text,
            allow_redirects=True,
            timeout=8,
            headers={'User-Agent': _SHORT_LINK_HEADERS['User-Agent']},
        )
        candidates = [response.url]
        candidates.extend(item.url for item in response.history)
        candidates.extend(
            item.headers.get('location')
            for item in response.history
            if item.headers.get('location')
        )
    except Exception:
        candidates = [text]

    result = next(
        (
            product_id
            for candidate in candidates
            if candidate and (
                product_id := _extract_product_id_from_redirect(candidate)
            )
        ),
        None,
    )
    if result:
        with cache_lock:
            cache[cache_key] = result
    return result
