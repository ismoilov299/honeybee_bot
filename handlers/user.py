import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, FSInputFile, ChatJoinRequest
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import settings
from database.database import db
from keyboards.keyboards import get_start_keyboard, get_channels_keyboard, get_offer_keyboard

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
                    # Muvaffaqiyat xabari
                    success_message = """
Tabriklayman, siz muvaffaqiyatli ro'yxatdan o'tdingiz 🥳

https://t.me/+mnyDxW0Zsug3MmRi

Darsliklar shu kanalga yuboriladi. Qo'shilib oling!
                    """

                    await message.bot.send_message(
                        referred_by,
                        success_message
                    )
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
        # Agar kanallar yo'q bo'lsa
        welcome_text = """
👋 Assalomu alaykum!

🎓 Bepul darsliklar olish uchun botdan foydalaning.

⚠️ Hozirda aktiv kanallar yo'q. Admin bilan bog'laning.
        """

    await message.answer(
        welcome_text,
        reply_markup=get_start_keyboard()
    )


@router.message(F.text == "✅ Tekshirish")
async def check_membership_handler(message: Message):
    """Kanalga a'zolikni tekshirish"""
    user_id = message.from_user.id
    user = await db.get_user(user_id)

    if not user:
        await message.answer("❌ Xato yuz berdi. /start ni bosing.")
        return

    # Kanallarni olish
    channels = await db.get_active_channels()

    if not channels:
        await message.answer("❌ Aktiv kanallar yo'q.")
        return

    # Har bir kanalga a'zolikni tekshirish
    joined_channels = []
    pending_requests = []
    not_joined_channels = []

    checking_message = await message.answer("⏳ Kanallar tekshirilmoqda...")

    for channel in channels:
        try:
            channel_identifier = channel['channel_id']

            try:
                # Kanal ma'lumotlarini olish
                if channel_identifier.startswith('https://t.me/+'):
                    try:
                        chat_info = await message.bot.get_chat(channel_identifier)
                        chat_id = chat_info.id
                        member = await message.bot.get_chat_member(chat_id, user_id)
                    except Exception:
                        member = await message.bot.get_chat_member(channel_identifier, user_id)
                else:
                    member = await message.bot.get_chat_member(channel_identifier, user_id)

                # A'zolik statuslarini tekshirish
                if member.status in ['member', 'administrator', 'creator']:
                    # To'liq a'zo
                    joined_channels.append(channel)
                    await db.join_channel(user_id, channel['id'])

                elif member.status == 'restricted':
                    if hasattr(member, 'is_member') and member.is_member:
                        # Cheklangan lekin a'zo
                        joined_channels.append(channel)
                        await db.join_channel(user_id, channel['id'])
                    else:
                        # Request yuborgan, lekin hali tasdiqlanmagan
                        pending_requests.append(channel)

                elif member.status == 'pending':
                    # Join request yuborgan, admin tasdiqini kutmoqda
                    pending_requests.append(channel)

                elif member.status == 'left':
                    # Kanalga qo'shilmagan - database'dan tekshirish
                    user_channel_status = await db.get_user_channel_status(user_id, channel['id'])
                    if user_channel_status and user_channel_status.get('request_sent'):
                        # Avval request yuborgan, lekin hali qo'shilmagan
                        pending_requests.append(channel)
                    else:
                        # Hech qanday action qilmagan
                        not_joined_channels.append(channel)

                elif member.status == 'kicked':
                    # Kanaldan chiqarilgan
                    not_joined_channels.append(channel)

                else:
                    # Boshqa holatlar
                    not_joined_channels.append(channel)

            except Exception as e:
                if "Bad Request: user not found" in str(e):
                    # Foydalanuvchi kanalga hech qo'shilmagan
                    user_channel_status = await db.get_user_channel_status(user_id, channel['id'])
                    if user_channel_status and user_channel_status.get('request_sent'):
                        # Avval request yuborgan, lekin hali qo'shilmagan
                        pending_requests.append(channel)
                    else:
                        # Hech qanday action qilmagan
                        not_joined_channels.append(channel)
                else:
                    logger.error(f"Kanal {channel_identifier} tekshirishda xato: {e}")
                    # Xato holatida ham database'dan tekshirish
                    user_channel_status = await db.get_user_channel_status(user_id, channel['id'])
                    if user_channel_status and user_channel_status.get('request_sent'):
                        pending_requests.append(channel)
                    else:
                        not_joined_channels.append(channel)

        except Exception as e:
            logger.error(f"Kanal ma'lumotlari olishda xato: {e}")
            not_joined_channels.append(channel)

    # Tekshirish xabarini o'chirish
    await checking_message.delete()

    # Natijani ko'rsatish
    if not_joined_channels or pending_requests:
        # Ba'zi kanallarga qo'shilmagan yoki pending
        not_joined_text = "❌ <b>Quyidagi kanallarga request yuboring:</b>\n\n"

        # Qo'shilmagan kanallar
        if not_joined_channels:
            for channel in not_joined_channels:
                not_joined_text += f"📌 <b>{channel['channel_name']}</b>\n"
                if channel['channel_link']:
                    not_joined_text += f"🔗 {channel['channel_link']}\n\n"

        # Pending kanallar (agar bor bo'lsa)
        if pending_requests:
            not_joined_text += "\n⏳ <b>Request yuborilgan kanallar:</b>\n"
            for channel in pending_requests:
                not_joined_text += f"• {channel['channel_name']}\n"
            not_joined_text += "\n"

        not_joined_text += "✅ Barcha kanallarga request yuborganingizdan so'ng 'Request yuborgan' tugmasini bosing!"

        # Request yuborgan tugmasi
        request_builder = InlineKeyboardBuilder()
        request_builder.button(
            text="✅ Request yuborgan",
            callback_data="request_sent"
        )

        await message.answer(not_joined_text, reply_markup=request_builder.as_markup())
        return

    # Barcha kanallarga qo'shilgan bo'lsa
    await message.answer("🎉 <b>Ajoyib! Barcha kanallarga tekshirildi!</b>")

    await message.answer("""
    <b>HAR TOMONLAMA RIVOJLANISHNI ISTAGANLAR UCHUN</b> 🔝

    ✨ Assalomu alaykum, muslimam!

    Bu yerda 5 nafar mutaxassis o'z tajribasi va bilimlarini jamlab, siz uchun bepul darslik tayyorlashdi. Har bir mavzu — rivojingiz uchun muhim:

    📌<b>Gulruh</b> – Hammasi blogdan boshlanadi  
    📌<b>Ayilen</b> – Oila qurishga tayyorgarlik va qo'rquvlarni yengish  
    📌<b>Mohinur Barista</b> – Koreyada yashash va o'qish imkoniyatlari  
    📌<b>Xilola Qayumova</b> – Homiladorlar bilishi shart  
    📌<b>Sojida Karimova</b> – Sog'lom munosabatlar siri  

    📖 Bu loyiha sizga maksimal foyda berish va yangi imkoniyatlarga yo'l ochish uchun takrorlanmas imkon.

    Yagona shart - bot bergan taklif postini atigi 6 ta yaqiningizga yuborish, xolos!

    Taklif postini olish uchun:👇
    """, parse_mode="HTML", reply_markup=get_offer_keyboard())


