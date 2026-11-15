"""TMDB client: token-bucket rate limit, LRU cache, back-off on HTTP 429 (CN engine owns outside services)."""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

import httpx

from ..dsa.lru import LRUCache
from ..security import TokenBucket

log = logging.getLogger("cinelog.tmdb")
BASE = "https://api.themoviedb.org/3"


class TMDBError(Exception):
    pass


class TMDBClient:
    def __init__(self, api_key: str, rate: float = 30.0, client: Optional[httpx.Client] = None,
                 sleep=time.sleep, cache_size: int = 512) -> None:
        self.api_key = api_key
        self.http = client or httpx.Client(timeout=httpx.Timeout(15.0, connect=5.0))
        self.bucket = TokenBucket(capacity=max(rate, 1), refill_per_sec=rate)
        self.cache: LRUCache = LRUCache(cache_size)
        self.sleep = sleep
        self.calls = 0

    def _get(self, path: str, _attempts: int = 5, **params: Any) -> Dict[str, Any]:
        """_attempts=1 is for a person waiting on a page: one try, no back-off sleeping."""
        key = (path, tuple(sorted(params.items())))
        hit = self.cache.get(key)
        if hit is not None:
            return hit
        delay = 1.0
        for _attempt in range(_attempts):
            while not self.bucket.allow("tmdb"):
                self.sleep(0.02)
            self.calls += 1
            r = self.http.get(BASE + path, params={"api_key": self.api_key, **params})
            last = _attempt == _attempts - 1
            if r.status_code == 429 and not last:
                wait = float(r.headers.get("Retry-After", delay))
                log.warning("TMDB 429, backing off %.1fs", wait)
                self.sleep(wait)
                delay *= 2
                continue
            if r.status_code in (429, 500, 502, 503, 504) and last:
                break
            if r.status_code >= 500:
                self.sleep(delay); delay *= 2
                continue
            if r.status_code != 200:
                raise TMDBError(f"{path}: HTTP {r.status_code}")
            data = r.json()
            self.cache.put(key, data)
            return data
        raise TMDBError(f"{path}: gave up after retries")

    def popular(self, page: int = 1) -> List[Dict[str, Any]]:
        return self._get("/movie/popular", page=page).get("results", [])

    def now_playing(self, page: int = 1) -> List[Dict[str, Any]]:
        return self._get("/movie/now_playing", page=page).get("results", [])

    def upcoming(self, page: int = 1) -> List[Dict[str, Any]]:
        return self._get("/movie/upcoming", page=page).get("results", [])

    def search(self, query: str, page: int = 1, attempts: int = 5) -> List[Dict[str, Any]]:
        return self._get("/search/movie", _attempts=attempts, query=query, page=page).get("results", [])

    def details(self, tmdb_id: int, attempts: int = 5) -> Dict[str, Any]:
        return self._get(f"/movie/{tmdb_id}", _attempts=attempts, append_to_response="credits,keywords")

    def find_imdb(self, imdb_id: str) -> Optional[Dict[str, Any]]:
        res = self._get(f"/find/{imdb_id}", external_source="imdb_id").get("movie_results", [])
        return res[0] if res else None
