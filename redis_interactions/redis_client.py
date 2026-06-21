"""Shared Redis connection.

Loads credentials from the local .env file (see .env.example) and exposes a
single configured client plus a small helper for the connection URL that
RedisVL expects.
"""

import os
from urllib.parse import quote

import redis
from dotenv import load_dotenv

# Load variables from the .env file sitting next to this script.
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

REDIS_HOST = os.getenv("REDIS_HOST")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_USERNAME = os.getenv("REDIS_USERNAME", "default")
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD")
# Managed Redis (e.g. Redis Cloud) usually requires TLS. Set REDIS_TLS=true to
# connect over rediss:// and enable SSL on the redis-py client.
REDIS_TLS = os.getenv("REDIS_TLS", "false").lower() in ("1", "true", "yes")

# Fail fast instead of hanging if the host is unreachable.
TIMEOUTS = dict(socket_connect_timeout=10, socket_timeout=10)


def _require_host() -> str:
    if not REDIS_HOST:
        raise RuntimeError(
            "REDIS_HOST is not set. Copy .env.example to .env and fill in your "
            "Redis credentials."
        )
    return REDIS_HOST


def get_client(decode_responses: bool = True) -> redis.Redis:
    """Return a configured redis-py client."""
    return redis.Redis(
        host=_require_host(),
        port=REDIS_PORT,
        username=REDIS_USERNAME,
        password=REDIS_PASSWORD,
        decode_responses=decode_responses,
        ssl=REDIS_TLS,
        **TIMEOUTS,
    )


def get_redis_url() -> str:
    """Build the redis(s):// URL RedisVL's SearchIndex.from_dict(...) accepts.

    Credentials are percent-encoded so passwords containing characters like
    '@', ':' or '/' don't corrupt the URL.
    """
    host = _require_host()
    scheme = "rediss" if REDIS_TLS else "redis"
    auth = ""
    if REDIS_USERNAME or REDIS_PASSWORD:
        user = quote(REDIS_USERNAME or "", safe="")
        password = quote(REDIS_PASSWORD or "", safe="")
        auth = f"{user}:{password}@"
    return f"{scheme}://{auth}{host}:{REDIS_PORT}"


if __name__ == "__main__":
    client = get_client()
    print("PING:", client.ping())