@router.callback_query(F.data == "request_sent")
async def request_sent_handler(callback: CallbackQuery):
    """Request yuborgan callback handleri - haqiqiy tekshirish"""
    user_id = callback.from_user.id
    user = await db.get_user(user_id)

    if not user:
        await callback.answer("❌ Xato yuz berdi. /start ni bosing.")
        return

    # Kanallarni olish
    channels = await db.get_active_channels()

    if not channels:
        await callback.answer("❌ Aktiv kanallar yo'q.")
        return

    # Har bir kanalga a'zolikni haqiqiy tekshirish
    joined_channels = []
    pending_requests = []
    not_joined_channels = []

    checking_message = await callback.message.edit_text("⏳ Kanallar tekshirilmoqda...")

    for channel in channels:
        try:
            channel_identifier = channel['channel_id']

            try:
                # Kanal ma'lumotlarini olish
                if channel_identifier.startswith('https://t.me/+'):
                    try:
                        chat_info = await callback.bot.get_chat(channel_identifier)
                        chat_id = chat_info.id
                    except Exception:
                        chat_id = channel_identifier
                else:
                    chat_id = channel_identifier

                # Foydalanuvchi holatini tekshirish
                member = await callback.bot.get_chat_member(chat_id, user_id)

                if member.status in ['member', 'administrator', 'creator']:
                    # To'liq a'zo
                    joined_channels.append(channel)
                    await db.join_channel(user_id, channel['id'])

                elif member.status == 'restricted':
                    if hasattr(member, 'is_member') and member.is_member:
                        # Cheklangan lekin a'zo
                        joined_channels.append(channel)
                        await db.join_channel(user_id, channel['id'])
                    else:
                        # Request yuborgan, lekin hali tasdiqlanmagan
                        pending_requests.append(channel)
                        await db.set_request_sent(user_id, channel['id'])

                elif member.status == 'pending':
                    # Join request yuborgan, admin tasdiqini kutmoqda
                    pending_requests.append(channel)
                    await db.set_request_sent(user_id, channel['id'])

                elif member.status == 'left':
                    # Kanalga qo'shilmagan - request yuborgan deb belgilash
                    pending_requests.append(channel)
                    await db.set_request_sent(user_id, channel['id'])

                elif member.status == 'kicked':
                    # Kanaldan chiqarilgan
                    not_joined_channels.append(channel)

                else:
                    # Boshqa holatlar
                    not_joined_channels.append(channel)

            except Exception as e:
                if "Bad Request: user not found" in str(e):
                    # Foydalanuvchi kanalga hech qo'shilmagan - request yuborgan deb belgilash
                    pending_requests.append(channel)
                    await db.set_request_sent(user_id, channel['id'])
                elif "Bad Request: chat not found" in str(e):
                    # Kanal topilmagan
                    logger.error(f"Kanal {channel_identifier} topilmagan")
                    pending_requests.append(channel)
                    await db.set_request_sent(user_id, channel['id'])
                else:
                    logger.error(f"Kanal {channel_identifier} tekshirishda xato: {e}")
                    pending_requests.append(channel)
                    await db.set_request_sent(user_id, channel['id'])

        except Exception as e:
            logger.error(f"Kanal ma'lumotlari olishda xato: {e}")
            pending_requests.append(channel)
            await db.set_request_sent(user_id, channel['id'])

    # Natijani ko'rsatish
    total_channels = len(channels)
    joined_count = len(joined_channels)
    pending_count = len(pending_requests)
    not_joined_count = len(not_joined_channels)

    if not_joined_channels or pending_requests:
        # Hali ham ba'zi kanallarga qo'shilmagan yoki pending
        status_text = f"📊 <b>Kanallar holati:</b>\n\n"
        status_text += f"✅ Qo'shilgan: {joined_count}\n"

        if pending_count > 0:
            status_text += f"⏳ Request yuborilgan: {pending_count}\n"

        if not_joined_count > 0:
            status_text += f"❌ Qo'shilmagan: {not_joined_count}\n"

        status_text += f"\n📈 Jami: {total_channels}\n\n"

        if not_joined_channels:
            status_text += "<b>❌ Qo'shilmagan kanallar:</b>\n"
            for channel in not_joined_channels:
                status_text += f"• {channel['channel_name']}\n"

        if pending_requests:
            status_text += "\n<b>⏳ Request yuborilgan kanallar:</b>\n"
            for channel in pending_requests:
                status_text += f"• {channel['channel_name']}\n"

        status_text += "\n⚠️ Barcha kanallarga qo'shiling va admin sizni tasdiqlashini kuting!"

        await checking_message.edit_text(status_text)

        # Qayta tekshirish tugmasi
        retry_builder = InlineKeyboardBuilder()
        retry_builder.button(
            text="🔄 Qayta tekshirish",
            callback_data="retry_check"
        )

        await callback.message.answer(
            "👆 Barcha kanallarga qo'shilgandan va adminlar tasdiqlagandan so'ng 'Qayta tekshirish' tugmasini bosing!",
            reply_markup=retry_builder.as_markup()
        )
        return

    # Barcha kanallarga qo'shilgan bo'lsa
    await checking_message.edit_text("🎉 <b>Ajoyib! Barcha kanallarga muvaffaqiyatli qo'shildingiz!</b>")

    # Taklif postini yuborish kodlari (o'zgarishsiz)
    # Referral linkni yaratish
    bot_info = await callback.bot.get_me()
    bot_username = bot_info.username
    referral_link = f"https://t.me/{bot_username}?start={user['referral_code']}"

    # Taklif posti tugma bilan
    builder = InlineKeyboardBuilder()
    builder.button(
        text="🔥 Ishtirok etish",
        url=referral_link
    )

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

            # Agar fayl mavjud bo'lsa, fayldan yuborish
            if os.path.exists(invitation_image):
                photo_file = FSInputFile(invitation_image)
                await callback.message.answer_photo(
                    photo=photo_file,
                    caption=invitation_post_text,
                    reply_markup=builder.as_markup()
                )
            else:
                # Agar fayl yo'q bo'lsa, file_id sifatida yuborish (backward compatibility)
                await callback.message.answer_photo(
                    photo=invitation_image,
                    caption=invitation_post_text,
                    reply_markup=builder.as_markup()
                )
        except Exception as e:
            logger.error(f"Taklif rasmi yuborishda xato: {e}")
            # Agar rasm yuborishda xato bo'lsa, faqat matn bilan
            await callback.message.answer(
                invitation_post_text,
                reply_markup=builder.as_markup()
            )
    else:
        await callback.message.answer(
            invitation_post_text,
            reply_markup=builder.as_markup()
        )


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
    builder.button(
        text="🔥 Ishtirok etish",
        url=referral_link
    )

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

            # Agar fayl mavjud bo'lsa, fayldan yuborish
            if os.path.exists(invitation_image):
                photo_file = FSInputFile(invitation_image)
                await message.answer_photo(
                    photo=photo_file,
                    caption=invitation_post_text,
                    reply_markup=builder.as_markup()
                )
            else:
                # Agar fayl yo'q bo'lsa, file_id sifatida yuborish (backward compatibility)
                await message.answer_photo(
                    photo=invitation_image,
                    caption=invitation_post_text,
                    reply_markup=builder.as_markup()
                )
        except Exception as e:
            logger.error(f"Taklif rasmi yuborishda xato: {e}")
            # Agar rasm yuborishda xato bo'lsa, faqat matn bilan
            await message.answer(
                invitation_post_text,
                reply_markup=builder.as_markup()
            )
    else:
        # Agar rasm yo'q bo'lsa, faqat matn bilan
        await message.answer(
            invitation_post_text,
            reply_markup=builder.as_markup()
        )

    await message.answer("Muvaffaqiyat tilayman! 🚀", reply_markup=get_start_keyboard())


