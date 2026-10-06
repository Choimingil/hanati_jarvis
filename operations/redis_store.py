from functools import lru_cache
import redis
from operations.settings import REDIS_URL


@lru_cache(maxsize=1)
def client():
    return redis.Redis.from_url(
        REDIS_URL, decode_responses=True, socket_timeout=5, socket_connect_timeout=3
    )
