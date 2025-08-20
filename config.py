import os
from dataclasses import dataclass, field
from typing import List
from dotenv import load_dotenv

load_dotenv()

@dataclass
class Settings:
    BOT_TOKEN: str = os.getenv("BOT_TOKEN")
    DATABASE_PATH: str = os.getenv("DATABASE_PATH", "bot_database.db")
    ADMIN_IDS: List[int] = field(default_factory=lambda: list(map(int, filter(None, os.getenv("ADMIN_IDS", "").split(",")))))
    REQUIRED_REFERRALS: int = int(os.getenv("REQUIRED_REFERRALS", "6"))

settings = Settings()