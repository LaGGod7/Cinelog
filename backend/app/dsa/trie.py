"""Trie for title autocomplete (DSA engine).

Every node keeps its K best (popularity, film_id) pairs, so a prefix query is
O(L + K) where L is the prefix length - independent of catalogue size.
Titles are indexed from every word boundary ("the dark knight" is reachable by
"dark kn" too).
"""
from __future__ import annotations

import bisect
import re
from typing import Dict, List, Optional, Tuple

_norm_re = re.compile(r"[^a-z0-9 ]+")


def normalize(text: str) -> str:
    return " ".join(_norm_re.sub(" ", text.lower()).split())


class _Node:
    __slots__ = ("children", "top")

    def __init__(self) -> None:
        self.children: Dict[str, "_Node"] = {}
        # sorted ascending by (-popularity, film_id): best first
        self.top: List[Tuple[float, int]] = []


class Trie:
    def __init__(self, k: int = 10) -> None:
        self.k = k
        self.root = _Node()
        self.size = 0

    def _push(self, node: _Node, key: Tuple[float, int]) -> None:
        top = node.top
        i = bisect.bisect_left(top, key)
        if i < len(top) and top[i] == key:
            return
        if len(top) >= self.k and i >= self.k:
            return
        top.insert(i, key)
        if len(top) > self.k:
            top.pop()

    def _insert_string(self, s: str, key: Tuple[float, int]) -> None:
        node = self.root
        for ch in s:
            nxt = node.children.get(ch)
            if nxt is None:
                nxt = node.children[ch] = _Node()
            node = nxt
            self._push(node, key)

    def insert(self, title: str, film_id: int, popularity: float = 0.0) -> None:
        norm = normalize(title)
        if not norm:
            return
        key = (-float(popularity), film_id)
        words = norm.split(" ")
        for i in range(len(words)):
            self._insert_string(" ".join(words[i:]), key)
        self.size += 1

    def search(self, prefix: str, limit: Optional[int] = None) -> List[int]:
        p = normalize(prefix)
        node = self.root
        for ch in p:
            node = node.children.get(ch)
            if node is None:
                return []
        out: List[int] = []
        seen = set()
        for _, fid in node.top:
            if fid not in seen:
                seen.add(fid)
                out.append(fid)
        return out[: (limit or self.k)]
