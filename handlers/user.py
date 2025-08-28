import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, FSInputFile
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import settings
from database.database import db
from keyboards.keyboards import get_start_keyboard, get_offer_keyboard

router = Router()
logger = logging.getLogger(__name__)


@router.message(CommandStart())
async def start_handler(message: Message, state: FSMContext):
    """Start kommandasi handleri"""
    await state.clear()

    telegram_id = message.from_user.id
    username = message.from_user.username
    first_name = message.from_user.first_name
    last_name = message.from_user.last_name

    # Referral kodni tekshirish
    referred_by = None
    if len(message.text.split()) > 1:
        referral_code = message.text.split()[1]
        referrer = await db.get_user_by_referral(referral_code)
        if referrer:
            referred_by = referrer['telegram_id']

    # Foydalanuvchini tekshirish yoki yaratish
    user = await db.get_user(telegram_id)
    if not user:
        user = await db.create_user(
            telegram_id=telegram_id,
            username=username,
            first_name=first_name,
            last_name=last_name,
            referred_by=referred_by
        )

        # Agar referral orqali kelgan bo'lsa, referrerni sanagichini oshirish
        if referred_by:
            await db.update_referral_count(referred_by)

            # Referrerni vazifasi bajarilganligini tekshirish
            referrer_user = await db.get_user(referred_by)
            if referrer_user['referral_count'] >= settings.REQUIRED_REFERRALS:
                await db.complete_task(referred_by)

                # Referrerni xabardor qilish
                try:
                    success_message = """
Tabriklayman, siz muvaffaqiyatli ro'yxatdan o'tdingiz 🥳

https://t.me/+mnyDxW0Zsug3MmRi

Darsliklar shu kanalga yuboriladi. Qo'shilib oling!
                    """
                    await message.bot.send_message(referred_by, success_message)
                except Exception as e:
                    logger.error(f"Referrerga xabar yuborishda xato: {e}")

    # Kanallar ma'lumotini database'dan olish
    channels = await db.get_active_channels()

    if channels:
        welcome_text = """
Bepul darsliklarni qo'lga kiritish uchun quyidagi kanallarga a'zo bo'ling👇

<b>📺 Kanallar:</b>

"""
        # Har bir kanal uchun ma'lumot qo'shish
        for channel in channels:
            welcome_text += f"📌 <b>{channel['channel_name']}</b>\n"
            if channel['channel_link']:
                welcome_text += f"🔗 {channel['channel_link']}\n\n"

        welcome_text += "✅ Barcha kanallarga a'zo bo'lgandan so'ng \"Tekshirish\" tugmasini bosing!"
    else:
        welcome_text = """
👋 Assalomu alaykum!

🎓 Bepul darsliklar olish uchun botdan foydalaning.

⚠️ Hozirda aktiv kanallar yo'q. Admin bilan bog'laning.
        """

    await message.answer(welcome_text, reply_markup=get_start_keyboard())


@router.message(F.text == "✅ Tekshirish")
async def check_membership_handler(message: Message):
    #  Darsliklarni olish
    link = 'https://t.me/+mnyDxW0Zsug3MmRi'
    keyboard = InlineKeyboardBuilder()
    keyboard.button(text=" Darsliklarni olish", url=link)

    await message.answer('''
    HAR TOMONLAMA RIVOJLANISHNI ISTAGANLAR UCHUN 🔝

✨ Assalomu alaykum, muslimam!

Bu yerda 5 nafar mutaxassis o'z tajribasi va bilimlarini jamlab, siz uchun bepul darslik tayyorlashdi. Har bir mavzu — rivojingiz uchun muhim:

📌 Gulruh – "Hammasi blogdan boshlanadi"
📌 Ayilen – Oila qurishga tayyorgarlik va qo'rquvlarni yengish
📌 Mohinur Barista – Koreyada yashash va o'qish imkoniyatlari
📌 Xilola Qayumova – "Homiladorlar bilishi shart"
📌 Sojida Karimova – Sog'lom munosabatlar siri

📖 Bu loyiha sizga maksimal foyda berish va yangi imkoniyatlarga yo'l ochish uchun takrorlanmas imkon.

Yagona shart - bot bergan taklif postini atigi 6 ta yaqiningizga yuborish, xolos!

Darsliklar jamlangan kanalga linkni olish uchun👇
    ''', reply_markup=keyboard.as_markup())


@router.message(F.text == "Taklif postini olish")
async def send_offer_post(message: Message):
    """Taklif postini yuborish"""
    user_id = message.from_user.id
    user = await db.get_user(user_id)

    if not user:
        await message.answer("❌ Xato yuz berdi. /start ni bosing.")
        return

    # Referral linkni yaratish
    bot_info = await message.bot.get_me()
    bot_username = bot_info.username
    referral_link = f"https://t.me/{bot_username}?start={user['referral_code']}"

    # Taklif posti tugma bilan
    builder = InlineKeyboardBuilder()
    builder.button(text="🔥 Ishtirok etish", url=referral_link)

    # Database'dan taklif posti matnini olish
    content = await db.get_active_content()
    invitation_post_text = content['text_content'] if content and content['text_content'] else """
✨ Bepul darslik loyihasi start oldi!

5 nafar mutaxassis siz uchun turli sohalarda bepul darslar tayyorlashdi:
🌱 Blog yuritish  
🌱 Oila qurishga tayyorgarlik
🌱 Koreyada o'qish va yashash
🌱 Homiladorlikda muhim ma'lumotlar
🌱 Sog'lom munosabatlar

✅ Hayotning eng muhim bosqichlarida kerak bo'ladigan bilimlarni bir joyda jamladik. Endi siz ham mutaxassislardan eshitasiz, mutlaqo BEPUL!

👇 Ishtirok etish tugmasini bosing va darslikni birinchi bo'lib qo'lga kiriting!
    """

    # Taklif rasmi tugma bilan birga yuborish
    invitation_image = await db.get_invitation_image()
    if invitation_image:
        try:
            import os
            if os.path.exists(invitation_image):
                photo_file = FSInputFile(invitation_image)
                await message.answer_photo(
                    photo=photo_file,
                    caption=invitation_post_text,
                    reply_markup=builder.as_markup()
                )
            else:
                await message.answer_photo(
                    photo=invitation_image,
                    caption=invitation_post_text,
                    reply_markup=builder.as_markup()
                )
        except Exception as e:
            logger.error(f"Taklif rasmi yuborishda xato: {e}")
            await message.answer(invitation_post_text, reply_markup=builder.as_markup())
    else:
        await message.answer(invitation_post_text, reply_markup=builder.as_markup())

    await message.answer("Muvaffaqiyat tilayman! 🚀", reply_markup=get_start_keyboard())






@router.message(F.text == "ℹ️ Yordam")
async def help_handler(message: Message):
    """Yordam ma'lumotlari"""
    help_text = """
ℹ️ <b>Bot haqida ma'lumot:</b>

🎯 <b>Maqsad:</b> Bepul darsliklar olish

📋 <b>Qadamlar:</b>
1️⃣ Barcha kanallarga qo'shiling
2️⃣ Sizning linkingiz orqali 6 ta odam qo'shiling
3️⃣ Darsliklarni oling!

🔗 <b>Linkni qanday ulashish:</b>
• Do'stlaringizga yuboring
• Ijtimoiy tarmoqlarda ulashing
• Guruplarda bo'lishing

❓ <b>Savollaringiz bo'lsa:</b>
Admin bilan bog'laning
    """
    await message.answer(help_text)