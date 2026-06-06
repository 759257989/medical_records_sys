# app/core/security.py
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.core.config import settings


def hash_password(plain: str) -> str:
    """把明文密码哈希成可存库的字符串。"""
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """校验明文密码是否匹配库里的哈希。"""
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


def create_access_token(user) -> str:
    """为用户签发一个有时效的 JWT。"""
    expire = datetime.now(timezone.utc) + timedelta(hours=settings.jwt_expire_hours)
    payload = {
        "sub": str(user.id),   # subject = 用户 id
        "role": user.role,     # 角色，便于前端/中间件快速判断
        "exp": expire,         # 过期时间（PyJWT 会自动校验）
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")