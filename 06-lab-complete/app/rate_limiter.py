"""
Rate limiting (tiêu chí 7) — Sliding window 60 giây lưu trong Redis.
"""
import hashlib
import time
import uuid
from collections import defaultdict, deque

import redis
from fastapi import HTTPException

from app.config import settings
from app.redis_client import r

WINDOW_SECONDS = 60

_SLIDING_WINDOW_LUA = """
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', ARGV[1])
local count = redis.call('ZCARD', KEYS[1])
if count >= tonumber(ARGV[2]) then
    return 0
end
redis.call('ZADD', KEYS[1], ARGV[3], ARGV[4])
redis.call('EXPIRE', KEYS[1], tonumber(ARGV[5]))
return 1
"""

_fallback_windows: dict[str, deque[float]] = defaultdict(deque)


def check_rate_limit(key: str) -> None:
    """Kiểm tra giới hạn request/phút theo API key bằng Redis sorted set."""
    limit = settings.rate_limit_per_minute
    now = time.time()
    window_start = now - WINDOW_SECONDS
    key_hash = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
    redis_key = f"ratelimit:{key_hash}"
    member = f"{now:.6f}:{uuid.uuid4().hex[:8]}"

    try:
        allowed = int(
            r.eval(
                _SLIDING_WINDOW_LUA,
                1,
                redis_key,
                str(window_start),
                str(limit),
                str(now),
                member,
                str(WINDOW_SECONDS),
            )
        )
    except redis.RedisError:
        win = _fallback_windows[key_hash]
        while win and win[0] < window_start:
            win.popleft()
        if len(win) >= limit:
            allowed = 0
        else:
            win.append(now)
            allowed = 1

    if not allowed:
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded. Please retry later.",
            headers={"Retry-After": str(WINDOW_SECONDS)},
        )
