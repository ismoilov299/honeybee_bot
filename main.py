import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from config import settings
from database.database import db
from handlers import user, admin

# Logging sozlash
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def main():
    # Database initializatsiya
    await db.init_db()

    # Standart kanallarni qo'shish (faqat agar mavjud bo'lmasa)
    default_channels = [
        {
            "channel_id": "-1002915789648",
            "channel_name": "test",
            "channel_link": "https://t.me/+PIRvJVNy8mthMGM6"
        },
        {
            "channel_id": "-1002973522990",
            "channel_name": "test 2",
            "channel_link": "https://t.me/+ORzjE72hInoxZWIy"
        }
    ]

    # Mavjud kanallarni tekshirish
    existing_channels = await db.get_active_channels()
    existing_channel_ids = [ch['channel_id'] for ch in existing_channels]



    # Standart contentni o'rnatish (faqat agar mavjud bo'lmasa)
    existing_content = await db.get_active_content()
    if not existing_content:
        default_content_title = "Bepul Bilimlar Loyihasi"
        default_content_text = """
✨ Bepul darslik loyihasi start oldi!

5 nafar mutaxassis siz uchun turli sohalarda bepul darslar tayyorlashdi:
🌱 Blog yuritish
🌱 Oila qurishga tayyorgarlik
🌱 Koreyada o'qish va yashash
🌱 Homiladorlikda muhim ma'lumotlar
🌱 Sog'lom munosabatlar

✅ Hayotning eng muhim bosqichlarida kerak bo'ladigan bilimlarni bir joyda jamladik. Endi siz ham mutaxassislardan eshitasiz, mutlaqo BEPUL!

👉 Ishtirok etish tugmasini bosing va darslikni birinchi bo'lib qo'lga kiriting!
        """.strip()

        # Standart contentni o'rnatish
        await db.set_content(default_content_title, default_content_text)
        logger.info("✅ Standart content o'rnatildi")
    else:
        logger.info("ℹ️ Content allaqachon mavjud - yangilanmadi")

    print("✅ Database va kanallar tekshirildi!")

    # Bot va dispatcher yaratish
    bot = Bot(
        token=settings.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )

    dp = Dispatcher()

    # Handlerlarni ro'yxatdan o'tkazish
    dp.include_router(user.router)
    dp.include_router(admin.router)

    # Botni ishga tushirish
    logger.info("Bot ishga tushdi...")
    logger.info("Bot nomi: @bepulbilim_bot (avtomatik aniqlanadi)")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())