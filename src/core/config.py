from pydantic_settings import BaseSettings
from dotenv import load_dotenv

load_dotenv()


class Settings(BaseSettings):
    BOT_TOKEN: str = ""
    DATABASE_URL: str = "sqlite+aiosqlite:///tratobot.db"
    
    POSTGRES_USER: str = ""
    POSTGRES_PASSWORD: str = ""
    POSTGRES_HOST: str = ""
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = ""
    
    USE_POSTGRES: bool = False
    
    @property
    def postgres_url(self) -> str:
        if self.USE_POSTGRES and self.POSTGRES_USER and self.POSTGRES_HOST:
            return f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        return self.DATABASE_URL
    
    @property
    def db_url(self) -> str:
        if self.USE_POSTGRES:
            return self.postgres_url
        return self.DATABASE_URL

    class Config:
        env_file = ".env"
        extra = "allow"


settings = Settings()