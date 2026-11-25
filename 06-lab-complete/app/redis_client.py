"""
Kết nối Redis dùng chung cho rate limiter và cost guard.

App vẫn khởi động được khi Redis chưa sẵn sàng (lazy connection, không ping lúc import).
"""
import redis

from app.config import settings

r = redis.from_url(
    settings.redis_url or "redis://localhost:6379/0",
    decode_responses=True,
    socket_connect_timeout=1.5,
    socket_timeout=1.5,
)


def redis_healthy() -> bool:
    """Kiểm tra kết nối Redis cho GET /ready."""
    if not settings.redis_url:
        return False
    try:
        return bool(r.ping())
    except Exception:
        return False