@router.callback_query(F.data == "request_sent")
async def request_sent_handler(callback: CallbackQuery):
    """Request yuborgan callback handleri - admin bot bilan haqiqiy tekshirish"""
    user_id = callback.from_user.id
    user = await db.get_user(user_id)

    if not user:
        await callback.answer("❌ Xato yuz berdi. /start ni bosing.")
        return

    # Kanallarni olish
    channels = await db.get_active_channels()

    if not channels:
        await callback.answer("❌ Aktiv kanallar yo'q.")
        return

    # Har bir kanalga a'zolikni haqiqiy tekshirish
    joined_channels = []
    pending_requests = []
    not_joined_channels = []

    checking_message = await callback.message.edit_text("⏳ Kanallar tekshirilmoqda...")

    for channel in channels:
        try:
            channel_identifier = channel['channel_id']

            try:
                # Kanal ma'lumotlarini olish
                try:
                    if channel_identifier.startswith('https://t.me/+'):
                        # Invite link uchun chat_id olish
                        chat_info = await callback.bot.get_chat(channel_identifier)
                        chat_id = chat_info.id
                    else:
                        chat_id = channel_identifier

                    # Botning kanalda admin ekanligini tekshirish
                    bot_member = await callback.bot.get_chat_member(chat_id, callback.bot.id)

                    if bot_member.status not in ['administrator', 'creator']:
                        logger.warning(f"Bot kanal {channel['channel_name']} da admin emas!")
                        # Agar bot admin bo'lmasa, foydalanuvchini "request yuborgan" deb belgilash
                        pending_requests.append(channel)
                        await db.set_request_sent(user_id, channel['id'])
                        continue

                except Exception as e:
                    logger.error(f"Bot admin holatini tekshirishda xato: {e}")
                    pending_requests.append(channel)
                    await db.set_request_sent(user_id, channel['id'])
                    continue

                # Foydalanuvchi holatini tekshirish
                member = await callback.bot.get_chat_member(chat_id, user_id)

                if member.status in ['member', 'administrator', 'creator']:
                    # To'liq a'zo
                    joined_channels.append(channel)
                    await db.join_channel(user_id, channel['id'])

                elif member.status == 'restricted':
                    # Restricted - bu join request yuborgan bo'lishi mumkin
                    if hasattr(member, 'is_member') and member.is_member:
                        # Cheklangan lekin a'zo
                        joined_channels.append(channel)
                        await db.join_channel(user_id, channel['id'])
                    else:
                        # Request yuborgan, lekin hali tasdiqlanmagan
                        pending_requests.append(channel)
                        await db.set_request_sent(user_id, channel['id'])

                elif member.status == 'left':
                    # Kanalga qo'shilmagan - hech qanday action qilmagan
                    not_joined_channels.append(channel)

                elif member.status == 'pending':
                    # Join request yuborgan, admin tasdiqini kutmoqda
                    pending_requests.append(channel)
                    await db.set_request_sent(user_id, channel['id'])

                elif member.status == 'kicked':
                    # Kanaldan chiqarilgan
                    not_joined_channels.append(channel)

                else:
                    # Boshqa holatlar
                    not_joined_channels.append(channel)

            except Exception as e:
                if "Bad Request: user not found" in str(e):
                    # Foydalanuvchi kanalga hech qo'shilmagan
                    not_joined_channels.append(channel)
                elif "Bad Request: chat not found" in str(e):
                    # Kanal topilmagan yoki bot admin emas
                    logger.error(f"Kanal {channel_identifier} topilmagan yoki bot admin emas")
                    pending_requests.append(channel)
                    await db.set_request_sent(user_id, channel['id'])
                else:
                    logger.error(f"Kanal {channel_identifier} tekshirishda xato: {e}")
                    pending_requests.append(channel)
                    await db.set_request_sent(user_id, channel['id'])

        except Exception as e:
            logger.error(f"Kanal ma'lumotlari olishda xato: {e}")
            pending_requests.append(channel)
            await db.set_request_sent(user_id, channel['id'])

    # Barcha kanallarga request yuborgan deb belgilash (faqat pending va not_joined uchun)
    for channel in pending_requests + not_joined_channels:
        await db.set_request_sent(user_id, channel['id'])

    # Natijani ko'rsatish
    total_channels = len(channels)
    joined_count = len(joined_channels)
    pending_count = len(pending_requests)
    not_joined_count = len(not_joined_channels)

    if not_joined_channels or pending_requests:
        # Hali ham ba'zi kanallarga qo'shilmagan yoki pending
        status_text = f"📊 <b>Kanallar holati:</b>\n\n"
        status_text += f"✅ Qo'shilgan: {joined_count}\n"

        if pending_count > 0:
            status_text += f"⏳ Request yuborilgan: {pending_count}\n"

        if not_joined_count > 0:
            status_text += f"❌ Qo'shilmagan: {not_joined_count}\n"

        status_text += f"\n📈 Jami: {total_channels}\n\n"

        if not_joined_channels:
            status_text += "<b>Qo'shilmagan kanallar:</b>\n"
            for channel in not_joined_channels:
                status_text += f"• {channel['channel_name']}\n"

        if pending_requests:
            status_text += "\n<b>Request yuborilgan kanallar:</b>\n"
            for channel in pending_requests:
                status_text += f"• {channel['channel_name']}\n"

        status_text += "\n⚠️ Barcha kanallarga qo'shiling va admin sizni tasdiqlashini kuting!"

        await checking_message.edit_text(status_text)

        # Qayta tekshirish tugmasi
        retry_builder = InlineKeyboardBuilder()
        retry_builder.button(
            text="🔄 Qayta tekshirish",
            callback_data="retry_check"
        )

        await callback.message.answer(
            "👆 Barcha kanallarga qo'shilgandan va adminlar tasdiqlagandan so'ng 'Qayta tekshirish' tugmasini bosing!",
            reply_markup=retry_builder.as_markup()
        )
        return

    # Barcha kanallarga qo'shilgan bo'lsa
    await checking_message.edit_text("🎉 <b>Ajoyib! Barcha kanallarga muvaffaqiyatli qo'shildingiz!</b>")

    # Referral linkni yaratish
    bot_info = await callback.bot.get_me()
    bot_username = bot_info.username
    referral_link = f"https://t.me/{bot_username}?start={user['referral_code']}"

    # Taklif posti tugma bilan
    builder = InlineKeyboardBuilder()
    builder.button(
        text="🔥 Ishtirok etish",
        url=referral_link
    )

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

            # Agar fayl mavjud bo'lsa, fayldan yuborish
            if os.path.exists(invitation_image):
                photo_file = FSInputFile(invitation_image)
                await callback.message.answer_photo(
                    photo=photo_file,
                    caption=invitation_post_text,
                    reply_markup=builder.as_markup()
                )
            else:
                # Agar fayl yo'q bo'lsa, file_id sifatida yuborish (backward compatibility)
                await callback.message.answer_photo(
                    photo=invitation_image,
                    caption=invitation_post_text,
                    reply_markup=builder.as_markup()
                )
        except Exception as e:
            logger.error(f"Taklif rasmi yuborishda xato: {e}")
            # Agar rasm yuborishda xato bo'lsa, faqat matn bilan
            await callback.message.answer(
                invitation_post_text,
                reply_markup=builder.as_markup()
            )
    else:
        await callback.message.answer(
            invitation_post_text,
            reply_markup=builder.as_markup()
        )


@router.callback_query(F.data == "retry_check")
async def retry_check_handler(callback: CallbackQuery):
    """Qayta tekshirish handleri"""
    # request_sent_handler bilan bir xil logika
    await request_sent_handler(callback)


@router.callback_query(F.data == "check_channels")
async def check_channels_handler(callback: CallbackQuery):
    user_id = callback.from_user.id

    # Haqiqiy holatni tekshirish
    channel_status = await db.check_all_channels_joined_real(user_id)

    if channel_status['all_joined']:
        user = await db.get_user(user_id)

        bot_info = await callback.bot.get_me()
        bot_username = bot_info.username
        referral_link = f"https://t.me/{bot_username}?start={user['referral_code']}"

        await callback.message.edit_text(
            f"✅ Barcha kanallarga qo'shildingiz!\n\n"
            f"🔗 <b>Sizning linkingiz:</b>\n"
            f"<code>{referral_link}</code>\n\n"
            f"📊 Hozirgi holat: {user['referral_count']}/{settings.REQUIRED_REFERRALS}\n\n"
            f"Bu linkni do'stlaringizga yuboring. {settings.REQUIRED_REFERRALS} ta odam "
            f"linkingiz orqali botga qo'shilganda sizga darslar yuboriladi!"
        )
    else:
        # Holatni batafsil ko'rsatish
        status_text = f"📊 <b>Kanallar holati:</b>\n\n"
        status_text += f"✅ Qo'shilgan: {channel_status['joined']}\n"

        if channel_status['pending'] > 0:
            status_text += f"⏳ Request yuborilgan: {channel_status['pending']}\n"

        if channel_status['not_joined'] > 0:
            status_text += f"❌ Qo'shilmagan: {channel_status['not_joined']}\n"

        status_text += f"\n📈 Jami: {channel_status['total']}\n\n"
        status_text += "⚠️ Avval barcha kanallarga qo'shiling!"

        await callback.answer(status_text, show_alert=True)


@router.message(F.text == "📊 Status")
async def status_handler(message: Message):
    """Foydalanuvchi statusini ko'rsatish"""
    user = await db.get_user(message.from_user.id)

    if not user:
        await message.answer("❌ Xato yuz berdi. /start ni bosing.")
        return

    # Bot username avtomatik olish
    bot_info = await message.bot.get_me()
    bot_username = bot_info.username
    referral_link = f"https://t.me/{bot_username}?start={user['referral_code']}"

    status_text = f"""
📊 <b>Sizning statusingiz:</b>

👤 Ism: {user['first_name']}
🆔 Referral kod: <code>{user['referral_code']}</code>
📈 Taklif qilganlar: {user['referral_count']}/{settings.REQUIRED_REFERRALS}
✅ Vazifa holati: {"Bajarildi" if user['completed_task'] else "Bajarilmagan"}

🔗 <b>Sizning linkingiz:</b>
<code>{referral_link}</code>

💡 Bu linkni do'stlaringizga yuboring!
    """

    await message.answer(status_text)


@router.message(F.text == "🔗 Mening linkim")
async def my_link_handler(message: Message):
    """Foydalanuvchi linkini ko'rsatish"""
    user = await db.get_user(message.from_user.id)

    if not user:
        await message.answer("❌ Xato yuz berdi. /start ni bosing.")
        return

    # Bot username avtomatik olish
    bot_info = await message.bot.get_me()
    bot_username = bot_info.username
    referral_link = f"https://t.me/{bot_username}?start={user['referral_code']}"

    await message.answer(
        f"🔗 <b>Sizning maxsus linkingiz:</b>\n\n"
        f"<code>{referral_link}</code>\n\n"
        f"📊 Holat: {user['referral_count']}/{settings.REQUIRED_REFERRALS}\n\n"
        f"Bu linkni do'stlaringiz bilan bo'lishing!"
    )


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


