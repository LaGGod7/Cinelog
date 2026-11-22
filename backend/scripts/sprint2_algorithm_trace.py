"""Sprint 2 algorithm and data-structure trace: one runnable demo per engine structure, printing input -> output.

    python -m scripts.sprint2_algorithm_trace > ../docs/sprint2/evidence/algorithm_traces.txt
"""
from __future__ import annotations

import threading
import time

from app.dsa.aho_corasick import AhoCorasick
from app.dsa.inverted_index import InvertedIndex, top_k
from app.dsa.lru import LRUCache
from app.dsa.trie import Trie
from app.scheduler.pool import BATCH, USER, BoundedPriorityQueue, Job, QueueFull, WorkerPool
from app.security import TokenBucket
from app.spoiler.text import normalize_text, split_sentences
from app.workflow import POLL_T, REVIEW_T, can


def h(title: str) -> None:
    print("\n" + "=" * 78 + f"\n{title}\n" + "=" * 78)


def main() -> None:
    print("CineLog Sprint 2 algorithm trace  |  run:", time.strftime("%Y-%m-%d %H:%M:%S"))

    h("E1-A  Trie with top-10 per node (autocomplete, FR-04 / NFR-01)")
    t = Trie(k=10)
    films = [("The Dark Knight", 1, 95.0), ("Dark Orbit", 2, 40.0), ("Darkest Hour", 3, 60.0), ("Drishyam", 4, 88.0),
             ("Dangal", 5, 91.0), ("Interstellar", 6, 97.0), ("Inception", 7, 99.0)]
    for title, fid, pop in films:
        t.insert(title, fid, pop)
    for q in ("dar", "da", "in", "d", "xyz"):
        ids = t.search(q)
        names = [next(f[0] for f in films if f[1] == i) for i in ids]
        print(f"search({q!r:7}) -> {names}")
    print("Edge case: one letter is still answered by the Trie; the API layer refuses < 2 letters (returns []).")
    print("Edge case: 'dark k' (half-typed second word) is matched because titles are also indexed from each word.")
    print(f"search('knight') -> {t.search('knight')}")

    h("E1-B  Aho-Corasick automaton (spoiler word list, one pass over the review)")
    ac = AhoCorasick.from_terms([("tyler durden", "name"), ("split personality", "plot"), ("durden", "name"), ("tower", "plot")])
    review = "Great twist. Tyler Durden is his own split personality. Towering performance."
    print("terms  :", ["tyler durden", "split personality", "durden", "tower"])
    print("review :", review)
    for s, e, term, kind in ac.search(review):
        print(f"  hit [{s:2},{e:2}) {term!r:20} kind={kind}")
    print("Edge case: 'Towering' does NOT match 'tower' (whole words only); overlapping 'durden' inside")
    print("           'tyler durden' is reported too, so names and phrases both count.")

    h("E1-C  Unicode normalisation before matching (DEF-07 / DEF-08 fixed in Sprint 2)")
    for raw in ("Tyler Dur​den", "split personality", "ｓｐｌｉｔ", "क्‍ष"):
        clean = normalize_text(raw)
        hits = [x[2] for x in ac.search(clean)]
        print(f"  {raw!r:28} -> {clean!r:22} hits={hits}")

    h("E1-D  Sentence splitter used for sentence-level blurring")
    txt = "Loved it.Dr. Crowe is great! He was dead all along... Wow"
    print(txt)
    for s, e in split_sentences(txt):
        print(f"  [{s:2},{e:2}) {txt[s:e]!r}")

    h("E1-E  Inverted index with sorted posting lists + heap top-k (search with filters, FR-05)")
    ix = InvertedIndex()
    ix.add(1, {"title": "The Dark Knight"}, year=2008, genres=["Action", "Crime"], cast=["Christian Bale"], popularity=95)
    ix.add(2, {"title": "Dark Orbit"}, year=2021, genres=["Sci-Fi"], cast=["Lee Cho"], popularity=40)
    ix.add(3, {"title": "Darkest Hour"}, year=2017, genres=["Drama"], cast=["Gary Oldman"], popularity=60)
    print("search('dark')                 ->", ix.search("dark"))
    print("search('dark', genre='Crime')  ->", ix.search("dark", genre="Crime"))
    print("search('dark', year=2021)      ->", ix.search("dark", year=2021))
    print("search('dark', genre='Horror') ->", ix.search("dark", genre="Horror"), " (edge case: empty, no error)")
    print("top_k([(0.2,1),(0.9,2),(0.5,3),(0.7,4)], 2) ->", top_k([(0.2, 1), (0.9, 2), (0.5, 3), (0.7, 4)], 2))

    h("E2-A  State machines with compare-and-swap (reviews FR-09, polls FR-13)")
    for src, dst in (("draft", "open"), ("open", "closed"), ("open", "cancelled"), ("closed", "open")):
        print(f"  poll   {src:>9} -> {dst:<9} allowed={can(POLL_T, src, dst)}")
    for src, dst in (("pending_scan", "published"), ("published", "hidden"), ("removed", "published")):
        print(f"  review {src:>12} -> {dst:<9} allowed={can(REVIEW_T, src, dst)}")
    print("Edge case: a disallowed change raises InvalidTransition -> HTTP 409; the UPDATE ... WHERE state=<old>")
    print("           changes 0 rows if someone else changed the state first.")

    h("E3-A  Bounded priority queue (mutex + 2 semaphores): USER before BATCH, FIFO inside a priority")
    order: list = []
    pool = WorkerPool(workers=1, capacity=8)
    for i in range(3):
        pool.submit(Job(f"BATCH sync-{i}", lambda i=i: order.append(f"BATCH sync-{i}"), priority=BATCH))
    for i in range(2):
        pool.submit(Job(f"USER scan-{i}", lambda i=i: order.append(f"USER scan-{i}"), priority=USER))
    print("submitted:", ["BATCH sync-0", "BATCH sync-1", "BATCH sync-2", "USER scan-0", "USER scan-1"])
    pool.start(); pool.wait_idle(5); pool.shutdown()
    print("ran      :", order)
    q = BoundedPriorityQueue(2)
    q.put(Job("a", lambda: None)); q.put(Job("b", lambda: None))
    try:
        q.put(Job("c", lambda: None), timeout=0.1)
    except QueueFull:
        print("Edge case: capacity 2, third put -> QueueFull after 0.1 s (producer never blocks forever)")

    h("E3-B  Retry with exponential back-off (0.01 s, 0.02 s, 0.04 s), then failed")
    calls: list = []

    def flaky():
        calls.append(round(time.time(), 3))
        raise RuntimeError("TMDB timeout")

    p2 = WorkerPool(workers=1, capacity=4, backoff_base=0.01).start()
    p2.submit(Job("sync-film-42", flaky, priority=BATCH, max_retries=3)); p2.wait_idle(5); p2.shutdown()
    gaps = [round(b - a, 3) for a, b in zip(calls, calls[1:])]
    print(f"attempts={len(calls)} gaps={gaps} stats={p2.stats} failed_jobs={p2.failed_jobs}")

    h("E3-C  LRU cache (hash map + doubly linked list), eviction counter added in Sprint 2 (DEF-10)")
    c: LRUCache = LRUCache(3)
    for k in ("film-1", "film-2", "film-3"):
        c.put(k, k.upper())
    c.get("film-1")
    c.put("film-4", "FILM-4")
    print("MRU -> LRU:", c.keys_mru_first(), " (film-2 was evicted)")
    print("stats     :", c.stats())

    h("E4-A  Token bucket (5 sign-in attempts per minute per address, FR-01)")
    now = [0.0]
    b = TokenBucket(5, 5 / 60, clock=lambda: now[0])
    print("t=0s  attempts 1-6:", [b.allow("10.0.0.7") for _ in range(6)])
    now[0] = 12.0
    print("t=12s attempt 7  :", b.allow("10.0.0.7"), "(one token refilled)")
    print("other address     :", b.allow("10.0.0.8"))

    h("E4-B  Concurrency: 20 threads take the last token at the same moment")
    b2 = TokenBucket(1, 0.0)
    wins: list = []
    bar = threading.Barrier(20)

    def grab():
        bar.wait()
        wins.append(b2.allow("same"))

    ts = [threading.Thread(target=grab) for _ in range(20)]
    [x.start() for x in ts]; [x.join() for x in ts]
    print(f"allowed={wins.count(True)} refused={wins.count(False)} (the bucket's lock makes it exactly one)")


if __name__ == "__main__":
    main()
