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
from app.models.encounter import Encounter
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

async def get_owned_encounter(
    encounter_id: uuid.UUID,                       # 来自 URL 路径 /encounters/{encounter_id}/...
    user: User = Depends(get_current_user),        # 先认证（复用第一级防线）
    db: AsyncSession = Depends(get_db),
) -> Encounter:
    """取出指定 encounter，并强制"归属校验"：
    - provider 只能访问自己的 encounter；
    - admin 可以访问任何人的（为 Phase 4 全局视图铺路）。
    校验在后端完成，不依赖前端隐藏，满足 AUTH-3。
    """
    enc = await db.get(Encounter, encounter_id)
    if enc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="encounter_not_found")
    if user.role != "admin" and enc.provider_id != user.id:
        # 注意：越权返回 403。也可返回 404 以不暴露资源是否存在，这里用 403 更直观。
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="forbidden")
    return enc