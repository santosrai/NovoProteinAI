"""Shared Redis connection.

Loads credentials from the local .env file (see .env.example) and exposes a
single configured client plus a small helper for the connection URL that
RedisVL expects.
"""

import os

import redis
from dotenv import load_dotenv

# Load variables from the .env file sitting next to this script.
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

REDIS_HOST = os.getenv("REDIS_HOST")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_USERNAME = os.getenv("REDIS_USERNAME", "default")
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD")

# Fail fast instead of hanging if the host is unreachable.
TIMEOUTS = dict(socket_connect_timeout=10, socket_timeout=10)


def get_client(decode_responses: bool = True) -> redis.Redis:
    """Return a configured redis-py client."""
    return redis.Redis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        username=REDIS_USERNAME,
        password=REDIS_PASSWORD,
        decode_responses=decode_responses,
        **TIMEOUTS,
    )


def get_redis_url() -> str:
    """Build the redis:// URL RedisVL's SearchIndex.from_dict(...) accepts."""
    auth = ""
    if REDIS_USERNAME or REDIS_PASSWORD:
        auth = f"{REDIS_USERNAME or ''}:{REDIS_PASSWORD or ''}@"
    return f"redis://{auth}{REDIS_HOST}:{REDIS_PORT}"


if __name__ == "__main__":
    client = get_client()
    print("PING:", client.ping())
