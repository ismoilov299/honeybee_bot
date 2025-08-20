import logging
from aiogram import Router, F
from aiogram.types import Message, ReplyKeyboardRemove
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from config import settings
from database.database import db
from keyboards.keyboards import get_admin_keyboard, get_start_keyboard, get_cancel_keyboard

router = Router()
logger = logging.getLogger(__name__)


class AdminStates(StatesGroup):
    waiting_for_channel_data = State()
    waiting_for_channel_to_remove = State()
    waiting_for_content = State()
    waiting_for_invitation_image = State()
    waiting_for_broadcast = State()
    waiting_for_clear_confirmation = State()


def is_admin(user_id: int) -> bool:
    """Admin ekanligini tekshirish"""
    return user_id in settings.ADMIN_IDS


@router.message(Command("admin"))
async def admin_panel(message: Message, state: FSMContext):
    """Admin panel"""
    if not is_admin(message.from_user.id):
        await message.answer("❌ Sizda admin huquqi yo'q!")
        return

    await state.clear()
    await message.answer(
        "👨‍💼 <b>Admin Panel</b>\n\n"
        "Kerakli amalni tanlang:",
        reply_markup=get_admin_keyboard()
    )


@router.message(F.text == "➕ Kanal qo'shish")
async def add_channel_start(message: Message, state: FSMContext):
    """Kanal qo'shishni boshlash"""
    if not is_admin(message.from_user.id):
        return

    await message.answer(
        "📝 Kanal ma'lumotlarini quyidagi formatda yuboring:\n\n"
        "<b>Private kanallar uchun (Chat ID):</b>\n"
        "<code>-1001234567890|Kanal nomi|https://t.me/+xxxxxxxxxx</code>\n\n"
        "<b>Public kanallar uchun (Username):</b>\n"
        "<code>@channel_username|Kanal nomi|https://t.me/username</code>\n\n"
        "<b>Invite link orqali (avtomatik ID aniqlash):</b>\n"
        "<code>https://t.me/+PIRvJVNy8mthMGM6|Kanal nomi|https://t.me/+PIRvJVNy8mthMGM6</code>\n\n"
        "📋 <b>Formatlar:</b>\n"
        "• Chat ID: -100 bilan boshlanadigan raqam\n"
        "• Username: @ belgisi bilan\n"
        "• Invite link: https://t.me/+ bilan boshlanadigan link\n\n"
        "💡 <b>Chat ID ni qanday topish:</b>\n"
        "1. Botni kanalga admin qiling\n"
        "2. Kanalda botni mention qiling\n"
        "3. Bot loglarida chat ID ko'rinadi\n\n"
        "🔗 <b>Yoki invite linkni to'g'ridan-to'g'ri ishlatishingiz mumkin!</b>",
        reply_markup=get_cancel_keyboard()
    )
    await state.set_state(AdminStates.waiting_for_channel_data)


