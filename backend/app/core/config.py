import json
import os

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://scribe:scribe_local_pw@localhost:5433/scribe"
    jwt_secret: str = "dev-only-change-me"
    jwt_expire_hours: int = 8
    openai_api_key: str = ""
    environment: str = "local"


def _hydrate_from_secrets_manager() -> None:
    """生产环境：从 Secrets Manager 拉密钥并写入环境变量，
    供下面的 Settings() 读取。明文密钥只在内存里，仓库/磁盘都不存。
    只有设置了 MEDNOTE_SECRET_NAME 时才生效（本地开发不受影响）。"""
    name = os.getenv("MEDNOTE_SECRET_NAME")
    if not name:
        return
    import boto3  # 已在 requirements.txt

    region = os.getenv("AWS_REGION", "us-east-2")
    client = boto3.client("secretsmanager", region_name=region)
    payload = client.get_secret_value(SecretId=name)["SecretString"]
    for key, value in json.loads(payload).items():
        os.environ.setdefault(key, str(value))   # 已存在的环境变量优先（便于临时覆盖）


_hydrate_from_secrets_manager()
settings = Settings()