@router.message(Command("debug_me"))
async def debug_user_status(message: Message):
    """Foydalanuvchi holatini debug qilish"""
    user_id = message.from_user.id

    # Database'dan ma'lumotlarni olish
    user = await db.get_user(user_id)
    channels = await db.get_active_channels()

    debug_text = f"🔍 <b>Debug ma'lumotlari:</b>\n\n"
    debug_text += f"👤 User ID: {user_id}\n"
    debug_text += f"📝 Username: {user.get('username', 'N/A')}\n\n"

    debug_text += f"📺 <b>Kanallar ({len(channels)}):</b>\n\n"

    for i, channel in enumerate(channels, 1):
        debug_text += f"<b>{i}. {channel['channel_name']}</b>\n"
        debug_text += f"🆔 Channel ID: <code>{channel['channel_id']}</code>\n"

        # Database'dan user-channel holatini olish
        user_channel_status = await db.get_user_channel_status(user_id, channel['id'])

        if user_channel_status:
            debug_text += f"📊 DB Status:\n"
            debug_text += f"   • Joined: {user_channel_status.get('joined', 0)}\n"
            debug_text += f"   • Request sent: {user_channel_status.get('request_sent', 0)}\n"
        else:
            debug_text += f"📊 DB Status: Hech qanday ma'lumot yo'q\n"

        # Telegram'dan haqiqiy holatni tekshirish
        try:
            if channel['channel_id'].startswith('https://t.me/+'):
                try:
                    chat_info = await message.bot.get_chat(channel['channel_id'])
                    chat_id = chat_info.id
                    member = await message.bot.get_chat_member(chat_id, user_id)
                except:
                    member = await message.bot.get_chat_member(channel['channel_id'], user_id)
            else:
                member = await message.bot.get_chat_member(channel['channel_id'], user_id)

            debug_text += f"🔗 Telegram Status: <code>{member.status}</code>\n"

            if hasattr(member, 'is_member'):
                debug_text += f"   • is_member: {member.is_member}\n"

        except Exception as e:
            debug_text += f"❌ Telegram Error: {str(e)[:50]}...\n"

        debug_text += "\n"

    # Uzun xabarni bo'lish
    if len(debug_text) > 4000:
        parts = [debug_text[i:i + 4000] for i in range(0, len(debug_text), 4000)]
        for part in parts:
            await message.answer(part)
    else:
        await message.answer(debug_text)


@router.message(Command("debug_channels"))
async def debug_channels_status(message: Message):
    """Kanallar holatini debug qilish"""
    user_id = message.from_user.id

    # Haqiqiy holatni olish
    channel_status = await db.check_all_channels_joined_real(user_id)

    debug_text = f"🔍 <b>Kanallar debug:</b>\n\n"
    debug_text += f"📈 Jami kanallar: {channel_status['total']}\n"
    debug_text += f"✅ Qo'shilgan: {channel_status['joined']}\n"
    debug_text += f"⏳ Pending: {channel_status['pending']}\n"
    debug_text += f"❌ Qo'shilmagan: {channel_status['not_joined']}\n"
    debug_text += f"🎯 Barchasi qo'shilganmi: {channel_status['all_joined']}\n\n"

    # Har bir kanal uchun batafsil
    channels = await db.get_active_channels()
    for channel in channels:
        user_channel_status = await db.get_user_channel_status(user_id, channel['id'])

        debug_text += f"📌 <b>{channel['channel_name']}</b>\n"

        if user_channel_status:
            debug_text += f"   • Joined: {user_channel_status.get('joined', 0)}\n"
            debug_text += f"   • Request sent: {user_channel_status.get('request_sent', 0)}\n"
        else:
            debug_text += f"   • Ma'lumot yo'q\n"
        debug_text += "\n"

    await message.answer(debug_text)


@router.message(Command("force_check"))
async def force_check_channels(message: Message):
    """Majburiy tekshirish va yangilash"""
    user_id = message.from_user.id

    progress_msg = await message.answer("🔄 Majburiy tekshirish boshlandi...")

    channels = await db.get_active_channels()
    updated_count = 0

    for channel in channels:
        try:
            if channel['channel_id'].startswith('https://t.me/+'):
                try:
                    chat_info = await message.bot.get_chat(channel['channel_id'])
                    chat_id = chat_info.id
                    member = await message.bot.get_chat_member(chat_id, user_id)
                except:
                    member = await message.bot.get_chat_member(channel['channel_id'], user_id)
            else:
                member = await message.bot.get_chat_member(channel['channel_id'], user_id)

            # Holatga qarab database'ni yangilash
            if member.status in ['member', 'administrator', 'creator']:
                await db.join_channel(user_id, channel['id'])
                updated_count += 1
            elif member.status == 'restricted' and hasattr(member, 'is_member') and member.is_member:
                await db.join_channel(user_id, channel['id'])
                updated_count += 1
            elif member.status in ['pending', 'left']:
                # Pending yoki left - request yuborgan deb belgilash
                await db.set_request_sent(user_id, channel['id'])
            elif member.status == 'kicked':
                # Kicked - database'dan o'chirish yoki 0 qilish
                # Hozircha hech narsa qilmaymiz
                pass

        except Exception as e:
            logger.error(f"Force check error for {channel['channel_name']}: {e}")

    await progress_msg.edit_text(
        f"✅ Majburiy tekshirish tugadi!\n\n"
        f"📊 {updated_count} ta kanal holati yangilandi.\n\n"
        f"Endi /debug_me bilan holatni tekshiring."
    )


@router.message(Command("reset_me"))
async def reset_user_status(message: Message):
    """Foydalanuvchi holatini reset qilish"""
    user_id = message.from_user.id

    # Database'dan barcha kanal holatini o'chirish
    await db.reset_user_channel_status(user_id)

    await message.answer(
        "🔄 <b>Sizning kanal holatlaringiz tozalandi!</b>\n\n"
        "Endi qaytadan '✅ Tekshirish' tugmasini bosing va "
        "faqat haqiqatan request yuborgan kanallar uchun "
        "'✅ Request yuborgan' tugmasini bosing."
    )


# 1. getChatJoinRequests API orqali pending requestlarni olish
async def check_pending_requests(bot, chat_id, user_id=None):
    """Kanalga yuborilgan join requestlarni tekshirish"""
    try:
        # Bot admin bo'lishi shart
        bot_member = await bot.get_chat_member(chat_id, bot.id)

        if bot_member.status not in ['administrator', 'creator']:
            return {"error": "Bot admin emas"}

        # Barcha pending requestlarni olish (faqat 50 ta)
        # Telegram Bot API da getChatJoinRequests mavjud
        # Lekin aiogram da to'g'ridan-to'g'ri method yo'q

        # Raw API chaqiruvi
        result = await bot.session.request(
            bot.session._build_url(bot.api, "getChatJoinRequests"),
            method="POST",
            data={
                "chat_id": chat_id,
                "limit": 50
            }
        )

        if result.get("ok"):
            requests = result.get("result", {}).get("requests", [])

            # Agar user_id berilgan bo'lsa, faqat shu foydalanuvchini qidirish
            if user_id:
                for request in requests:
                    if request.get("from", {}).get("id") == user_id:
                        return {
                            "found": True,
                            "request": request,
                            "date": request.get("date")
                        }
                return {"found": False}
            else:
                return {"requests": requests, "count": len(requests)}
        else:
            return {"error": result.get("description", "API xatosi")}

    except Exception as e:
        return {"error": str(e)}


# 2. getChatMember bilan statusni aniqroq tekshirish
async def check_member_detailed_status(bot, chat_id, user_id):
    """Foydalanuvchi statusini batafsil tekshirish"""
    try:
        member = await bot.get_chat_member(chat_id, user_id)

        status_info = {
            "status": member.status,
            "user_id": user_id,
            "is_member": getattr(member, 'is_member', None),
            "can_be_edited": getattr(member, 'can_be_edited', None),
            "can_manage_chat": getattr(member, 'can_manage_chat', None),
            "can_change_info": getattr(member, 'can_change_info', None),
            "can_delete_messages": getattr(member, 'can_delete_messages', None),
            "can_invite_users": getattr(member, 'can_invite_users', None),
            "can_restrict_members": getattr(member, 'can_restrict_members', None),
            "can_pin_messages": getattr(member, 'can_pin_messages', None),
            "can_promote_members": getattr(member, 'can_promote_members', None),
            "until_date": getattr(member, 'until_date', None)
        }

        # Status tahlili
        if member.status == "left":
            status_info["interpretation"] = "Kanalga qo'shilmagan yoki chiqib ketgan"
        elif member.status == "member":
            status_info["interpretation"] = "Faol a'zo"
        elif member.status == "restricted":
            if getattr(member, 'is_member', False):
                status_info["interpretation"] = "Cheklangan a'zo"
            else:
                status_info["interpretation"] = "Request yuborgan yoki rad etilgan"
        elif member.status == "kicked":
            status_info["interpretation"] = "Kanaldan chiqarilgan"
        elif member.status == "administrator":
            status_info["interpretation"] = "Admin"
        elif member.status == "creator":
            status_info["interpretation"] = "Yaratuvchi"

        return status_info

    except Exception as e:
        return {"error": str(e)}


