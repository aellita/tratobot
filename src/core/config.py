import os
import logging
from pydantic_settings import BaseSettings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    BOT_TOKEN: str = ""
    DATABASE_URL: str = "sqlite+aiosqlite:///tratobot.db"
    
    @property
    def db_url(self) -> str:
        # Use Railway's DATABASE_URL if available
        railway_db = os.getenv("DATABASE_URL")
        
        if railway_db:
            # Convert postgresql:// to postgresql+asyncpg:// for async
            db_url = railway_db.replace("postgresql://", "postgresql+asyncpg://")
            logger.info(f"Using Railway DATABASE_URL")
            return db_url
        
        # Default to local SQLite for local dev
        logger.info("Using default SQLite")
        return self.DATABASE_URL

    class Config:
        extra = "allow"


settings = Settings()