"""Basic connection example.

Loads credentials from a local .env file (see .env.example) and pings the
Redis database to confirm connectivity.
"""

import os

import redis
from dotenv import load_dotenv

# Load variables from the .env file sitting next to this script.
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

REDIS_HOST = os.getenv("REDIS_HOST")
REDIS_PORT = os.getenv("REDIS_PORT")
REDIS_USERNAME = os.getenv("REDIS_USERNAME")
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD")

# Fail fast instead of hanging if the host is unreachable.
TIMEOUTS = dict(socket_connect_timeout=10, socket_timeout=10)

r = redis.Redis(
    host=REDIS_HOST,
    port=REDIS_PORT,
    decode_responses=True,
    username=REDIS_USERNAME,
    password=REDIS_PASSWORD,
)

success = r.set('foo', 'bar')
# True

result = r.get('foo')
print(result)
# >>> bar
