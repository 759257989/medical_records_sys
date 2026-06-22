# app/core/security/__init__.py
#
# “模型边界安全”包：
#   auth   登录态 / 密码哈希 / JWT（原 security.py，对外 API 原样保留）
#   guard  输入/输出护栏（注入、越狱、提示泄露；对齐 OWASP LLM Top 10）
#   phi    PHI 脱敏（用于可观测性 trace）
#
# 这里把 auth 的函数重新导出，让历史调用点
# `from app.core.security import hash_password` 等保持不变。
from app.core.security.auth import (
    create_access_token,
    hash_password,
    verify_password,
)

__all__ = ["create_access_token", "hash_password", "verify_password"]
