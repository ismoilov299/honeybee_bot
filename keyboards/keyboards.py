from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from typing import List, Dict


def get_start_keyboard() -> ReplyKeyboardMarkup:
    """Boshlang'ich keyboard"""
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="✅ Tekshirish")],

        ],
        resize_keyboard=True
    )
    return keyboard


def get_admin_keyboard() -> ReplyKeyboardMarkup:
    """Admin keyboard"""
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="➕ Kanal qo'shish"), KeyboardButton(text="➖ Kanal o'chirish")],
            [KeyboardButton(text="🗑 Barcha kanallarni o'chirish"), KeyboardButton(text="📊 Statistika")],
            [KeyboardButton(text="📝 Content o'rnatish"), KeyboardButton(text="🖼 Taklif rasmi")],
            [KeyboardButton(text="📢 Xabar yuborish"), KeyboardButton(text="🔙 Orqaga")]
        ],
        resize_keyboard=True
    )
    return keyboard


def get_channels_keyboard(channels: List[Dict], user_channels: List[Dict]) -> InlineKeyboardMarkup:
    """Kanallar ro'yxati keyboard"""
    builder = InlineKeyboardBuilder()

    # User qo'shilgan kanallarni tekshirish
    joined_channels = {ch['channel_id']: ch.get('joined', 0) for ch in user_channels}

    for channel in channels:
        status = "✅" if joined_channels.get(str(channel['id']), 0) else "❌"
        text = f"{status} {channel['channel_name']}"

        if channel['channel_link']:
            builder.button(
                text=text,
                url=channel['channel_link']
            )
        else:
            builder.button(
                text=text,
                callback_data=f"channel_{channel['id']}"
            )

    builder.button(
        text="🔄 Tekshirish",
        callback_data="check_channels"
    )

    builder.adjust(1)
    return builder.as_markup()


def get_offer_keyboard() -> ReplyKeyboardMarkup:
    """Taklif posti olish uchun keyboard"""
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Taklif postini olish")]
        ],
        resize_keyboard=True
    )
    return keyboard

def get_cancel_keyboard() -> ReplyKeyboardMarkup:
    """Bekor qilish keyboard"""
    keyboard = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="❌ Bekor qilish")]],
        resize_keyboard=True
    )
    return keyboard