@router.message(AdminStates.waiting_for_channel_data)
async def add_channel_process(message: Message, state: FSMContext):
    """Kanal qo'shishni yakunlash"""
    if message.text == "❌ Bekor qilish":
        await state.clear()
        await message.answer("❌ Bekor qilindi.", reply_markup=get_admin_keyboard())
        return

    try:
        parts = message.text.split('|')
        if len(parts) != 3:
            await message.answer(
                "❌ Noto'g'ri format!\n\n"
                "To'g'ri formatlar:\n"
                "<code>-1001234567890|Kanal nomi|https://t.me/+link</code>\n"
                "<code>@username|Kanal nomi|https://t.me/username</code>\n"
                "<code>https://t.me/+xxxxxx|Kanal nomi|https://t.me/+xxxxxx</code>"
            )
            return

        channel_id = parts[0].strip()
        channel_name = parts[1].strip()
        channel_link = parts[2].strip()

        # Channel ID formatini tekshirish va avtomatik aniqlash
        channel_type = "Unknown"

        if channel_id.startswith('-100'):
            # Chat ID format
            try:
                int(channel_id)  # Raqam ekanligini tekshirish
                channel_type = "Private (Chat ID)"
            except ValueError:
                await message.answer("❌ Chat ID raqam bo'lishi kerak! Misol: -1001234567890")
                return

        elif channel_id.startswith('@'):
            # Username format
            channel_type = "Public (Username)"

        elif channel_id.startswith('https://t.me/+'):
            # Invite link format - bu holatda link ni ID sifatida saqlaymiz
            channel_type = "Private (Invite Link)"
            # Invite linkdan foydalanish uchun linkni ID sifatida saqlaymiz

        else:
            await message.answer(
                "❌ Kanal ID/Link noto'g'ri formatda!\n\n"
                "✅ Private kanal (Chat ID): <code>-1001234567890</code>\n"
                "✅ Public kanal (Username): <code>@username</code>\n"
                "✅ Invite link: <code>https://t.me/+xxxxxxxx</code>\n\n"
                "Qaytadan kiriting:"
            )
            return

        success = await db.add_channel(channel_id, channel_name, channel_link)

        if success:
            await message.answer(
                f"✅ Kanal muvaffaqiyatli qo'shildi!\n\n"
                f"📱 ID/Link: <code>{channel_id}</code>\n"
                f"📝 Nomi: {channel_name}\n"
                f"🔗 Link: {channel_link}\n"
                f"🏷 Turi: {channel_type}\n\n"
                f"⚠️ <b>Eslatma:</b> Invite link orqali a'zolikni tekshirish uchun botni kanalga admin qilishni unutmang!",
                reply_markup=get_admin_keyboard()
            )
        else:
            await message.answer(
                "❌ Kanal qo'shilmadi!\n\n"
                "Ehtimol bu kanal allaqachon mavjud yoki database xatosi yuz berdi.",
                reply_markup=get_admin_keyboard()
            )
    except Exception as e:
        logger.error(f"Kanal qo'shishda xato: {e}")
        await message.answer(
            "❌ Xato yuz berdi! Formatni tekshiring:\n\n"
            "📋 To'g'ri formatlar:\n"
            "<code>-1001234567890|Kanal nomi|https://t.me/+link</code>\n"
            "<code>@username|Kanal nomi|https://t.me/username</code>\n"
            "<code>https://t.me/+xxxxxx|Kanal nomi|https://t.me/+xxxxxx</code>",
            reply_markup=get_admin_keyboard()
        )

    await state.clear()


@router.message(F.text == "➖ Kanal o'chirish")
async def remove_channel_start(message: Message, state: FSMContext):
    """Kanal o'chirishni boshlash"""
    if not is_admin(message.from_user.id):
        return

    channels = await db.get_active_channels()
    if not channels:
        await message.answer("❌ Aktiv kanallar yo'q!", reply_markup=get_admin_keyboard())
        return

    channels_text = "📝 Aktiv kanallar:\n\n"
    for channel in channels:
        channels_text += f"• {channel['channel_id']} - {channel['channel_name']}\n"

    channels_text += "\n📱 O'chirish uchun kanal ID sini yuboring:"

    await message.answer(channels_text, reply_markup=get_cancel_keyboard())
    await state.set_state(AdminStates.waiting_for_channel_to_remove)


@router.message(AdminStates.waiting_for_channel_to_remove)
async def remove_channel_process(message: Message, state: FSMContext):
    """Kanal o'chirishni yakunlash"""
    if message.text == "❌ Bekor qilish":
        await state.clear()
        await message.answer("❌ Bekor qilindi.", reply_markup=get_admin_keyboard())
        return

    channel_id = message.text.strip()

    success = await db.remove_channel(channel_id)
    if success:
        await message.answer(
            f"✅ Kanal o'chirildi: {channel_id}",
            reply_markup=get_admin_keyboard()
        )
    else:
        await message.answer(
            "❌ Kanal topilmadi yoki o'chirilmadi!",
            reply_markup=get_admin_keyboard()
        )

    await state.clear()


@router.message(F.text == "📊 Statistika")
async def show_stats(message: Message):
    """Statistikani ko'rsatish"""
    if not is_admin(message.from_user.id):
        return

    stats = await db.get_stats()

    stats_text = f"""
📊 <b>Bot Statistikasi</b>

👥 Jami foydalanuvchilar: {stats['total_users']}
✅ Vazifani bajarganlar: {stats['completed_users']}
📺 Aktiv kanallar: {stats['active_channels']}

📈 Foizlar:
• Bajarganlar: {(stats['completed_users'] / stats['total_users'] * 100) if stats['total_users'] > 0 else 0:.1f}%
    """

    await message.answer(stats_text, reply_markup=get_admin_keyboard())


@router.message(F.text == "📝 Content o'rnatish")
async def set_content_start(message: Message, state: FSMContext):
    """Content o'rnatishni boshlash"""
    if not is_admin(message.from_user.id):
        return

    await message.answer(
        "📝 Yangi content yuklang.\n\n"
        "Quyidagi formatda yuboring:\n"
        "<code>Sarlavha|Matn content</code>\n\n"
        "Yoki faqat rasm ham yuborishingiz mumkin.\n\n"
        "Misol:\n"
        "<code>Bepul Python Kursi|Bu kursda siz Python dasturlash tilini o'rganasiz...</code>",
        reply_markup=get_cancel_keyboard()
    )
    await state.set_state(AdminStates.waiting_for_content)


