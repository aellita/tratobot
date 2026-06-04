import logging

from pydantic_settings import BaseSettings, SettingsConfigDict

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )

    BOT_TOKEN: str = ""
    DATABASE_URL: str = "sqlite+aiosqlite:///tratobot.db"

    @property
    def db_url(self) -> str:
        if self.DATABASE_URL.startswith("postgresql://"):
            logger.info("Using PostgreSQL DATABASE_URL")
            return self.DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)

        logger.info("Using SQLite DATABASE_URL")
        return self.DATABASE_URL


settings = Settings()
