"""Aho-Corasick automaton (finite automaton) - find many terms in one pass."""
from __future__ import annotations

from collections import deque
from typing import Dict, Iterable, List, Tuple


class AhoCorasick:
    def __init__(self) -> None:
        self.goto: List[Dict[str, int]] = [{}]
        self.fail: List[int] = [0]
        self.out: List[List[int]] = [[]]  # indices into self.terms
        self.terms: List[str] = []
        self.payload: List[object] = []
        self._built = False

    def add(self, term: str, payload: object = None) -> None:
        term = term.lower().strip()
        if not term:
            return
        state = 0
        for ch in term:
            nxt = self.goto[state].get(ch)
            if nxt is None:
                self.goto.append({}); self.fail.append(0); self.out.append([])
                nxt = len(self.goto) - 1
                self.goto[state][ch] = nxt
            state = nxt
        self.terms.append(term)
        self.payload.append(payload)
        self.out[state].append(len(self.terms) - 1)
        self._built = False

    def build(self) -> "AhoCorasick":
        q: deque = deque()
        for s in self.goto[0].values():
            q.append(s)
        while q:
            r = q.popleft()
            for ch, s in self.goto[r].items():
                q.append(s)
                f = self.fail[r]
                while f and ch not in self.goto[f]:
                    f = self.fail[f]
                self.fail[s] = self.goto[f].get(ch, 0)
                self.out[s] = self.out[s] + self.out[self.fail[s]]
        self._built = True
        return self

    @staticmethod
    def _is_word_char(c: str) -> bool:
        return c.isalnum()

    def search(self, text: str, whole_words: bool = True) -> List[Tuple[int, int, str, object]]:
        """Return (start, end, term, payload) for every occurrence, in one pass."""
        if not self._built:
            self.build()
        low = text.lower()
        state = 0
        hits: List[Tuple[int, int, str, object]] = []
        for i, ch in enumerate(low):
            while state and ch not in self.goto[state]:
                state = self.fail[state]
            state = self.goto[state].get(ch, 0)
            for idx in self.out[state]:
                term = self.terms[idx]
                start = i - len(term) + 1
                end = i + 1
                if whole_words:
                    if start > 0 and self._is_word_char(low[start - 1]) and self._is_word_char(term[0]):
                        continue
                    if end < len(low) and self._is_word_char(low[end]) and self._is_word_char(term[-1]):
                        continue
                hits.append((start, end, term, self.payload[idx]))
        return hits

    @classmethod
    def from_terms(cls, items: Iterable[Tuple[str, object]]) -> "AhoCorasick":
        ac = cls()
        for term, payload in items:
            ac.add(term, payload)
        return ac.build()
