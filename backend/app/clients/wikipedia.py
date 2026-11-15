"""Fetch a film's plot section from Wikipedia (CC BY-SA) to use as RAG context for new films."""
from __future__ import annotations

import re
from typing import List, Optional

import httpx

API = "https://en.wikipedia.org/w/api.php"
HEAD = re.compile(r"^==\s*([^=].*?)\s*==\s*$", re.M)


def extract_plot(wikitext_extract: str) -> str:
    """Take the 'Plot'/'Synopsis' section out of an `exsectionformat=wiki` extract."""
    heads = list(HEAD.finditer(wikitext_extract))
    for i, h in enumerate(heads):
        if h.group(1).strip().lower() in ("plot", "synopsis", "premise", "story", "plot summary"):
            end = heads[i + 1].start() if i + 1 < len(heads) else len(wikitext_extract)
            body = wikitext_extract[h.end():end]
            body = re.sub(r"^=+.*?=+\s*$", "", body, flags=re.M)  # drop sub-headings
            return " ".join(body.split())
    return ""


class WikipediaClient:
    def __init__(self, client: Optional[httpx.Client] = None) -> None:
        self.http = client or httpx.Client(timeout=15, headers={"User-Agent": "CineLog/1.0 (student project)"})

    def _extract(self, title: str) -> str:
        r = self.http.get(API, params={"action": "query", "prop": "extracts", "explaintext": 1,
                                       "exsectionformat": "wiki", "redirects": 1, "titles": title, "format": "json"})
        if r.status_code != 200:
            return ""
        pages = r.json().get("query", {}).get("pages", {})
        for p in pages.values():
            if "missing" in p:
                continue
            return p.get("extract", "") or ""
        return ""

    def plot_for(self, title: str, year: Optional[int]) -> str:
        cands: List[str] = []
        if year:
            cands.append(f"{title} ({year} film)")
        cands += [f"{title} (film)", title]
        for c in cands:
            plot = extract_plot(self._extract(c))
            if len(plot) > 200:
                return plot
        return ""
