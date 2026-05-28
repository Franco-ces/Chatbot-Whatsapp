from collections import OrderedDict
from typing import Optional

from logging_config import get_logger

logger = get_logger("cache")


class LRUCache:
    """LRU cache for exact-match query responses.

    Thread-safe for asyncio (single event loop). Not safe for multi-threaded
    access without a lock.
    """

    def __init__(self, maxsize: int = 100):
        self._cache: OrderedDict[str, str] = OrderedDict()
        self._maxsize = maxsize

    def get(self, query: str) -> Optional[str]:
        """Return cached response for exact query, or None on miss."""
        key = query.strip().lower()
        if key in self._cache:
            self._cache.move_to_end(key)
            logger.debug("Cache hit", query=query[:50])
            return self._cache[key]
        logger.debug("Cache miss", query=query[:50])
        return None

    def set(self, query: str, response: str) -> None:
        """Store a query-response pair, evicting oldest if at capacity."""
        key = query.strip().lower()
        if key in self._cache:
            self._cache.move_to_end(key)
        elif len(self._cache) >= self._maxsize:
            self._cache.popitem(last=False)
        self._cache[key] = response

    def clear(self) -> None:
        """Flush the entire cache."""
        self._cache.clear()

    @property
    def size(self) -> int:
        return len(self._cache)