# 3. Raw API chaqiruvi uchun helper
async def raw_api_call(bot, method, params):
    """Telegram API ga to'g'ridan-to'g'ri chaqiruv"""
    try:
        url = f"https://api.telegram.org/bot{bot.token}/{method}"

        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=params) as response:
                return await response.json()

    except Exception as e:
        return {"ok": False, "description": str(e)}


# Debug uchun kengaytirilgan komanda
@router.message(Command("deep_debug"))
async def deep_debug_channels(message: Message):
    """Chuqur debug - join requestlar bilan"""
    user_id = message.from_user.id

    await message.answer("🔍 Chuqur debug boshlandi...")

    channels = await db.get_active_channels()

    for channel in channels[:2]:  # Faqat birinchi 2 ta kanalini tekshirish
        channel_id = channel['channel_id']

        debug_text = f"🔍 <b>{channel['channel_name']}</b>\n\n"

        # 1. Oddiy member status
        try:
            member_status = await check_member_detailed_status(message.bot, channel_id, user_id)
            debug_text += f"👤 <b>Member Status:</b>\n"
            debug_text += f"Status: <code>{member_status.get('status')}</code>\n"
            debug_text += f"Tahlil: {member_status.get('interpretation', 'N/A')}\n"
            if member_status.get('is_member') is not None:
                debug_text += f"Is Member: {member_status.get('is_member')}\n"
        except Exception as e:
            debug_text += f"❌ Member status xatosi: {e}\n"

        debug_text += "\n"

        # 2. Join requests tekshirish
        try:
            requests_check = await check_pending_requests(message.bot, channel_id, user_id)
            debug_text += f"📋 <b>Join Requests:</b>\n"

            if requests_check.get("found"):
                debug_text += f"✅ Request topildi!\n"
                debug_text += f"Sana: {requests_check.get('date')}\n"
            elif requests_check.get("found") is False:
                debug_text += f"❌ Request topilmadi\n"
            elif requests_check.get("error"):
                debug_text += f"⚠️ Xato: {requests_check.get('error')}\n"

        except Exception as e:
            debug_text += f"❌ Requests xatosi: {e}\n"

        await message.answer(debug_text)


# Admin uchun barcha pending requestlarni ko'rish
@router.message(Command("pending_requests"))
async def show_pending_requests(message: Message):
    """Barcha pending requestlarni ko'rsatish (faqat adminlar uchun)"""
    # Admin tekshiruvi
    # if not is_admin(message.from_user.id):
    #     return

    channels = await db.get_active_channels()

    for channel in channels:
        try:
            requests_info = await check_pending_requests(message.bot, channel['channel_id'])

            if requests_info.get("requests"):
                request_text = f"📋 <b>{channel['channel_name']}</b>\n"
                request_text += f"Pending requests: {requests_info.get('count', 0)}\n\n"

                for req in requests_info["requests"][:5]:  # Faqat birinchi 5 tasi
                    user_info = req.get("from", {})
                    request_text += f"👤 {user_info.get('first_name', 'N/A')}"
                    if user_info.get('username'):
                        request_text += f" (@{user_info.get('username')})"
                    request_text += f"\n🆔 {user_info.get('id')}\n"
                    request_text += f"📅 {req.get('date')}\n\n"

                await message.answer(request_text)
            elif requests_info.get("error"):
                await message.answer(f"❌ {channel['channel_name']}: {requests_info['error']}")

        except Exception as e:
            await message.answer(f"❌ {channel['channel_name']} xatosi: {e}")


# Import qo'shing
import aiohttp
# from aiogram.methods import GetChatJoinRequests


# To'g'rilangan join requests tekshiruvi
async def check_pending_requests_fixed(bot, chat_id, user_id=None):
    """Join requestlarni to'g'ri usulda tekshirish"""
    try:
        # Bot admin ekanligini tekshirish
        bot_member = await bot.get_chat_member(chat_id, bot.id)

        if bot_member.status not in ['administrator', 'creator']:
            return {"error": "Bot admin emas"}

        # 1-usul: Aiogram method orqali
        try:
            # GetChatJoinRequests methodini ishlatish
            method = ChatJoinRequest(chat_id=chat_id, limit=50)
            result = await bot(method)

            if result and hasattr(result, 'requests'):
                requests = result.requests

                # Agar user_id berilgan bo'lsa, faqat shu foydalanuvchini qidirish
                if user_id:
                    for request in requests:
                        if request.from_user.id == user_id:
                            return {
                                "found": True,
                                "request": {
                                    "user_id": request.from_user.id,
                                    "first_name": request.from_user.first_name,
                                    "username": request.from_user.username,
                                    "date": request.date.timestamp() if request.date else None
                                }
                            }
                    return {"found": False}
                else:
                    request_list = []
                    for request in requests:
                        request_list.append({
                            "user_id": request.from_user.id,
                            "first_name": request.from_user.first_name,
                            "username": request.from_user.username,
                            "date": request.date.timestamp() if request.date else None
                        })
                    return {"requests": request_list, "count": len(request_list)}
            else:
                return {"requests": [], "count": 0}

        except Exception as e:
            # 2-usul: Direct HTTP request
            return await direct_api_request(bot, chat_id, user_id)

    except Exception as e:
        return {"error": f"Umumiy xato: {str(e)}"}


async def direct_api_request(bot, chat_id, user_id=None):
    """To'g'ridan-to'g'ri API chaqiruvi"""
    try:
        url = f"https://api.telegram.org/bot{bot.token}/getChatJoinRequests"
        params = {
            "chat_id": chat_id,
            "limit": 50
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=params) as response:
                result = await response.json()

                if result.get("ok"):
                    requests = result.get("result", {}).get("requests", [])

                    if user_id:
                        for request in requests:
                            if request.get("from", {}).get("id") == user_id:
                                return {
                                    "found": True,
                                    "request": request
                                }
                        return {"found": False}
                    else:
                        return {"requests": requests, "count": len(requests)}
                else:
                    return {"error": result.get("description", "API xatosi")}

    except Exception as e:
        return {"error": f"HTTP request xatosi: {str(e)}"}


# Sodda usul - faqat member statusini tekshirish
async def simple_request_check(bot, chat_id, user_id):
    """Oddiy usul - faqat member statusini tahlil qilish"""
    try:
        member = await bot.get_chat_member(chat_id, user_id)

        # Status tahlili
        if member.status == "left":
            return {
                "status": "left",
                "interpretation": "Kanalga qo'shilmagan",
                "likely_requested": False
            }
        elif member.status == "member":
            return {
                "status": "member",
                "interpretation": "Faol a'zo",
                "likely_requested": False  # Allaqachon a'zo
            }
        elif member.status == "restricted":
            is_member = getattr(member, 'is_member', False)
            if is_member:
                return {
                    "status": "restricted_member",
                    "interpretation": "Cheklangan a'zo",
                    "likely_requested": False
                }
            else:
                return {
                    "status": "restricted_not_member",
                    "interpretation": "Request yuborgan yoki rad etilgan",
                    "likely_requested": True
                }
        elif member.status == "kicked":
            return {
                "status": "kicked",
                "interpretation": "Kanaldan chiqarilgan",
                "likely_requested": False
            }
        else:
            return {
                "status": member.status,
                "interpretation": f"Noma'lum status: {member.status}",
                "likely_requested": False
            }

    except Exception as e:
        return {"error": str(e)}


# Yangilangan debug komanda
@router.message(Command("check_requests"))
async def check_user_requests(message: Message):
    """Foydalanuvchining join requestlarini tekshirish"""
    user_id = message.from_user.id

    await message.answer("🔍 Join requestlar tekshirilmoqda...")

    channels = await db.get_active_channels()

    for channel in channels:
        channel_id = channel['channel_id']

        result_text = f"📺 <b>{channel['channel_name']}</b>\n\n"

        # 1. Oddiy member status
        simple_check = await simple_request_check(message.bot, channel_id, user_id)

        if simple_check.get("error"):
            result_text += f"❌ Xato: {simple_check['error']}\n"
        else:
            result_text += f"📊 Status: <code>{simple_check['status']}</code>\n"
            result_text += f"💬 Tahlil: {simple_check['interpretation']}\n"
            result_text += f"🤔 Request yuborgan bo'lishi mumkin: {'✅ Ha' if simple_check['likely_requested'] else '❌ Yoq'}\n"

        result_text += "\n"

        # 2. Join requests API (agar bot admin bo'lsa)
        try:
            api_check = await check_pending_requests_fixed(message.bot, channel_id, user_id)

            if api_check.get("error"):
                result_text += f"⚠️ API: {api_check['error']}\n"
            elif api_check.get("found"):
                result_text += f"✅ Join request topildi!\n"
                req_info = api_check['request']
                if isinstance(req_info, dict) and 'date' in req_info:
                    result_text += f"📅 Sana: {req_info['date']}\n"
            elif api_check.get("found") is False:
                result_text += f"❌ Join request topilmadi\n"
            else:
                result_text += f"📋 API javob: {api_check}\n"

        except Exception as e:
            result_text += f"❌ API xatosi: {e}\n"

        result_text += "\n" + "=" * 30 + "\n\n"

        await message.answer(result_text)


