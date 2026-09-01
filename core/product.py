import logging

from config import TRACKING_ID
from core.api import prepare_api_params, send_api_request_with_retry

logger = logging.getLogger(__name__)


def parse_product_data(product_data):
    try:
        product = product_data['aliexpress_affiliate_productdetail_get_response']['resp_result']['result']['products'].get('product')
        if not product:
            return {}
        p = product[0] if isinstance(product, list) else product
        sale_price = p.get('target_sale_price', p.get('app_sale_price', 'غير متوفر'))
        original_price = p.get('target_original_price', p.get('original_price', 'غير متوفر'))
        discount = p.get('target_discount', 'غير محسوب')
        if discount == 'غير محسوب' and original_price != 'غير متوفر' and sale_price != 'غير متوفر':
            try:
                original = float(str(original_price).replace('USD', '').replace('$', '').strip())
                sale = float(str(sale_price).replace('USD', '').replace('$', '').strip())
                if original > 0:
                    discount = f"{((original - sale) / original) * 100:.1f}%"
            except Exception:
                pass
        shop_url = p.get('shop_url', 'غير متوفر')
        if '/store/' in shop_url:
            try:
                store_id = shop_url.split('/store/')[1].split('/')[0].split('?')[0]
                shop_url = f"https://m.aliexpress.com/store/{store_id}?shopId={store_id}"
            except Exception:
                pass
        return {
            'product_title': p.get('product_title', 'غير متوفر'),
            'target_sale_price': f"{sale_price} USD",
            'target_original_price': f"{original_price} USD",
            'target_discount': discount,
            'lastest_volume': p.get('lastest_volume', 'غير متوفر'),
            'shop_name': p.get('shop_name', 'غير متوفر'),
            'evaluate_rate': p.get('evaluate_rate', 'غير متوفر'),
            'shop_url': shop_url,
            'first_level_category_name': p.get('first_level_category_name', 'غير محدد'),
            'second_level_category_name': p.get('second_level_category_name', 'غير محدد'),
            'commission_rate': p.get('commission_rate', 'غير محدد')
        }
    except Exception:
        return {}


def get_product_info_from_api(product_id):
    try:
        params = prepare_api_params('aliexpress.affiliate.productdetail.get', {
            'product_ids': product_id,
            'target_currency': 'USD',
            'target_language': 'EN',
            'country': 'DZ',
            'tracking_id': TRACKING_ID,
            'fields': 'product_title,product_main_image_url'
        })
        data = send_api_request_with_retry(params, max_retries=2)
        if 'error_response' in data:
            logger.error(f"API error in get_product_info_from_api: {data['error_response'].get('msg', 'unknown')}")
            return None
        product = (
            data.get('aliexpress_affiliate_productdetail_get_response', {})
                .get('resp_result', {})
                .get('result', {})
                .get('products', {})
                .get('product')
        )
        if not product:
            return None
        p = product[0] if isinstance(product, list) else product
        title = p.get('product_title', '')
        image_url = p.get('product_main_image_url', '')
        if image_url and image_url.startswith('//'):
            image_url = f"https:{image_url}"
        if not title and not image_url:
            return None
        return {
            'title': title.strip()[:255] if title else 'غير متوفر',
            'image_url': image_url if image_url else None
        }
    except Exception as e:
        logger.error(f"Error in get_product_info_from_api: {e}")
        return None
