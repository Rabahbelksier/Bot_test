import re
import logging
from bs4 import BeautifulSoup

from core.cache import scrape_cache, scrape_cache_lock
from utils.http import _http_session

logger = logging.getLogger(__name__)


def get_product_details_scraping(product_id):
    cache_key = f"scrape_{product_id}"

    try:
        cached = scrape_cache.get(cache_key)
    except Exception:
        cached = None
    if cached is not None:
        return cached

    try:
        url = f"https://www.aliexpress.com/item/{product_id}.html"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9,ar;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
            "Cache-Control": "no-cache",
            "Referer": "https://www.aliexpress.com/",
        }

        response = _http_session.get(url, headers=headers, timeout=12)
        response.raise_for_status()

        title = None
        image_url = None

        try:
            script_tags = re.findall(r'<script[^>]*>(.*?)</script>', response.text, re.DOTALL)
            for script in script_tags:
                if not title:
                    title_match = re.search(r'"subject"\s*:\s*"([^"]+)"', script)
                    if title_match:
                        title = title_match.group(1)
                if not image_url:
                    img_match = re.search(r'"imageUrl"\s*:\s*"([^"]+)"', script)
                    if not img_match:
                        img_match = re.search(r'"imagePathList"\s*:\s*\[\s*"([^"]+)"', script)
                    if img_match:
                        image_url = img_match.group(1)
                if title and image_url:
                    break
        except Exception as e:
            logger.error(f"Error parsing JavaScript: {e}")

        if not title or not image_url:
            soup = BeautifulSoup(response.content, 'html.parser')

            if not title:
                meta_title = soup.find('meta', {'property': 'og:title'})
                if meta_title:
                    title = meta_title.get('content', '')

            if not title:
                title_tag = soup.find('title')
                if title_tag:
                    raw_title = title_tag.get_text(strip=True)
                    if raw_title and 'AliExpress' not in raw_title[:10]:
                        title = raw_title.split('|')[0].split('-')[0].strip()

            if not image_url:
                meta_image = soup.find('meta', {'property': 'og:image'})
                if meta_image:
                    image_url = meta_image.get('content')

            if not image_url:
                for img in soup.find_all('img'):
                    src = img.get('src') or img.get('data-src') or ''
                    if 'ae01.alicdn.com' in src or 'cbu01.alicdn.com' in src:
                        image_url = src
                        break

        if image_url and image_url.startswith('//'):
            image_url = f"https:{image_url}"

        result = {
            'title': title.strip()[:255] if title else None,
            'image_url': image_url
        }
        if result.get('title') or result.get('image_url'):
            with scrape_cache_lock:
                scrape_cache[cache_key] = result
        return result
    except Exception as e:
        logger.error(f"Error in scraping: {e}")
        return {'title': None, 'image_url': None}
