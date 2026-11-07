from collections import OrderedDict
from threading import Lock
from time import monotonic

from fastapi import HTTPException


class RateLimiter:
    """Per-process fixed windows, bounded memory. Shared limiter required for multiple workers."""
    def __init__(self):
        self.entries = OrderedDict()
        self.lock = Lock()

    def check(self, key: str, limit: int):
        now = monotonic()
        with self.lock:
            while self.entries and next(iter(self.entries.values()))[0] + 60 <= now:
                self.entries.popitem(last=False)
            start, count = self.entries.get(key, (now, 0))
            if count >= limit:
                raise HTTPException(429, "요청이 너무 많습니다. 잠시 후 다시 시도해 주세요.",
                                    headers={"Retry-After": str(max(1, int(60 - (now - start))))})
            if key not in self.entries and len(self.entries) >= 10_000:
                raise HTTPException(429, "서버가 혼잡합니다. 잠시 후 다시 시도해 주세요.", headers={"Retry-After": "60"})
            self.entries[key] = (start, count + 1)


limiter = RateLimiter()
