from fastapi import Request
from redis.asyncio import Redis

from app.core.config import Settings


def create_redis_client(settings: Settings) -> Redis:
    return Redis.from_url(settings.redis_url, decode_responses=True)


def get_redis(request: Request) -> Redis:
    """FastAPI dependency returning the app-wide Redis client."""

    redis: Redis = request.app.state.redis
    return redis
