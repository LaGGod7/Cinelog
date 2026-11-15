"""Inverted index + top-K ranking with a min-heap (DSA engine)."""
from __future__ import annotations

import heapq
import math
import re
from collections import defaultdict
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

_tok = re.compile(r"[a-z0-9]+")
STOP = {"the", "a", "an", "of", "and", "in", "on", "to", "for", "is", "it", "with", "at", "by", "from"}


def tokenize(text: str) -> List[str]:
    return [t for t in _tok.findall(text.lower()) if t not in STOP]


class InvertedIndex:
    """term -> sorted list of film ids; documents carry a popularity prior."""

    def __init__(self) -> None:
        self.postings: Dict[str, List[int]] = defaultdict(list)
        self.tf: Dict[Tuple[str, int], int] = {}
        self.popularity: Dict[int, float] = {}
        self.meta: Dict[int, dict] = {}  # year, genres(set), cast(set)
        self.n_docs = 0
        self._sorted = True

    def add(self, film_id: int, fields: Dict[str, str], *, year: Optional[int], genres: Iterable[str],
            cast: Iterable[str], popularity: float = 0.0) -> None:
        weights = {"title": 3, "keywords": 2, "cast": 2, "genres": 2, "overview": 1}
        counts: Dict[str, int] = defaultdict(int)
        for name, text in fields.items():
            w = weights.get(name, 1)
            for t in tokenize(text or ""):
                counts[t] += w
        for t, c in counts.items():
            self.postings[t].append(film_id)
            self.tf[(t, film_id)] = c
        self.popularity[film_id] = popularity
        self.meta[film_id] = {
            "year": year,
            "genres": {g.lower() for g in genres},
            "cast": {c.lower() for c in cast},
        }
        self.n_docs += 1
        self._sorted = False

    def _ensure_sorted(self) -> None:
        if not self._sorted:
            for lst in self.postings.values():
                lst.sort()
            self._sorted = True

    @staticmethod
    def _intersect(a: Sequence[int], b: Sequence[int]) -> List[int]:
        i = j = 0
        out: List[int] = []
        while i < len(a) and j < len(b):
            if a[i] == b[j]:
                out.append(a[i]); i += 1; j += 1
            elif a[i] < b[j]:
                i += 1
            else:
                j += 1
        return out

    def matches(self, film_id: int, *, genre: Optional[str] = None, cast: Optional[str] = None,
                year: Optional[int] = None) -> bool:
        """Does this film pass the genre / cast / year filters? (same rules as search())"""
        m = self.meta.get(film_id)
        if m is None:
            return False
        if genre and genre.lower() not in m["genres"]:
            return False
        if year and m["year"] != year:
            return False
        if cast and not any(cast.lower() in name for name in m["cast"]):
            return False
        return True

    def search(self, query: str, *, genre: Optional[str] = None, cast: Optional[str] = None,
               year: Optional[int] = None, k: int = 10) -> List[int]:
        self._ensure_sorted()
        terms = tokenize(query)
        if terms:
            lists = sorted((self.postings.get(t, []) for t in terms), key=len)
            if not lists[0]:
                return []
            cand = lists[0]
            for lst in lists[1:]:
                cand = self._intersect(cand, lst)
                if not cand:
                    return []
        else:
            cand = sorted(self.meta.keys())
        g = genre.lower() if genre else None
        c = cast.lower() if cast else None
        heap: List[Tuple[float, int]] = []  # min-heap of size k keeps the best k
        for fid in cand:
            m = self.meta[fid]
            if g and g not in m["genres"]:
                continue
            if year and m["year"] != year:
                continue
            if c and not any(c in name for name in m["cast"]):
                continue
            score = sum(
                (1 + math.log(self.tf[(t, fid)])) * math.log(1 + self.n_docs / (1 + len(self.postings[t])))
                for t in terms
            ) + 0.05 * math.log1p(self.popularity.get(fid, 0.0))
            item = (score, -fid)
            if len(heap) < k:
                heapq.heappush(heap, item)
            elif item > heap[0]:
                heapq.heapreplace(heap, item)
        return [-neg for _, neg in sorted(heap, reverse=True)]


def top_k(items: Iterable[Tuple[float, int]], k: int) -> List[Tuple[float, int]]:
    """Generic min-heap top-K (used for feed merge / similarity)."""
    heap: List[Tuple[float, int]] = []
    for it in items:
        if len(heap) < k:
            heapq.heappush(heap, it)
        elif it > heap[0]:
            heapq.heapreplace(heap, it)
    return sorted(heap, reverse=True)
