from telegram import InlineKeyboardButton, InlineKeyboardMarkup


APP_PROMOTION_CALLBACK = "app_promotion"
APP_DOWNLOAD_URL = "https://play.google.com/store/apps/details?id=com.offers365.app"
APP_PROMOTION_IMAGE_URL = "https://gcdnb.pbrd.co/images/izrHmBCJ5zgs.jpg"

APP_PROMOTION_TEXT = """⬇️ قم بتنزيل تطبيق العروض Offres 365 وتمتع بخصومات وكوبونات لا نهائية

✅خصائص او التطبيق:
●توفير روابط عروض باسعار لاتجدها على الموقع
●له القدرة على جلب سبع عروض مختلفة
●لذيه امكانية سحب ومعاينة السعر النهائي للمنتج
●يمكنه الحصول على نسبة التخفيض بالعملات وطبيعة الشحن
●معرفة عدد مبيعات المنتج وتقييمه بالاضافة الى تقييم المتجر
●امكانية استخراج ودجت للتطبيق (الظاهر في الصورة) تمكنك من الحصول على العروض مباشرة من الصفحة الرئيسية للهاتف
●امكانية الحصول على العديدة من الكوبونات بمختلف القيم من خلال التطبيق
●به خاصية طريقة السلة الذكية AI
●يمكن الحصول على احسن عرض لمنتجك من خلال ميزة "طلب عرض AI"
●يدعم مختلف دول الشحن والعديد من العملات ويتوفر بعدة لغاة
●التطبيق عبارة عن نسخة برو مطورة من البوت
●يمتاز بواجهة سهلة ومنظمة بشكل جيد وادواة عديدة تساعدك في التسوق
●التطبيق به العديد من المزايا مقارنة بالبوت (لم يتم ذكر كل مزايا التطبيق هنا) قم بتحميله واكتشفه بنفسك"""


def app_promotion_button() -> InlineKeyboardButton:
    return InlineKeyboardButton(
        "تطبيق العروض Offers 365",
        callback_data=APP_PROMOTION_CALLBACK,
    )


def app_download_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("⬇️تحميل التطبيق⬇️", url=APP_DOWNLOAD_URL)
    ]])