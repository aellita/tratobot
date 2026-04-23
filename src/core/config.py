import os
from pydantic_settings import BaseSettings

# Don't use load_dotenv - Railway provides env vars directly


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
        
        # Default to local SQLite
        return self.DATABASE_URL

    class Config:
        extra = "allow"


settings = Settings()