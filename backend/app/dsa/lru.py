"""LRU cache = hash map + doubly linked list (OS/DSA engine)."""
from __future__ import annotations

import threading
from typing import Dict, Generic, Hashable, Optional, TypeVar

K = TypeVar("K", bound=Hashable)
V = TypeVar("V")


class _N:
    __slots__ = ("k", "v", "prev", "next")

    def __init__(self, k=None, v=None):
        self.k, self.v, self.prev, self.next = k, v, None, None


class LRUCache(Generic[K, V]):
    def __init__(self, capacity: int = 256) -> None:
        assert capacity > 0
        self.capacity = capacity
        self.map: Dict[K, _N] = {}
        self.head, self.tail = _N(), _N()  # sentinels
        self.head.next, self.tail.prev = self.tail, self.head
        self.lock = threading.Lock()
        self.hits = self.misses = self.evictions = 0

    def _unlink(self, n: _N) -> None:
        n.prev.next, n.next.prev = n.next, n.prev

    def _push_front(self, n: _N) -> None:
        n.next, n.prev = self.head.next, self.head
        self.head.next.prev = n
        self.head.next = n

    def get(self, key: K) -> Optional[V]:
        with self.lock:
            n = self.map.get(key)
            if n is None:
                self.misses += 1
                return None
            self.hits += 1
            self._unlink(n); self._push_front(n)
            return n.v

    def put(self, key: K, value: V) -> None:
        with self.lock:
            n = self.map.get(key)
            if n:
                n.v = value
                self._unlink(n); self._push_front(n)
                return
            if len(self.map) >= self.capacity:
                lru = self.tail.prev
                self._unlink(lru)
                del self.map[lru.k]
                self.evictions += 1
            n = _N(key, value)
            self.map[key] = n
            self._push_front(n)

    def pop(self, key: K) -> None:
        with self.lock:
            n = self.map.pop(key, None)
            if n:
                self._unlink(n)

    def stats(self) -> Dict[str, float]:
        """Counters for the soak test and /health: a rising eviction rate with a falling hit rate means thrashing."""
        with self.lock:
            total = self.hits + self.misses
            return {"size": len(self.map), "capacity": self.capacity, "hits": self.hits, "misses": self.misses,
                    "evictions": self.evictions, "hit_rate": round(self.hits / total, 4) if total else 0.0}

    def __len__(self) -> int:
        return len(self.map)

    def keys_mru_first(self):
        out, n = [], self.head.next
        while n is not self.tail:
            out.append(n.k); n = n.next
        return out