# Bot admin statusini tekshirish
@router.message(Command("check_bot_perms"))
async def check_bot_permissions(message: Message):
    """Bot ruxsatlarini tekshirish"""
    channels = await db.get_active_channels()

    for channel in channels:
        try:
            bot_member = await message.bot.get_chat_member(channel['channel_id'], message.bot.id)

            perm_text = f"🤖 <b>{channel['channel_name']}</b>\n\n"
            perm_text += f"Status: <code>{bot_member.status}</code>\n"

            if bot_member.status in ['administrator', 'creator']:
                perm_text += "✅ Bot admin\n"

                # Ruxsatlarni tekshirish
                perms = [
                    ("Can manage chat", getattr(bot_member, 'can_manage_chat', None)),
                    ("Can delete messages", getattr(bot_member, 'can_delete_messages', None)),
                    ("Can manage video chats", getattr(bot_member, 'can_manage_video_chats', None)),
                    ("Can restrict members", getattr(bot_member, 'can_restrict_members', None)),
                    ("Can promote members", getattr(bot_member, 'can_promote_members', None)),
                    ("Can change info", getattr(bot_member, 'can_change_info', None)),
                    ("Can invite users", getattr(bot_member, 'can_invite_users', None)),
                    ("Can pin messages", getattr(bot_member, 'can_pin_messages', None)),
                ]

                for perm_name, perm_value in perms:
                    if perm_value is not None:
                        perm_text += f"• {perm_name}: {'✅' if perm_value else '❌'}\n"

            else:
                perm_text += "❌ Bot admin emas\n"

            await message.answer(perm_text)

        except Exception as e:
            await message.answer(f"❌ {channel['channel_name']}: {e}")


async def check_user_channel_status_detailed(bot, chat_id, user_id):
    """Foydalanuvchi holatini batafsil tekshirish"""
    try:
        # Bot admin ekanligini tekshirish
        try:
            bot_member = await bot.get_chat_member(chat_id, bot.id)
            bot_is_admin = bot_member.status in ['administrator', 'creator']
        except:
            bot_is_admin = False

        # Foydalanuvchi holatini olish
        member = await bot.get_chat_member(chat_id, user_id)

        result = {
            "status": member.status,
            "bot_is_admin": bot_is_admin,
            "interpretation": "",
            "likely_pending": False,
            "can_join": True
        }

        # Status bo'yicha tahlil
        if member.status == "left":
            result["interpretation"] = "Kanalga qo'shilmagan"
            result["likely_pending"] = False
            result["can_join"] = True

        elif member.status == "member":
            result["interpretation"] = "Faol a'zo"
            result["likely_pending"] = False
            result["can_join"] = False  # Allaqachon a'zo

        elif member.status == "administrator":
            result["interpretation"] = "Administrator"
            result["likely_pending"] = False
            result["can_join"] = False

        elif member.status == "creator":
            result["interpretation"] = "Kanal yaratuvchisi"
            result["likely_pending"] = False
            result["can_join"] = False

        elif member.status == "restricted":
            is_member = getattr(member, 'is_member', False)
            if is_member:
                result["interpretation"] = "Cheklangan a'zo"
                result["likely_pending"] = False
                result["can_join"] = False
            else:
                result["interpretation"] = "Request yuborgan yoki cheklangan"
                result["likely_pending"] = True
                result["can_join"] = False

        elif member.status == "kicked":
            result["interpretation"] = "Kanaldan chiqarilgan"
            result["likely_pending"] = False
            result["can_join"] = False

        else:
            result["interpretation"] = f"Noma'lum status: {member.status}"
            result["likely_pending"] = False
            result["can_join"] = True

        # Qo'shimcha ma'lumotlar
        if hasattr(member, 'until_date') and member.until_date:
            result["until_date"] = member.until_date

        if hasattr(member, 'can_send_messages'):
            result["can_send_messages"] = member.can_send_messages

        return result

    except Exception as e:
        return {"error": str(e)}


# Raw API chaqiruvi (agar kerak bo'lsa)
async def raw_get_chat_join_requests(bot_token, chat_id, limit=20):
    """Raw API orqali join requestlarni olish"""
    import aiohttp

    try:
        url = f"https://api.telegram.org/bot{bot_token}/getChatJoinRequests"
        params = {
            "chat_id": chat_id,
            "limit": limit
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=params) as response:
                result = await response.json()

                if result.get("ok"):
                    return {
                        "success": True,
                        "requests": result.get("result", {}).get("requests", []),
                        "total_count": result.get("result", {}).get("total_count", 0)
                    }
                else:
                    return {
                        "success": False,
                        "error": result.get("description", "API xatosi")
                    }

    except Exception as e:
        return {"success": False, "error": str(e)}


# Sodda va ishonchli tekshirish
@router.message(Command("simple_check"))
async def simple_channel_check(message: Message):
    """Oddiy va ishonchli kanal tekshiruvi"""
    user_id = message.from_user.id

    await message.answer("🔍 Kanallaringiz tekshirilmoqda...")

    channels = await db.get_active_channels()

    summary = {
        "joined": [],
        "likely_pending": [],
        "not_joined": [],
        "blocked": [],
        "errors": []
    }

    for channel in channels:
        channel_id = channel['channel_id']
        channel_name = channel['channel_name']

        status_info = await check_user_channel_status_detailed(message.bot, channel_id, user_id)

        if status_info.get("error"):
            summary["errors"].append({"name": channel_name, "error": status_info["error"]})
            continue

        status = status_info["status"]

        if status in ["member", "administrator", "creator"]:
            summary["joined"].append(channel_name)
        elif status_info["likely_pending"]:
            summary["likely_pending"].append(channel_name)
        elif status == "kicked":
            summary["blocked"].append(channel_name)
        else:
            summary["not_joined"].append(channel_name)

    # Natijani ko'rsatish
    result_text = "📊 <b>Kanallar holati:</b>\n\n"

    if summary["joined"]:
        result_text += f"✅ <b>Qo'shilgan ({len(summary['joined'])}):</b>\n"
        for name in summary["joined"]:
            result_text += f"• {name}\n"
        result_text += "\n"

    if summary["likely_pending"]:
        result_text += f"⏳ <b>Request yuborgan ({len(summary['likely_pending'])}):</b>\n"
        for name in summary["likely_pending"]:
            result_text += f"• {name}\n"
        result_text += "\n"

    if summary["not_joined"]:
        result_text += f"❌ <b>Qo'shilmagan ({len(summary['not_joined'])}):</b>\n"
        for name in summary["not_joined"]:
            result_text += f"• {name}\n"
        result_text += "\n"

    if summary["blocked"]:
        result_text += f"🚫 <b>Bloklanган ({len(summary['blocked'])}):</b>\n"
        for name in summary["blocked"]:
            result_text += f"• {name}\n"
        result_text += "\n"

    if summary["errors"]:
        result_text += f"⚠️ <b>Xatolar ({len(summary['errors'])}):</b>\n"
        for item in summary["errors"]:
            result_text += f"• {item['name']}: {item['error'][:50]}...\n"

    await message.answer(result_text)


# Raw API bilan sinab ko'rish (agar bot admin bo'lsa)
@router.message(Command("raw_check"))
async def raw_api_check(message: Message):
    """Raw API bilan join requestlarni tekshirish"""
    user_id = message.from_user.id

    channels = await db.get_active_channels()

    for channel in channels[:2]:  # Faqat birinchi 2 tasi
        channel_id = channel['channel_id']

        # Raw API chaqiruvi
        requests_result = await raw_get_chat_join_requests(message.bot.token, channel_id, 50)

        result_text = f"📺 <b>{channel['channel_name']}</b>\n\n"

        if requests_result["success"]:
            requests = requests_result["requests"]
            total_count = requests_result["total_count"]

            result_text += f"📋 Jami pending requests: {total_count}\n"

            # Foydalanuvchini qidirish
            found_user = False
            for request in requests:
                if request.get("from", {}).get("id") == user_id:
                    found_user = True
                    result_text += f"✅ <b>Sizning requestingiz topildi!</b>\n"
                    result_text += f"📅 Sana: {request.get('date', 'N/A')}\n"
                    if request.get("bio"):
                        result_text += f"📝 Bio: {request['bio']}\n"
                    break

            if not found_user:
                result_text += f"❌ Sizning requestingiz topilmadi\n"

            result_text += f"\n📝 Oxirgi 5 ta request:\n"
            for request in requests[:5]:
                user_info = request.get("from", {})
                result_text += f"• {user_info.get('first_name', 'N/A')} (ID: {user_info.get('id')})\n"

        else:
            result_text += f"❌ Xato: {requests_result['error']}\n"

        await message.answer(result_text)


