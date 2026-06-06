# app/api/deps.py
#
# FastAPI "依赖注入"模块。
# 路由函数通过 Depends(xxx) 声明需要哪个依赖，FastAPI 在处理请求前自动调用并注入结果。
# 本文件提供两个认证/鉴权依赖，形成两级防线：
#   第一级 get_current_user  —— 验证身份（你是谁？）
#   第二级 require_admin     —— 验证权限（你能做什么？）

import uuid

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import get_db
from app.models.user import User

# OAuth2PasswordBearer 是一个"令牌提取器"：
# 它告诉 FastAPI 去请求头里找 "Authorization: Bearer <token>"，并把 token 字符串传给依赖它的函数。
# tokenUrl 仅供 /docs 页面的「Authorize」按钮知道去哪里登录，不影响实际验证逻辑。
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/auth/login")


async def get_current_user(
    token: str = Depends(oauth2_scheme),  # 从请求头自动提取 Bearer token
    db: AsyncSession = Depends(get_db),   # 注入数据库会话
) -> User:
    # 第一步：验证 token 签名和有效期
    # jwt.decode 会同时校验：签名是否被篡改、token 是否已过期
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="token_expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="invalid_token")

    # 第二步：用 token 里的用户 ID（sub 字段）查数据库，确认用户真实存在且未被停用
    # 每次请求都查一次，确保账号被管理员停用后旧 token 立即失效（不用等 token 自然过期）
    user = await db.get(User, uuid.UUID(payload["sub"]))
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="inactive_or_invalid")
    return user  # 返回的 User 对象会被注入到路由函数的参数中


def require_admin(user: User = Depends(get_current_user)) -> User:
    # 依赖链：require_admin 内部依赖 get_current_user，FastAPI 会先执行身份验证再执行权限检查
    # 只需在路由上声明 Depends(require_admin)，两步校验自动串联执行
    if user.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="admin_required")
    return user