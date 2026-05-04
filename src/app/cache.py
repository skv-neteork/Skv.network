"""Simple in-memory LRU cache with tiered TTL for SKV Reflex Engine."""
import time
from collections import OrderedDict
from typing import Optional, Any

class SimpleCache:
    def __init__(self, max_size: int = 1000):
        self.cache = OrderedDict()
        self.timestamps = {}
        self.ttls = {}
        self.max_size = max_size
        self.hits = 0
        self.misses = 0

    def get(self, key: str) -> Optional[Any]:
        if key not in self.cache:
            self.misses += 1
            return None
        ttl = self.ttls.get(key, 300)
        if ttl > 0 and time.time() - self.timestamps[key] > ttl:
            self.delete(key)
            self.misses += 1
            return None
        self.cache.move_to_end(key)
        self.hits += 1
        return self.cache[key]

    def set(self, key: str, value: Any, ttl: int = 300):
        if key in self.cache:
            self.cache.move_to_end(key)
        self.cache[key] = value
        self.timestamps[key] = time.time()
        self.ttls[key] = ttl
        while len(self.cache) > self.max_size:
            oldest = next(iter(self.cache))
            self.delete(oldest)

    def delete(self, key: str):
        self.cache.pop(key, None)
        self.timestamps.pop(key, None)
        self.ttls.pop(key, None)

    def invalidate_cube(self, cube_id: str):
        to_delete = [k for k in self.cache if cube_id in k]
        for k in to_delete:
            self.delete(k)

    def clear(self):
        """Очистить весь кэш."""
        self.cache.clear()
        self.timestamps.clear()
        self.ttls.clear()

    def get_stats(self) -> dict:
        total = self.hits + self.misses
        return {
            "size": len(self.cache),
            "hits": self.hits,
            "misses": self.misses,
            "hit_rate": round(self.hits / total * 100, 1) if total > 0 else 0
        }

cache = SimpleCache(max_size=1000)
