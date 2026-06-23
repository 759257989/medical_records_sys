#
# 全局限流器。key 函数决定"按谁限流"：登录后按用户 id，登录前(或无 token)按 IP。
import jwt
from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import settings


def user_or_ip_key(request: Request) -> str:
    """从 Authorization: Bearer <token> 里解出用户 id 作为限流键；失败则用客户端 IP。
    只做轻量解码用于"分桶"，真正的鉴权仍由各端点的 get_current_user 负责。"""
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        token = auth[7:]
        try:
            payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
            # 多租户：按 租户+用户 分桶 —— 一个诊所打爆自己的额度，不殃及别家(噪声邻居隔离)
            return f"tenant:{payload.get('tenant', '-')}:user:{payload['sub']}"
        except Exception:                           # 过期/篡改/格式错 → 退回按 IP
            pass
    return f"ip:{get_remote_address(request)}"


# storage_uri 留空 → 内存；配了 redis_url → 多实例共享计数(生产推荐)
limiter = Limiter(
    key_func=user_or_ip_key,
    storage_uri=settings.redis_url or "memory://",
    headers_enabled=True,        # 在响应头回 X-RateLimit-* ，前端/调用方能看到剩余额度
)
