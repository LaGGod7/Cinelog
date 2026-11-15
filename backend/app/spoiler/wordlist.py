"""Per-film spoiler word lists + cached Aho-Corasick automata."""
from __future__ import annotations

import re
from typing import Iterable, List, Sequence, Tuple

from ..dsa.aho_corasick import AhoCorasick
from ..dsa.lru import LRUCache
from .text import COMMON, STOP

TermT = Tuple[str, str]  # (term, kind) kind in {"name", "plot"}


def usable(term: str) -> bool:
    t = term.lower().strip()
    return len(t) >= 3 and t not in STOP and t not in COMMON and not t.isdigit()


def terms_from_cast(characters: Iterable[str]) -> List[TermT]:
    """Character names become weak ('name') terms: a name alone is not a spoiler."""
    out: dict[str, str] = {}
    for ch in characters:
        ch = re.sub(r"\(.*?\)|/.*|\bvoice\b|\buncredited\b", "", ch or "", flags=re.I).strip()
        if not ch:
            continue
        if usable(ch) and " " in ch.strip():
            out[ch.lower()] = "name"
        for part in re.split(r"[\s\-]+", ch):
            if usable(part) and len(part) >= 4:
                out[part.lower()] = "name"
    return list(out.items())


def terms_from_actors(actors: Iterable[str]) -> List[TermT]:
    """Actor names are weak terms too: people write "is Ruffalo hallucinating?" without ever naming the character.
    Full name plus surname only - first names ("Mark", "Will") collide with ordinary words."""
    out: dict[str, str] = {}
    for a in actors:
        a = re.sub(r"\(.*?\)", "", a or "").strip()
        parts = [p for p in re.split(r"\s+", a) if p]
        if len(parts) >= 2 and usable(a):
            out[a.lower()] = "name"
        if parts and usable(parts[-1]) and len(parts[-1]) >= 5:
            out[parts[-1].lower().strip(".,")] = "name"
    return list(out.items())


class AutomatonCache:
    def __init__(self, capacity: int = 128) -> None:
        self.cache: LRUCache = LRUCache(capacity)

    def get(self, film_id: int, version: int, terms: Sequence[TermT]) -> AhoCorasick:
        key = (film_id, version)
        ac = self.cache.get(key)
        if ac is None:
            ac = AhoCorasick.from_terms((t, k) for t, k in terms if usable(t))
            self.cache.put(key, ac)
        return ac
