import os
from pydantic_settings import BaseSettings
from dotenv import load_dotenv

load_dotenv()


class Settings(BaseSettings):
    BOT_TOKEN: str = ""
    DATABASE_URL: str = "sqlite+aiosqlite:///tratobot.db"
    
    @property
    def db_url(self) -> str:
        # Use Railway's DATABASE_URL if available
        railway_db = os.getenv("DATABASE_URL")
        if railway_db:
            # Convert postgresql:// to postgresql+asyncpg://
            return railway_db.replace("postgresql://", "postgresql+asyncpg://")
        
        # Default to SQLite if no DATABASE_URL
        return self.DATABASE_URL

    class Config:
        env_file = ".env"
        extra = "allow"


settings = Settings()