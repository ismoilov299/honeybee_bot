import aiosqlite
import asyncio
from config import settings
from typing import Optional, List, Dict, Any


class Database:
    def __init__(self, db_path: str = settings.DATABASE_PATH):
        self.db_path = db_path

    async def init_db(self):
        """Database va jadvallarni yaratish"""
        async with aiosqlite.connect(self.db_path) as db:
            # Users jadvali
            await db.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_id INTEGER UNIQUE NOT NULL,
                    username TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    referral_code TEXT UNIQUE NOT NULL,
                    referred_by INTEGER,
                    completed_task INTEGER DEFAULT 0,
                    referral_count INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Channels jadvali
            await db.execute("""
                CREATE TABLE IF NOT EXISTS channels (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel_id TEXT UNIQUE NOT NULL,
                    channel_name TEXT NOT NULL,
                    channel_link TEXT,
                    is_active INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # User-Channel bog'lanish jadvali
            await db.execute("""
                CREATE TABLE IF NOT EXISTS user_channels (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    channel_id INTEGER NOT NULL,
                    joined INTEGER DEFAULT 0,
                    request_sent INTEGER DEFAULT 0,
                    joined_at TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (telegram_id),
                    FOREIGN KEY (channel_id) REFERENCES channels (id)
                )
            """)

            # Mavjud jadvalga ustun qo'shish (agar mavjud bo'lmasa)
            try:
                await db.execute("ALTER TABLE user_channels ADD COLUMN request_sent INTEGER DEFAULT 0")
            except:
                # Ustun allaqachon mavjud yoki boshqa xato
                pass

            # Content jadvali
            await db.execute("""
                CREATE TABLE IF NOT EXISTS content (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT,
                    text_content TEXT,
                    image_path TEXT,
                    invitation_image TEXT,
                    is_active INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            await db.commit()

    # User CRUD operatsiyalari
    async def create_user(self, telegram_id: int, username: str,
                          first_name: str, last_name: str,
                          referred_by: int = None) -> Optional[Dict]:
        import uuid
        referral_code = str(uuid.uuid4())[:8]

        async with aiosqlite.connect(self.db_path) as db:
            try:
                await db.execute("""
                    INSERT INTO users (telegram_id, username, first_name, 
                                     last_name, referral_code, referred_by)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (telegram_id, username, first_name, last_name,
                      referral_code, referred_by))
                await db.commit()
                return await self.get_user(telegram_id)
            except aiosqlite.IntegrityError:
                return None

    async def get_user(self, telegram_id: int) -> Optional[Dict]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                    "SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)
            ) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None

    async def get_user_by_referral(self, referral_code: str) -> Optional[Dict]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                    "SELECT * FROM users WHERE referral_code = ?", (referral_code,)
            ) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None

    async def update_referral_count(self, telegram_id: int):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                UPDATE users SET referral_count = referral_count + 1 
                WHERE telegram_id = ?
            """, (telegram_id,))
            await db.commit()

    async def complete_task(self, telegram_id: int):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                UPDATE users SET completed_task = 1 WHERE telegram_id = ?
            """, (telegram_id,))
            await db.commit()

    # Channel CRUD operatsiyalari
    async def add_channel(self, channel_id: str, channel_name: str,
                          channel_link: str = None) -> bool:
        async with aiosqlite.connect(self.db_path) as db:
            try:
                await db.execute("""
                    INSERT INTO channels (channel_id, channel_name, channel_link)
                    VALUES (?, ?, ?)
                """, (channel_id, channel_name, channel_link))
                await db.commit()
                return True
            except aiosqlite.IntegrityError:
                return False

    async def get_active_channels(self) -> List[Dict]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                    "SELECT * FROM channels WHERE is_active = 1"
            ) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]

    async def remove_channel(self, channel_id: str) -> bool:
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "UPDATE channels SET is_active = 0 WHERE channel_id = ?",
                (channel_id,)
            )
            await db.commit()
            return cursor.rowcount > 0

    async def remove_all_channels(self) -> int:
        """Barcha kanallarni o'chirish"""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "UPDATE channels SET is_active = 0 WHERE is_active = 1"
            )
            await db.commit()
            return cursor.rowcount

    # User-Channel bog'lanish
    async def join_channel(self, user_id: int, channel_id: int):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT OR REPLACE INTO user_channels 
                (user_id, channel_id, joined, joined_at)
                VALUES (?, ?, 1, CURRENT_TIMESTAMP)
            """, (user_id, channel_id))
            await db.commit()

    async def set_request_sent(self, user_id: int, channel_id: int):
        """Request yuborgan holatini belgilash"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT OR REPLACE INTO user_channels 
                (user_id, channel_id, joined, request_sent, joined_at)
                VALUES (?, ?, 0, 1, CURRENT_TIMESTAMP)
            """, (user_id, channel_id))
            await db.commit()

    async def get_user_channel_status(self, user_id: int, channel_id: int):
        """Foydalanuvchining kanal holatini olish"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("""
                SELECT * FROM user_channels 
                WHERE user_id = ? AND channel_id = ?
            """, (user_id, channel_id)) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None

    async def get_user_channels(self, user_id: int) -> List[Dict]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("""
                SELECT c.*, uc.joined FROM channels c
                LEFT JOIN user_channels uc ON c.id = uc.channel_id 
                AND uc.user_id = ?
                WHERE c.is_active = 1
            """, (user_id,)) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]

    async def check_all_channels_joined(self, user_id: int) -> bool:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("""
                SELECT COUNT(*) as total,
                       SUM(CASE WHEN uc.joined = 1 THEN 1 ELSE 0 END) as joined
                FROM channels c
                LEFT JOIN user_channels uc ON c.id = uc.channel_id 
                AND uc.user_id = ?
                WHERE c.is_active = 1
            """, (user_id,)) as cursor:
                row = await cursor.fetchone()
                total, joined = row
                return total > 0 and total == joined

    # Content CRUD operatsiyalari
    async def set_content(self, title: str, text_content: str,
                          image_path: str = None):
        async with aiosqlite.connect(self.db_path) as db:
            # Avvalgi contentni deaktiv qilish
            await db.execute("UPDATE content SET is_active = 0")

            # Yangi content qo'shish
            await db.execute("""
                INSERT INTO content (title, text_content, image_path)
                VALUES (?, ?, ?)
            """, (title, text_content, image_path))
            await db.commit()

    async def set_invitation_image(self, image_path: str):
        async with aiosqlite.connect(self.db_path) as db:
            # Avvalgi contentni olish
            async with db.execute(
                    "SELECT * FROM content WHERE is_active = 1 ORDER BY created_at DESC LIMIT 1"
            ) as cursor:
                row = await cursor.fetchone()

            if row:
                # Mavjud contentni yangilash
                await db.execute("""
                    UPDATE content SET invitation_image = ? WHERE id = ?
                """, (image_path, row[0]))
            else:
                # Yangi content yaratish
                await db.execute("""
                    INSERT INTO content (title, text_content, invitation_image)
                    VALUES (?, ?, ?)
                """, ("Bepul Darsliklar", "", image_path))

            await db.commit()

    async def get_invitation_image(self) -> str:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                    "SELECT invitation_image FROM content WHERE is_active = 1 AND invitation_image IS NOT NULL ORDER BY created_at DESC LIMIT 1"
            ) as cursor:
                row = await cursor.fetchone()
                return row[0] if row else None

    async def get_active_content(self) -> Optional[Dict]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                    "SELECT * FROM content WHERE is_active = 1 ORDER BY created_at DESC LIMIT 1"
            ) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None

    # Statistika
    async def get_stats(self) -> Dict:
        async with aiosqlite.connect(self.db_path) as db:
            stats = {}

            # Jami foydalanuvchilar
            async with db.execute("SELECT COUNT(*) FROM users") as cursor:
                stats['total_users'] = (await cursor.fetchone())[0]

            # Vazifani bajargan foydalanuvchilar
            async with db.execute(
                    "SELECT COUNT(*) FROM users WHERE completed_task = 1"
            ) as cursor:
                stats['completed_users'] = (await cursor.fetchone())[0]

            # Aktiv kanallar
            async with db.execute(
                    "SELECT COUNT(*) FROM channels WHERE is_active = 1"
            ) as cursor:
                stats['active_channels'] = (await cursor.fetchone())[0]

            return stats

    async def get_completed_users(self) -> List[Dict]:
        """Vazifani bajargan barcha foydalanuvchilarni olish"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("""
                    SELECT telegram_id, username, first_name, last_name, 
                           referral_count, completed_task, created_at
                    FROM users 
                    WHERE completed_task = 1
                    ORDER BY created_at DESC
                """) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]

    async def get_all_users(self) -> List[Dict]:
        """Barcha foydalanuvchilarni olish"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("""
                SELECT telegram_id, username, first_name, last_name, 
                       referral_count, completed_task, created_at
                FROM users 
                ORDER BY created_at DESC
            """) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]

    async def check_all_channels_joined_real(self, user_id: int) -> Dict:
        """Foydalanuvchining haqiqiy kanal holatini tekshirish"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row

            # Barcha aktiv kanallar
            async with db.execute(
                    "SELECT COUNT(*) as total FROM channels WHERE is_active = 1"
            ) as cursor:
                total_channels = (await cursor.fetchone())[0]

            # Haqiqatan qo'shilgan kanallar (joined = 1)
            async with db.execute("""
                SELECT COUNT(*) as joined FROM user_channels uc
                JOIN channels c ON uc.channel_id = c.id
                WHERE uc.user_id = ? AND c.is_active = 1 AND uc.joined = 1
            """, (user_id,)) as cursor:
                joined_channels = (await cursor.fetchone())[0]

            # Request yuborgan kanallar (request_sent = 1, joined = 0)
            async with db.execute("""
                SELECT COUNT(*) as pending FROM user_channels uc
                JOIN channels c ON uc.channel_id = c.id
                WHERE uc.user_id = ? AND c.is_active = 1 
                AND uc.request_sent = 1 AND uc.joined = 0
            """, (user_id,)) as cursor:
                pending_channels = (await cursor.fetchone())[0]

            return {
                'total': total_channels,
                'joined': joined_channels,
                'pending': pending_channels,
                'not_joined': total_channels - joined_channels - pending_channels,
                'all_joined': total_channels > 0 and joined_channels == total_channels
            }


# Singleton pattern uchun
db = Database()