import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, FSInputFile
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
    not_joined_channels = []

    checking_message = await message.answer("⏳ Kanallar tekshirilmoqda...")

    for channel in channels:
        try:
            # Kanal ID ni olish (username, chat ID yoki invite link)
            channel_identifier = channel['channel_id']

            # Foydalanuvchining kanal a'zoligini tekshirish
            try:
                # Agar invite link bo'lsa, uni chat ID ga aylantirish kerak
                # Hozircha invite linklar uchun alohida logic qo'shamiz
                if channel_identifier.startswith('https://t.me/+'):
                    # Invite link uchun - botni avval kanalga admin qilish kerak
                    # Keyin get_chat orqali chat ma'lumotlarini olish mumkin
                    try:
                        # Invite linkdan chat ma'lumotini olishga harakat qilamiz
                        # Bu faqat bot admin bo'lgan kanallar uchun ishlaydi
                        chat_info = await message.bot.get_chat(channel_identifier)
                        chat_id = chat_info.id
                        member = await message.bot.get_chat_member(chat_id, user_id)
                    except Exception:
                        # Agar invite link orqali olib bo'lmasa, Chat ID dan foydalanish
                        member = await message.bot.get_chat_member(channel_identifier, user_id)
                else:
                    # Chat ID yoki username uchun oddiy tekshirish
                    member = await message.bot.get_chat_member(channel_identifier, user_id)

                # A'zolik statuslarini kengaytirib tekshirish
                if member.status in ['member', 'administrator', 'creator']:
                    # To'liq a'zo
                    joined_channels.append(channel)
                    await db.join_channel(user_id, channel['id'])
                elif member.status == 'restricted' and hasattr(member, 'is_member') and member.is_member:
                    # Cheklangan lekin a'zo
                    joined_channels.append(channel)
                    await db.join_channel(user_id, channel['id'])
                elif member.status == 'left':
                    # Request yuborilgan yoki yo'q - qo'shimcha tekshirish
                    # Private kanallarda pending request ni tekshirish
                    try:
                        # Agar chat_join_request orqali pending request bor bo'lsa
                        # Bu API Telegram Bot API da mavjud emas, shuning uchun
                        # biz foydalanuvchini "request yuborgan" deb hisoblaymiz
                        # agar u avval request yuborgan tugmasini bosgan bo'lsa

                        # Database'dan tekshiramiz - avval request yuborgan bo'lsa
                        user_channel_status = await db.get_user_channel_status(user_id, channel['id'])
                        if user_channel_status and user_channel_status.get('request_sent'):
                            # Request yuborgan deb belgilangan
                            joined_channels.append(channel)
                        else:
                            not_joined_channels.append(channel)
                    except:
                        not_joined_channels.append(channel)
                else:
                    # Boshqa holatlar (kicked, va h.k.)
                    not_joined_channels.append(channel)

            except Exception as e:
                logger.error(f"Kanal {channel_identifier} tekshirishda xato: {e}")
                # Xato bo'lsa ham request yuborgan deb tekshirish
                try:
                    user_channel_status = await db.get_user_channel_status(user_id, channel['id'])
                    if user_channel_status and user_channel_status.get('request_sent'):
                        joined_channels.append(channel)
                    else:
                        not_joined_channels.append(channel)
                except:
                    not_joined_channels.append(channel)

        except Exception as e:
            logger.error(f"Kanal ma'lumotlari olishda xato: {e}")
            not_joined_channels.append(channel)

    # Tekshirish xabarini o'chirish
    await checking_message.delete()

    # Natijani ko'rsatish
    if not_joined_channels:
        # Ba'zi kanallarga qo'shilmagan
        not_joined_text = "❌ <b>Quyidagi kanallarga request yuboring:</b>\n\n"
        for channel in not_joined_channels:
            not_joined_text += f"📌 <b>{channel['channel_name']}</b>\n"
            if channel['channel_link']:
                not_joined_text += f"🔗 {channel['channel_link']}\n\n"

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


    all_joined = await db.check_all_channels_joined(user_id)

    if all_joined:
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
        await callback.answer("❌ Barcha kanallarga qo'shilmadingiz!", show_alert=True)


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