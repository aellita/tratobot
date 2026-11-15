import logging

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
    )

    BOT_TOKEN: str = ""
    DATABASE_URL: str = "sqlite+aiosqlite:///tratobot.db"
    ADMIN_CHAT_ID: int | None = None
    EXPENSE_SIMPLE_CHECK: bool = True
    RECOVERY_ENABLED: bool = True

    RECOVERY_TRIGGER: float = 0.85
    RECOVERY_FAST: float = 0.60
    RECOVERY_BALANCED: float = 0.70
    RECOVERY_SOFT: float = 0.80
    RECOVERY_SUCCESS: float = 0.90
    RECOVERY_REPLAN_THRESHOLD: float = 0.90
    RECOVERY_SMALL_OVERSPEND: float = 1.10
    RECOVERY_MIN_TAIL_DAYS: int = 7
    RECOVERY_COOLDOWN_DAYS: int = 3
    RECOVERY_MIN_BASE_LIMIT: float = 1000.0
    RECOVERY_REPEAT_DEFICIT_MULT: float = 0.50

    @field_validator("ADMIN_CHAT_ID", mode="before")
    @classmethod
    def _empty_admin_chat_id_is_none(cls, value):
        if value is None or (isinstance(value, str) and not value.strip()):
            return None
        return value

    @property
    def db_url(self) -> str:
        if self.DATABASE_URL.startswith("postgresql://"):
            logger.info("Using PostgreSQL DATABASE_URL")
            return self.DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)

        logger.info("Using SQLite DATABASE_URL")
        return self.DATABASE_URL


settings = Settings()
