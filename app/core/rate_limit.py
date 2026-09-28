from slowapi import Limiter
from slowapi.util import get_remote_address

# In-memory buckets (per-process). No Redis required — sufficient for
# brute-force protection on auth endpoints at this scale. Move to
# redis://localhost:6379 storage when running multiple API replicas.
limiter = Limiter(
    key_func=get_remote_address,
    storage_uri="memory://",
    default_limits=["200/minute"],
)