@router.message(AdminStates.waiting_for_content)
async def set_content_process(message: Message, state: FSMContext):
    """Content o'rnatishni yakunlash"""
    if message.text == "❌ Bekor qilish":
        await state.clear()
        await message.answer("❌ Bekor qilindi.", reply_markup=get_admin_keyboard())
        return

    try:
        title = "Bepul Darsliklar"
        text_content = ""
        image_path = None

        # Agar matn yuborilgan bo'lsa
        if message.text:
            if '|' in message.text:
                parts = message.text.split('|', 1)
                title = parts[0].strip()
                text_content = parts[1].strip()
            else:
                text_content = message.text.strip()

        # Agar rasm yuborilgan bo'lsa
        if message.photo:
            # Bu yerda rasmni saqlash logikasini qo'shish kerak
            # Hozircha faqat file_id ni saqlaymiz
            image_path = message.photo[-1].file_id
            if message.caption:
                if '|' in message.caption:
                    parts = message.caption.split('|', 1)
                    title = parts[0].strip()
                    text_content = parts[1].strip()
                else:
                    text_content = message.caption.strip()

        await db.set_content(title, text_content, image_path)

        await message.answer(
            f"✅ Content o'rnatildi!\n\n"
            f"📝 Sarlavha: {title}\n"
            f"📄 Matn: {text_content[:100]}{'...' if len(text_content) > 100 else ''}\n"
            f"🖼 Rasm: {'Ha' if image_path else 'Yoq'}",
            reply_markup=get_admin_keyboard()
        )

    except Exception as e:
        logger.error(f"Content o'rnatishda xato: {e}")
        await message.answer("❌ Xato yuz berdi!", reply_markup=get_admin_keyboard())

    await state.clear()


@router.message(F.text == "🖼 Taklif rasmi")
async def set_invitation_image_start(message: Message, state: FSMContext):
    """Taklif rasmi o'rnatishni boshlash"""
    if not is_admin(message.from_user.id):
        return

    current_image = await db.get_invitation_image()
    status_text = "✅ O'rnatilgan" if current_image else "❌ O'rnatilmagan"

    await message.answer(
        f"🖼 <b>Taklif posti uchun rasm yuklash</b>\n\n"
        f"📊 Hozirgi holat: {status_text}\n\n"
        f"Bu rasm taklif posti bilan birga foydalanuvchilarga ko'rsatiladi.\n\n"
        f"📷 Yangi rasm yuklang:",
        reply_markup=get_cancel_keyboard()
    )
    await state.set_state(AdminStates.waiting_for_invitation_image)


@router.message(AdminStates.waiting_for_invitation_image)
async def set_invitation_image_process(message: Message, state: FSMContext):
    """Taklif rasmi o'rnatishni yakunlash"""
    if message.text == "❌ Bekor qilish":
        await state.clear()
        await message.answer("❌ Bekor qilindi.", reply_markup=get_admin_keyboard())
        return

    if not message.photo:
        await message.answer("❌ Iltimos, rasm yuklang!")
        return

    try:
        # Rasmni yuklab olish
        photo = message.photo[-1]  # Eng katta o'lchamdagi rasmni olish
        file_info = await message.bot.get_file(photo.file_id)

        # Faylni yuklab olish
        import os
        import uuid

        # uploads papkasini yaratish
        os.makedirs("uploads", exist_ok=True)

        # Unique fayl nomi yaratish
        file_extension = file_info.file_path.split('.')[-1] if '.' in file_info.file_path else 'jpg'
        filename = f"{uuid.uuid4().hex}.{file_extension}"
        local_path = f"uploads/{filename}"

        # Faylni serverga yuklab olish
        await message.bot.download_file(file_info.file_path, local_path)

        # Database'dagi contentni yangilash
        await db.set_invitation_image(local_path)

        await message.answer(
            f"✅ Taklif rasmi muvaffaqiyatli yuklandi va saqlandi!\n\n"
            f"📁 Fayl yo'li: {local_path}\n"
            f"📊 Fayl hajmi: {os.path.getsize(local_path)} bytes\n\n"
            f"Endi foydalanuvchilar bu rasmni taklif posti bilan birga olishlari mumkin.",
            reply_markup=get_admin_keyboard()
        )

    except Exception as e:
        logger.error(f"Taklif rasmi saqlashda xato: {e}")
        await message.answer(f"❌ Xato yuz berdi: {str(e)}", reply_markup=get_admin_keyboard())

    await state.clear()


