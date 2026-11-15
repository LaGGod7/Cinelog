"""Text helpers: sentence splitting with offsets, writer spoiler tags, stop words."""
from __future__ import annotations

import re
from typing import List, Tuple

# a sentence ends at . ! ? then spaces - or, as people often type it, directly before a capital letter ("outside.The idiot")
SENT_RE = re.compile(r"(?<=[.!?])[\"')\]]*\s+|\n+|(?<=[a-z]{3}[.!?])(?=[A-Z][a-z])|(?<=[a-z]{3}[.!?][\"')\]])(?=[A-Z][a-z])")
ABBR = {"mr.", "mrs.", "ms.", "dr.", "st.", "vs.", "etc.", "e.g.", "i.e.", "u.s.", "no.", "jr.", "sr."}
TAG_RE = re.compile(r"\|\|(.+?)\|\|", re.S)

STOP = set("""a about above after again all also am an and any are as at be because been before being below between both but
by can could did do does doing down during each few for from further had has have having he her here hers herself him
himself his how i if in into is it its itself just me more most my myself no nor not now of off on once only or other
our ours ourselves out over own same she should so some such than that the their theirs them themselves then there these
they this those through to too under until up very was we were what when where which while who whom why will with would
you your yours yourself yourselves movie film films movies one get got really much even also still""".split())

# ordinary words that must never become spoiler terms even if a character is called that
COMMON = set("""will rose mark grace hope joy faith star king queen john jack paul peter james george bill tom sam max ray
dan ben jim joe frank bob dave tony ted fred sue ann may june april august summer winter spring day night man woman boy
girl kid mother father son daughter friend""".split())


def split_sentences(text: str) -> List[Tuple[int, int]]:
    """Return (start, end) character offsets of each sentence (no empty ones)."""
    spans: List[Tuple[int, int]] = []
    pos = 0
    for m in SENT_RE.finditer(text):
        s, e = pos, m.start()
        last = text[s:e].split()[-1].lower() if text[s:e].split() else ""
        if last in ABBR and "\n" not in m.group(0):
            continue  # "Dr. Strange", "e.g. this": not a sentence end
        if text[s:e].strip():
            spans.append((s, e))
        pos = m.end()
    if text[pos:].strip():
        spans.append((pos, len(text)))
    # trim whitespace
    out = []
    for s, e in spans:
        while s < e and text[s].isspace():
            s += 1
        while e > s and text[e - 1].isspace():
            e -= 1
        if e > s:
            out.append((s, e))
    return out


def strip_tags(text: str) -> Tuple[str, List[Tuple[int, int]]]:
    """Remove ||spoiler|| markers; return clean text and the tagged (start, end) ranges in clean text."""
    clean, ranges, last = [], [], 0
    offset = 0
    for m in TAG_RE.finditer(text):
        clean.append(text[last:m.start()])
        offset += m.start() - last
        inner = m.group(1)
        ranges.append((offset, offset + len(inner)))
        clean.append(inner)
        offset += len(inner)
        last = m.end()
    clean.append(text[last:])
    return "".join(clean), ranges


def content_words(text: str) -> List[str]:
    return [w for w in re.findall(r"[a-z][a-z']{2,}", text.lower()) if w not in STOP]