@router.message(Command("raw_check"))
async def raw_api_check(message: Message):
    """Raw API bilan join requestlarni tekshirish"""
    user_id = message.from_user.id

    channels = await db.get_active_channels()

    for channel in channels[:2]:  # Faqat birinchi 2 tasi
        channel_id = channel['channel_id']

        # Raw API chaqiruvi
        requests_result = await raw_get_chat_join_requests(message.bot.token, channel_id, 50)

        result_text = f"📺 <b>{channel['channel_name']}</b>\n\n"

        if requests_result["success"]:
            requests = requests_result["requests"]
            total_count = requests_result["total_count"]

            result_text += f"📋 Jami pending requests: {total_count}\n"

            # Foydalanuvchini qidirish
            found_user = False
            for request in requests:
                if request.get("from", {}).get("id") == user_id:
                    found_user = True
                    result_text += f"✅ <b>Sizning requestingiz topildi!</b>\n"
                    result_text += f"📅 Sana: {request.get('date', 'N/A')}\n"
                    if request.get("bio"):
                        result_text += f"📝 Bio: {request['bio']}\n"
                    break

            if not found_user:
                result_text += f"❌ Sizning requestingiz topilmadi\n"

            result_text += f"\n📝 Oxirgi 5 ta request:\n"
            for request in requests[:5]:
                user_info = request.get("from", {})
                result_text += f"• {user_info.get('first_name', 'N/A')} (ID: {user_info.get('id')})\n"

        else:
            result_text += f"❌ Xato: {requests_result['error']}\n"

        await message.answer(result_text)


async def check_user_channel_status_detailed(bot, chat_id, user_id):
    """Foydalanuvchi holatini batafsil tekshirish"""
    try:
        # Bot admin ekanligini tekshirish
        try:
            bot_member = await bot.get_chat_member(chat_id, bot.id)
            bot_is_admin = bot_member.status in ['administrator', 'creator']
        except:
            bot_is_admin = False

        # Foydalanuvchi holatini olish
        member = await bot.get_chat_member(chat_id, user_id)

        result = {
            "status": member.status,
            "bot_is_admin": bot_is_admin,
            "interpretation": "",
            "likely_pending": False,
            "can_join": True
        }

        # Status bo'yicha tahlil
        if member.status == "left":
            result["interpretation"] = "Kanalga qo'shilmagan"
            result["likely_pending"] = False
            result["can_join"] = True

        elif member.status == "member":
            result["interpretation"] = "Faol a'zo"
            result["likely_pending"] = False
            result["can_join"] = False  # Allaqachon a'zo

        elif member.status == "administrator":
            result["interpretation"] = "Administrator"
            result["likely_pending"] = False
            result["can_join"] = False

        elif member.status == "creator":
            result["interpretation"] = "Kanal yaratuvchisi"
            result["likely_pending"] = False
            result["can_join"] = False

        elif member.status == "restricted":
            is_member = getattr(member, 'is_member', False)
            if is_member:
                result["interpretation"] = "Cheklangan a'zo"
                result["likely_pending"] = False
                result["can_join"] = False
            else:
                result["interpretation"] = "Request yuborgan yoki cheklangan"
                result["likely_pending"] = True
                result["can_join"] = False

        elif member.status == "kicked":
            result["interpretation"] = "Kanaldan chiqarilgan"
            result["likely_pending"] = False
            result["can_join"] = False

        else:
            result["interpretation"] = f"Noma'lum status: {member.status}"
            result["likely_pending"] = False
            result["can_join"] = True

        # Qo'shimcha ma'lumotlar
        if hasattr(member, 'until_date') and member.until_date:
            result["until_date"] = member.until_date

        if hasattr(member, 'can_send_messages'):
            result["can_send_messages"] = member.can_send_messages

        return result

    except Exception as e:
        return {"error": str(e)}


# Raw API chaqiruvi (agar kerak bo'lsa)
async def raw_get_chat_join_requests(bot_token, chat_id, limit=20):
    """Raw API orqali join requestlarni olish"""
    import aiohttp

    try:
        url = f"https://api.telegram.org/bot{bot_token}/getChatJoinRequests"
        params = {
            "chat_id": chat_id,
            "limit": limit
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=params) as response:
                result = await response.json()

                if result.get("ok"):
                    return {
                        "success": True,
                        "requests": result.get("result", {}).get("requests", []),
                        "total_count": result.get("result", {}).get("total_count", 0)
                    }
                else:
                    return {
                        "success": False,
                        "error": result.get("description", "API xatosi")
                    }

    except Exception as e:
        return {"success": False, "error": str(e)}


# Sodda va ishonchli tekshirish
@router.message(Command("simple_check"))
async def simple_channel_check(message: Message):
    """Oddiy va ishonchli kanal tekshiruvi"""
    user_id = message.from_user.id

    await message.answer("🔍 Kanallaringiz tekshirilmoqda...")

    channels = await db.get_active_channels()

    summary = {
        "joined": [],
        "likely_pending": [],
        "not_joined": [],
        "blocked": [],
        "errors": []
    }

    for channel in channels:
        channel_id = channel['channel_id']
        channel_name = channel['channel_name']

        status_info = await check_user_channel_status_detailed(message.bot, channel_id, user_id)

        if status_info.get("error"):
            summary["errors"].append({"name": channel_name, "error": status_info["error"]})
            continue

        status = status_info["status"]

        if status in ["member", "administrator", "creator"]:
            summary["joined"].append(channel_name)
        elif status_info["likely_pending"]:
            summary["likely_pending"].append(channel_name)
        elif status == "kicked":
            summary["blocked"].append(channel_name)
        else:
            summary["not_joined"].append(channel_name)

    # Natijani ko'rsatish
    result_text = "📊 <b>Kanallar holati:</b>\n\n"

    if summary["joined"]:
        result_text += f"✅ <b>Qo'shilgan ({len(summary['joined'])}):</b>\n"
        for name in summary["joined"]:
            result_text += f"• {name}\n"
        result_text += "\n"

    if summary["likely_pending"]:
        result_text += f"⏳ <b>Request yuborgan ({len(summary['likely_pending'])}):</b>\n"
        for name in summary["likely_pending"]:
            result_text += f"• {name}\n"
        result_text += "\n"

    if summary["not_joined"]:
        result_text += f"❌ <b>Qo'shilmagan ({len(summary['not_joined'])}):</b>\n"
        for name in summary["not_joined"]:
            result_text += f"• {name}\n"
        result_text += "\n"

    if summary["blocked"]:
        result_text += f"🚫 <b>Bloklanган ({len(summary['blocked'])}):</b>\n"
        for name in summary["blocked"]:
            result_text += f"• {name}\n"
        result_text += "\n"

    if summary["errors"]:
        result_text += f"⚠️ <b>Xatolar ({len(summary['errors'])}):</b>\n"
        for item in summary["errors"]:
            result_text += f"• {item['name']}: {item['error'][:50]}...\n"

    await message.answer(result_text)


# FAQAT TEKSHIRISH - hech narsa tasdiqlamaslik/bekor qilmaslik

async def check_user_pending_requests(bot_token, chat_id, user_id):
    """Foydalanuvchining pending requestini faqat tekshirish"""
    import aiohttp

    try:
        url = f"https://api.telegram.org/bot{bot_token}/getChatJoinRequests"
        data = {"chat_id": chat_id, "limit": 50}

        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=data) as response:
                result = await response.json()

                if result.get("ok"):
                    requests = result.get("result", {}).get("requests", [])
                    total_count = result.get("result", {}).get("total_count", 0)

                    # Foydalanuvchini qidirish
                    for request in requests:
                        if request.get("from", {}).get("id") == user_id:
                            return {
                                "found": True,
                                "date": request.get("date"),
                                "bio": request.get("bio"),
                                "total_pending": total_count
                            }

                    return {
                        "found": False,
                        "total_pending": total_count
                    }
                else:
                    return {"error": result.get("description", "API xatosi")}

    except Exception as e:
        return {"error": str(e)}