@router.message(F.text == "🗑 Barcha kanallarni o'chirish")
async def remove_all_channels_start(message: Message, state: FSMContext):
    """Barcha kanallarni o'chirishni boshlash"""
    if not is_admin(message.from_user.id):
        return

    # Aktiv kanallar sonini tekshirish
    channels = await db.get_active_channels()
    if not channels:
        await message.answer("❌ O'chirish uchun aktiv kanallar yo'q!", reply_markup=get_admin_keyboard())
        return

    # Tasdiqlash so'rovi
    confirm_text = f"""
⚠️ <b>DIQQAT: Barcha kanallarni o'chirish</b>

📊 Jami aktiv kanallar: {len(channels)}

📋 <b>O'chiriladigan kanallar:</b>
"""

    for channel in channels:
        confirm_text += f"• {channel['channel_name']}\n"

    confirm_text += f"""
🚨 <b>Bu amal qaytarib bo'lmaydi!</b>

Davom etish uchun <code>TASDIQLASH</code> deb yozing yoki "❌ Bekor qilish" tugmasini bosing.
    """

    await message.answer(confirm_text, reply_markup=get_cancel_keyboard())
    await state.set_state(AdminStates.waiting_for_clear_confirmation)


@router.message(AdminStates.waiting_for_clear_confirmation)
async def remove_all_channels_process(message: Message, state: FSMContext):
    """Barcha kanallarni o'chirishni yakunlash"""
    if message.text == "❌ Bekor qilish":
        await state.clear()
        await message.answer("❌ Bekor qilindi.", reply_markup=get_admin_keyboard())
        return

    if message.text != "TASDIQLASH":
        await message.answer("❌ Noto'g'ri! 'TASDIQLASH' deb yozing yoki 'Bekor qilish' tugmasini bosing.")
        return

    try:
        # Barcha kanallarni o'chirish
        removed_count = await db.remove_all_channels()

        if removed_count > 0:
            await message.answer(
                f"✅ <b>Barcha kanallar o'chirildi!</b>\n\n"
                f"📊 O'chirilgan kanallar soni: {removed_count}\n\n"
                f"💡 Yangi kanallar qo'shish uchun '➕ Kanal qo'shish' tugmasini ishlatishingiz mumkin.",
                reply_markup=get_admin_keyboard()
            )
        else:
            await message.answer(
                "❌ O'chirish uchun aktiv kanallar topilmadi.",
                reply_markup=get_admin_keyboard()
            )

    except Exception as e:
        logger.error(f"Barcha kanallarni o'chirishda xato: {e}")
        await message.answer("❌ Xato yuz berdi!", reply_markup=get_admin_keyboard())

    await state.clear()


@router.message(F.text == "📢 Xabar yuborish")
async def broadcast_start(message: Message, state: FSMContext):
    """Umumiy xabar yuborishni boshlash"""
    if not is_admin(message.from_user.id):
        return

    await message.answer(
        "📢 Barcha foydalanuvchilarga yuborilecek xabarni kiriting:\n\n"
        "💡 HTML formatidan foydalanishingiz mumkin.",
        reply_markup=get_cancel_keyboard()
    )
    await state.set_state(AdminStates.waiting_for_broadcast)


@router.message(AdminStates.waiting_for_broadcast)
async def broadcast_process(message: Message, state: FSMContext):
    """Umumiy xabar yuborishni yakunlash"""
    if message.text == "❌ Bekor qilish":
        await state.clear()
        await message.answer("❌ Bekor qilindi.", reply_markup=get_admin_keyboard())
        return

    # Bu yerda broadcast logikasini qo'shish kerak
    # Hozircha shunchaki tasdiqlash xabari yuboramiz
    await message.answer(
        "📢 Xabar yuborilmoqda...\n\n"
        "⚠️ Bu funksiya hali ishlab chiqilmoqda.",
        reply_markup=get_admin_keyboard()
    )

    await state.clear()


@router.message(F.text == "🔙 Orqaga")
async def back_to_user_mode(message: Message, state: FSMContext):
    """Foydalanuvchi rejimiga qaytish"""
    if not is_admin(message.from_user.id):
        return

    await state.clear()
    await message.answer(
        "👤 Foydalanuvchi rejimiga qaytdingiz.",
        reply_markup=get_start_keyboard()
    )