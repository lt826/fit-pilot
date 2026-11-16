"""认证与限流（设计为可复用组件：FitPilot 等项目直接拷走即用）。

- JWT：HS256，登录换 token，过期 401。无用户体系，单管理员口令制（demo 场景）
- 限流：进程内滑动窗口，按 key（token 用户 / IP）计数，超限 429 + Retry-After
  多 worker 部署时换 Redis 计数器即可（接口不变，注释在类上）
"""

import time
from collections import defaultdict, deque

import jwt
from fastapi import HTTPException, Request

from app.core.config import get_settings

ALG = "HS256"


def create_token(username: str) -> str:
    """登录成功后签发 JWT（HS256 签名）。

    payload 三件：sub=用户名、iat=签发时间、exp=过期时间（默认 24h 后）。
    "过期"不是定时任务，而是 verify_token 每次验签时对照 exp 当场判定——
    服务端不存任何 token，只存签名密钥（无状态认证）。
    """
    s = get_settings()
    now = int(time.time())
    payload = {"sub": username, "iat": now,
               "exp": now + s.jwt_expire_hours * 3600}
    return jwt.encode(payload, s.jwt_secret, algorithm=ALG)


def verify_token(request: Request) -> str:
    """FastAPI 依赖：验 Authorization: Bearer <token>，通过返回用户名。

    三种死法都归 401：没带 Bearer 头、签名对不上（伪造）、exp 已过
    （ExpiredSignatureError 单独提示"登录已过期"，前端据此弹回登录页）。
    """
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="未登录")
    try:
        payload = jwt.decode(auth[7:], get_settings().jwt_secret, algorithms=[ALG])
        return payload["sub"]
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="登录已过期，请重新登录")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="无效凭证")


class RateLimiter:
    """滑动窗口限流器（进程内版；多 worker 换 Redis ZSET，方法签名不变）。

    limit(key, max_n, window_s) -> None 或抛 429。
    """

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def limit(self, key: str, max_n: int, window_s: int = 60) -> None:
        """滑动窗口限流：window_s 秒内第 max_n+1 次请求抛 429。

        实现：每个 key 一个 deque 存请求时间戳；来新请求先弹掉窗口外
        的旧戳，剩的数量超限即拒绝（429 + Retry-After 告知等待秒数）。
        key 粒度即隔离粒度："login"全局计数防爆破，"ask:用户名"按人隔离防烧配额。
        """
        now = time.monotonic()
        q = self._hits[key]
        while q and q[0] <= now - window_s:
            q.popleft()
        if len(q) >= max_n:
            retry = int(q[0] + window_s - now) + 1
            raise HTTPException(
                status_code=429,
                detail=f"请求过于频繁（{window_s}s 内限 {max_n} 次），{retry}s 后重试",
                headers={"Retry-After": str(retry)},
            )
        q.append(now)


limiter = RateLimiter()
