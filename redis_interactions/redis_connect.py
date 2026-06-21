"""Basic connection example.

Confirms connectivity to the Redis database using the shared, configured client
from redis_client.py (which loads credentials from the local .env file).
"""

from redis_client import get_client

r = get_client()

success = r.set("foo", "bar")
# True

result = r.get("foo")
print(result)
# >>> bar
