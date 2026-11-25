"""
Cost guard (tiêu chí 8) — Theo dõi và giới hạn chi phí LLM trong Redis.
"""
from datetime import datetime, timezone

import redis
from fastapi import HTTPException

from app.config import settings
from app.redis_client import r

# Giá USD / 1K tokens (tham khảo gpt-4o-mini)
PRICE_INPUT_PER_1K = 0.00015
PRICE_OUTPUT_PER_1K = 0.0006

_fallback_costs: dict[str, float] = {}


def _budget_keys() -> tuple[str, str]:
    now = datetime.now(timezone.utc)
    return (
        f"cost:daily:{now.strftime('%Y-%m-%d')}",
        f"cost:monthly:{now.strftime('%Y-%m')}",
    )


def check_budget() -> None:
    """Gọi TRƯỚC khi gọi LLM. Hết budget → raise HTTPException(status_code=402)."""
    daily_key, monthly_key = _budget_keys()
    try:
        daily_spent = float(r.get(daily_key) or 0.0)
        monthly_spent = float(r.get(monthly_key) or 0.0)
    except redis.RedisError:
        daily_spent = _fallback_costs.get(daily_key, 0.0)
        monthly_spent = _fallback_costs.get(monthly_key, 0.0)

    if daily_spent >= settings.daily_budget_usd or monthly_spent >= settings.monthly_budget_usd:
        raise HTTPException(
            status_code=402,
            detail="Budget limit exceeded.",
        )


def record_cost(input_tokens: int, output_tokens: int) -> float:
    """Gọi SAU khi gọi LLM. Cộng chi phí của request vào tổng, trả về chi phí request."""
    cost = (
        (max(1, input_tokens) / 1000.0) * PRICE_INPUT_PER_1K
        + (max(1, output_tokens) / 1000.0) * PRICE_OUTPUT_PER_1K
    )
    daily_key, monthly_key = _budget_keys()
    try:
        pipe = r.pipeline()
        pipe.incrbyfloat(daily_key, cost)
        pipe.expire(daily_key, 90000)
        pipe.incrbyfloat(monthly_key, cost)
        pipe.expire(monthly_key, 32 * 86400)
        pipe.execute()
    except redis.RedisError:
        _fallback_costs[daily_key] = _fallback_costs.get(daily_key, 0.0) + cost
        _fallback_costs[monthly_key] = _fallback_costs.get(monthly_key, 0.0) + cost
    return cost
