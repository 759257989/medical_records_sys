# app/api/auth.py
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.db import get_db
from app.core.security import create_access_token, verify_password
from app.models.user import User
from app.schemas.auth import LoginRequest, TokenResponse, UserOut

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    user = await db.scalar(select(User).where(User.email == body.email.lower()))
    # 注意：用户不存在和密码错误返回同样的错误，避免“撞库”探测出哪些邮箱存在
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="invalid_credentials")
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="account_inactive")

    token = create_access_token(user)
    return TokenResponse(access_token=token, user=UserOut.model_validate(user))

# 前端刷新页面后调它「我还登着吗？是谁？」——既恢复登录态又顺带验证 token 有效
@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)):
    """前端用它在刷新后恢复登录态，并验证 token 是否还有效。"""
    return UserOut.model_validate(user)