import json
import os

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://scribe:scribe_local_pw@localhost:5433/scribe"
    jwt_secret: str = "dev-only-change-me"
    jwt_expire_hours: int = 8
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    environment: str = "local"
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "http://localhost:3000"   # Cloud 则填 https://cloud.langfuse.com
    prompt_version: str = "soap_v1"                # prompt 版本标签（为 Phase 3/4 治理埋点）
    # 限流存储：留空 → 用进程内内存(单实例够用)；填 redis://host:port/db → 多实例共享
    redis_url: str = ""
    # 各接口的限流额度(可按需调)
    rate_limit_generate: str = "10/minute"   # SOAP 生成：贵，收紧 每 1 分钟 最多 10 次
    rate_limit_agent: str = "5/minute"       # agent 运行：更贵
    rate_limit_icd: str = "60/minute"        # ICD 检索：便宜，放宽
    rate_limit_login: str = "5/minute"       # 登录：按 IP，防爆破
    
    phi_scrub_logs: bool = True       # 写 trace/日志前是否擦 PHI(强烈建议 True)
    phi_strict_mode: bool = False     # 是否"发给模型前去标识"(默认 False，保留姓名进 prompt)

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