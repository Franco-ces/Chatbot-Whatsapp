import pytest
from cache import LRUCache


class TestLRUCache:
    def test_miss_on_empty(self):
        cache = LRUCache()
        assert cache.get("hello") is None

    def test_hit_after_set(self):
        cache = LRUCache()
        cache.set("horario", "Lunes a viernes 9-18")
        assert cache.get("horario") == "Lunes a viernes 9-18"

    def test_case_insensitive(self):
        cache = LRUCache()
        cache.set("Horario", "Lunes a viernes 9-18")
        assert cache.get("HORARIO") == "Lunes a viernes 9-18"
        assert cache.get("horario") == "Lunes a viernes 9-18"

    def test_strips_whitespace(self):
        cache = LRUCache()
        cache.set("  horario  ", "respuesta")
        assert cache.get("horario") == "respuesta"

    def test_evicts_oldest(self):
        cache = LRUCache(maxsize=2)
        cache.set("a", "1")
        cache.set("b", "2")
        cache.set("c", "3")  # evicts "a"
        assert cache.get("a") is None
        assert cache.get("b") == "2"
        assert cache.get("c") == "3"

    def test_get_refreshes_order(self):
        cache = LRUCache(maxsize=2)
        cache.set("a", "1")
        cache.set("b", "2")
        cache.get("a")          # refreshes "a"
        cache.set("c", "3")     # should evict "b", not "a"
        assert cache.get("a") == "1"
        assert cache.get("b") is None

    def test_overwrite_same_key(self):
        cache = LRUCache()
        cache.set("q", "old")
        cache.set("q", "new")
        assert cache.get("q") == "new"
        assert cache.size == 1

    def test_clear(self):
        cache = LRUCache()
        cache.set("a", "1")
        cache.set("b", "2")
        cache.clear()
        assert cache.size == 0
        assert cache.get("a") is None

    def test_size_property(self):
        cache = LRUCache()
        assert cache.size == 0
        cache.set("a", "1")
        assert cache.size == 1
