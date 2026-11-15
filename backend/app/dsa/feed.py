"""K-way merge of followed users' activity (min-heap) and taste similarity."""
from __future__ import annotations

import heapq
import math
from typing import Dict, List, Sequence, Tuple


def merge_feeds(feeds: Sequence[Sequence[dict]], limit: int = 20) -> List[dict]:
    """Each feed is sorted newest-first by item['at']; return newest `limit` overall."""
    heap: List[Tuple[float, int, int]] = []  # (-timestamp, feed idx, position)
    for i, f in enumerate(feeds):
        if f:
            heapq.heappush(heap, (-f[0]["at"], i, 0))
    out: List[dict] = []
    while heap and len(out) < limit:
        _, i, j = heapq.heappop(heap)
        out.append(feeds[i][j])
        if j + 1 < len(feeds[i]):
            heapq.heappush(heap, (-feeds[i][j + 1]["at"], i, j + 1))
    return out


def cosine(a: Dict[int, float], b: Dict[int, float]) -> Tuple[float, int]:
    """Cosine similarity over co-rated films; returns (similarity, #common films)."""
    common = set(a) & set(b)
    if not common:
        return 0.0, 0
    dot = sum(a[k] * b[k] for k in common)
    na = math.sqrt(sum(a[k] ** 2 for k in common))
    nb = math.sqrt(sum(b[k] ** 2 for k in common))
    return (dot / (na * nb) if na and nb else 0.0), len(common)
