"""Local Mirror — in-process LRU cache for Light Resonance (<100ms)."""
from collections import OrderedDict
import time
import hashlib

class LocalMirror:
    def __init__(self, max_size=100, ttl=300):
        self.cache = OrderedDict()
        self.max_size = max_size
        self.ttl = ttl
    
    def get(self, key: str):
        if key not in self.cache:
            return None
        value, timestamp = self.cache[key]
        if time.time() - timestamp > self.ttl:
            del self.cache[key]
            return None
        self.cache.move_to_end(key)
        return value
    
    def put(self, key: str, value):
        if key in self.cache:
            del self.cache[key]
        elif len(self.cache) >= self.max_size:
            self.cache.popitem(last=False)
        self.cache[key] = (value, time.time())
    
    def _hash(self, text: str) -> str:
        return hashlib.sha256(text.encode()).hexdigest()[:16]

# Глобальный экземпляр
mirror = LocalMirror(max_size=100, ttl=300)
