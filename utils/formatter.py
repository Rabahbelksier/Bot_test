from datetime import datetime


def _format_markdown_code(value):
    # Legacy Telegram Markdown uses backticks for copyable code entities.
    text = str(value).replace("`", "'")
    return f"`{text}`"


def format_product_message(info, coupon=None):
    coupon_lines = ""
    if coupon and coupon.get("codes"):
        codes = " ".join(
            _format_markdown_code(code) for code in coupon["codes"][:3]
        )
        coupon_lines = (
            f"🎟️ **الكوبون:** {coupon['label']}\n"
            f"🎫 **الرموز الترويجية:** {codes}\n\n"
        )

    return f"""📦 **تفاصيل المنتج الكاملة**
🛒 **الاسم:** {info['product_title']}
💰 **السعر الحالي:** {info['target_sale_price']}
🏷️ **السعر الأصلي:** {info['target_original_price']}
🎁 **نسبة الخصم:** {info['target_discount']}
📊 **عدد الطلبات:** {info['lastest_volume']}

{coupon_lines}🏪 **معلومات المتجر:**
🏠 **اسم المتجر:** {info['shop_name']}
⭐️ **تقييم المتجر:** {info['evaluate_rate']}
🔗 [رابط المتجر]({info['shop_url']})

📂 **معلومات إضافية:**
   • الفئة الرئيسية: {info['first_level_category_name']}
   • الفئة الفرعية: {info['second_level_category_name']}
💡 **نسبة العمولة:** {info['commission_rate']}

⏰ *تم الاستخراج في: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}*"""