async def simple_member_status_check(bot, chat_id, user_id):
    """Oddiy member status tekshiruvi"""
    try:
        member = await bot.get_chat_member(chat_id, user_id)

        if member.status == "member":
            return {"status": "member", "message": "✅ Siz allaqachon a'zosiz"}
        elif member.status == "administrator":
            return {"status": "admin", "message": "👑 Siz adminsiz"}
        elif member.status == "creator":
            return {"status": "creator", "message": "👑 Siz yaratuvchisiz"}
        elif member.status == "left":
            return {"status": "left", "message": "❌ Kanalga qo'shilmadingiz"}
        elif member.status == "kicked":
            return {"status": "kicked", "message": "🚫 Kanaldan chiqarilgansiz"}
        elif member.status == "restricted":
            is_member = getattr(member, 'is_member', False)
            if is_member:
                return {"status": "restricted_member", "message": "⚠️ Cheklangan a'zo"}
            else:
                return {"status": "restricted_pending", "message": "⏳ Request yuborgan (pending)"}
        else:
            return {"status": member.status, "message": f"🤔 Noma'lum status: {member.status}"}

    except Exception as e:
        return {"error": str(e)}


# Asosiy tekshirish komandasi
@router.message(Command("my_status"))
async def check_my_channel_status(message: Message):
    """Mening barcha kanallar bo'yicha holatim - FAQAT TEKSHIRISH"""
    user_id = message.from_user.id

    await message.answer("🔍 Sizning holatingiz tekshirilmoqda...")

    channels = await db.get_active_channels()

    summary = {
        "member": [],
        "pending": [],
        "not_joined": [],
        "blocked": [],
        "pending_confirmed": []  # API orqali tasdiqlangan pending requestlar
    }

    for channel in channels:
        channel_id = channel['channel_id']
        channel_name = channel['channel_name']

        # 1. Member statusini tekshirish
        status_info = await simple_member_status_check(message.bot, channel_id, user_id)

        channel_result = {
            "name": channel_name,
            "member_status": status_info.get("status"),
            "member_message": status_info.get("message"),
            "api_confirmed": False,
            "api_message": ""
        }

        # 2. Agar "pending" ko'rinsa, API orqali tasdiqlash
        if status_info.get("status") == "restricted_pending":
            api_check = await check_user_pending_requests(message.bot.token, channel_id, user_id)

            if api_check.get("error"):
                channel_result["api_message"] = f"API xatosi: {api_check['error']}"
            elif api_check.get("found"):
                channel_result["api_confirmed"] = True
                channel_result["api_message"] = f"✅ API tasdiqladi (Pending: {api_check['total_pending']})"
                summary["pending_confirmed"].append(channel_result)
            else:
                channel_result["api_message"] = f"❌ API tasdiqlamadi (Pending: {api_check.get('total_pending', 0)})"
                summary["not_joined"].append(channel_result)
        else:
            # Status bo'yicha kategoriyalarga ajratish
            if status_info.get("status") in ["member", "admin", "creator"]:
                summary["member"].append(channel_result)
            elif status_info.get("status") == "kicked":
                summary["blocked"].append(channel_result)
            else:
                summary["not_joined"].append(channel_result)

    # Natijalarni ko'rsatish
    if summary["member"]:
        result_text = f"✅ <b>A'zo bo'lgan kanallar ({len(summary['member'])}):</b>\n"
        for ch in summary["member"]:
            result_text += f"• {ch['name']}: {ch['member_message']}\n"
        result_text += "\n"
        await message.answer(result_text)

    if summary["pending_confirmed"]:
        result_text = f"⏳ <b>Request yuborgan kanallar ({len(summary['pending_confirmed'])}):</b>\n"
        for ch in summary["pending_confirmed"]:
            result_text += f"• {ch['name']}\n"
            result_text += f"  📊 Status: {ch['member_message']}\n"
            result_text += f"  🔍 API: {ch['api_message']}\n\n"
        await message.answer(result_text)

    if summary["not_joined"]:
        result_text = f"❌ <b>Qo'shilmagan kanallar ({len(summary['not_joined'])}):</b>\n"
        for ch in summary["not_joined"]:
            result_text += f"• {ch['name']}: {ch['member_message']}\n"
            if ch['api_message']:
                result_text += f"  🔍 {ch['api_message']}\n"
        result_text += "\n"
        await message.answer(result_text)

    if summary["blocked"]:
        result_text = f"🚫 <b>Bloklangan kanallar ({len(summary['blocked'])}):</b>\n"
        for ch in summary["blocked"]:
            result_text += f"• {ch['name']}: {ch['member_message']}\n"
        await message.answer(result_text)

    # Umumiy xulosa
    total_pending = len(summary["pending_confirmed"])
    total_member = len(summary["member"])
    total_channels = len(channels)

    summary_text = f"📊 <b>Umumiy natija:</b>\n\n"
    summary_text += f"👥 A'zo: {total_member}/{total_channels}\n"
    summary_text += f"⏳ Pending: {total_pending}/{total_channels}\n"
    summary_text += f"❌ Qo'shilmagan: {len(summary['not_joined'])}/{total_channels}\n"
    summary_text += f"🚫 Bloklangan: {len(summary['blocked'])}/{total_channels}\n\n"

    if total_member == total_channels:
        summary_text += f"🎉 Barcha kanallarga qo'shildingiz!"
    elif total_pending > 0:
        summary_text += f"⏳ {total_pending} ta kanalda requestingiz admin tasdiqini kutmoqda"
    else:
        summary_text += f"💡 Qo'shilmagan kanallarga request yuboring"

    await message.answer(summary_text)


# Bitta kanal uchun batafsil tekshirish
@router.message(Command("check_channel"))
async def check_specific_channel(message: Message):
    """Muayyan kanal uchun batafsil tekshirish"""
    # Format: /check_channel channel_id
    args = message.text.split()
    if len(args) != 2:
        channels = await db.get_active_channels()
        channels_list = "\n".join([f"• {ch['channel_name']}: {ch['channel_id']}" for ch in channels])
        await message.answer(f"❌ Format: /check_channel <channel_id>\n\n📺 Mavjud kanallar:\n{channels_list}")
        return

    try:
        channel_id = int(args[1])
    except ValueError:
        await message.answer("❌ Channel ID raqam bo'lishi kerak")
        return

    user_id = message.from_user.id

    # Kanal nomini topish
    channels = await db.get_active_channels()
    channel_name = "Noma'lum kanal"
    for ch in channels:
        if str(ch['channel_id']) == str(channel_id):
            channel_name = ch['channel_name']
            break

    await message.answer(f"🔍 {channel_name} uchun batafsil tekshirish...")

    # 1. Member status
    status_info = await simple_member_status_check(message.bot, channel_id, user_id)

    result_text = f"📺 <b>{channel_name}</b>\n"
    result_text += f"🆔 ID: <code>{channel_id}</code>\n\n"

    if status_info.get("error"):
        result_text += f"❌ Xato: {status_info['error']}\n"
        await message.answer(result_text)
        return

    result_text += f"👤 <b>Member Status:</b>\n"
    result_text += f"Status: <code>{status_info['status']}</code>\n"
    result_text += f"Ma'no: {status_info['message']}\n\n"

    # 2. API tekshiruvi (agar pending bo'lsa)
    if status_info.get("status") == "restricted_pending":
        api_check = await check_user_pending_requests(message.bot.token, channel_id, user_id)

        result_text += f"🔍 <b>API Tekshiruvi:</b>\n"

        if api_check.get("error"):
            result_text += f"❌ Xato: {api_check['error']}\n"
        elif api_check.get("found"):
            result_text += f"✅ <b>Pending request tasdiqlandi!</b>\n"
            result_text += f"📅 Sana: {api_check.get('date', 'N/A')}\n"
            if api_check.get("bio"):
                result_text += f"📝 Bio: {api_check['bio']}\n"
            result_text += f"📊 Jami pending: {api_check.get('total_pending', 'N/A')}\n"
        else:
            result_text += f"❌ API pending request tasdiqlamadi\n"
            result_text += f"📊 Jami pending: {api_check.get('total_pending', 0)}\n"
    else:
        result_text += f"💡 <b>Tavsiya:</b>\n"
        if status_info.get("status") == "left":
            result_text += f"📤 Kanalga join request yuboring\n"
        elif status_info.get("status") in ["member", "admin", "creator"]:
            result_text += f"🎉 Hech narsa qilish kerak emas\n"
        elif status_info.get("status") == "kicked":
            result_text += f"🚫 Kanaldan chiqarilgansiz\n"

    await message.answer(result_text)


# Qisqa holat tekshiruvi
@router.message(Command("quick_status"))
async def quick_channel_status(message: Message):
    """Tezkor holat tekshiruvi"""
    user_id = message.from_user.id
    channels = await db.get_active_channels()

    status_text = f"⚡ <b>Tezkor holat:</b>\n\n"

    for channel in channels:
        status_info = await simple_member_status_check(message.bot, channel['channel_id'], user_id)

        if status_info.get("error"):
            icon = "❌"
        elif status_info.get("status") in ["member", "admin", "creator"]:
            icon = "✅"
        elif status_info.get("status") == "restricted_pending":
            icon = "⏳"
        elif status_info.get("status") == "kicked":
            icon = "🚫"
        else:
            icon = "❌"

        status_text += f"{icon} {channel['channel_name']}\n"

    await message.answer(status_text)