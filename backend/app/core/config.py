# app/core/config.py
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # 从 backend/.env 读取；环境变量名大小写不敏感（database_url ⇄ DATABASE_URL）
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # 运行时用 asyncpg 驱动连接（异步）
    database_url: str = "postgresql+asyncpg://scribe:scribe_local_pw@localhost:5433/scribe"

    jwt_secret: str = "dev-only-change-me"   # 上线务必换成长随机串
    jwt_expire_hours: int = 8

    openai_api_key: str = ""                 # 从 .env 读取，不要在此处填写真实 Key
    environment: str = "local"               # local / aws


settings = Settings()