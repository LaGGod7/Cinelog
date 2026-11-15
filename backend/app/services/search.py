"""In-memory search engine over the catalogue (Trie + inverted index), rebuilt after catalogue changes."""
from __future__ import annotations

import threading
from typing import List, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..dsa.inverted_index import InvertedIndex
from ..dsa.trie import Trie
from ..models import Film


class SearchService:
    def __init__(self) -> None:
        self.trie, self.index = Trie(10), InvertedIndex()
        self._lock = threading.RLock()
        self.size = 0
        self._sig: tuple = ()

    @staticmethod
    def signature(db: Session) -> tuple:
        """Cheap fingerprint of the catalogue: changes when a film is added or re-synced by any process."""
        n, last, top = db.execute(select(func.count(Film.id), func.max(Film.synced_at), func.max(Film.id))).one()
        return (n, str(last), top)

    def refresh_if_changed(self, db: Session) -> bool:
        """Scripts (import_kaggle, seed_demo) write to the database from another process; pick their films up."""
        if self.signature(db) == self._sig:
            return False
        self.rebuild(db)
        return True

    def rebuild(self, db: Session) -> int:
        sig = self.signature(db)
        trie, index = Trie(10), InvertedIndex()
        n = 0
        for f in db.scalars(select(Film)):
            self._add(trie, index, f)
            n += 1
        with self._lock:
            self.trie, self.index, self.size, self._sig = trie, index, n, sig
        return n

    @staticmethod
    def _add(trie: Trie, index: InvertedIndex, f: Film) -> None:
        trie.insert(f.title, f.id, f.popularity)
        index.add(f.id, {"title": f.title, "overview": f.overview,
                         "keywords": " ".join(k.keyword for k in f.keywords),
                         "cast": " ".join(c.actor for c in f.cast),
                         "genres": " ".join(g.genre for g in f.genres)},
                  year=f.year, genres=[g.genre for g in f.genres], cast=[c.actor for c in f.cast],
                  popularity=f.popularity)

    def add_film(self, f: Film) -> None:
        with self._lock:
            self._add(self.trie, self.index, f)
            self.size += 1

    def autocomplete(self, prefix: str) -> List[int]:
        if len(prefix.strip()) < 2:
            return []
        with self._lock:
            return self.trie.search(prefix, 10)

    def search(self, q: str, genre: Optional[str], cast: Optional[str], year: Optional[int], k: int = 10) -> List[int]:
        with self._lock:
            ids = self.index.search(q, genre=genre, cast=cast, year=year, k=k)
            # The index matches whole words, so a half-typed title ("godf", "incep") found nothing while the person was
            # still typing. Fill the remaining places with title-prefix matches from the trie (same filters apply).
            if len(ids) < k and len(q.strip()) >= 2:
                for fid in self.trie.search(q, k):
                    if len(ids) >= k:
                        break
                    if fid not in ids and self.index.matches(fid, genre=genre, cast=cast, year=year):
                        ids.append(fid)
            return ids
