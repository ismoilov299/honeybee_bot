import asyncio
import logging
from typing import List
from aiogram import Bot

logger = logging.getLogger(__name__)


async def send_broadcast(bot: Bot, user_ids: List[int], text: str, photo: str = None):
    """Umumiy xabar yuborish"""
    success_count = 0
    failed_count = 0

    for user_id in user_ids:
        try:
            if photo:
                await bot.send_photo(user_id, photo, caption=text)
            else:
                await bot.send_message(user_id, text)
            success_count += 1
            await asyncio.sleep(0.1)  # Rate limiting uchun
        except Exception as e:
            logger.error(f"Foydalanuvchi {user_id} ga xabar yuborilmadi: {e}")
            failed_count += 1

    return success_count, failed_count


async def check_channel_membership(bot: Bot, user_id: int, channel_id: str) -> bool:
    """Kanalga a'zolikni tekshirish"""
    try:
        member = await bot.get_chat_member(channel_id, user_id)
        return member.status in ['member', 'administrator', 'creator']
    except Exception as e:
        logger.error(f"Kanal a'zoligini tekshirishda xato: {e}")
        return False