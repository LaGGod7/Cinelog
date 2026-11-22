"""Sprint 2 partial performance checks (engine level, in-process, no network).

    python -m scripts.sprint2_benchmarks > ../docs/sprint2/evidence/benchmarks.txt

NFR01: autocomplete p95 <= 100 ms over 1,000 random prefixes on 10,000+ titles (server-side Trie lookup).
NFR02 (time part only): <= 20 ms per review for the spoiler scan with the deployed model files.
The full NFR01 HTTP benchmark on the synced TMDB catalogue and the NFR02 accuracy target are Sprint 3 work.
"""
from __future__ import annotations

import os
import random
import statistics
import time

from app.dsa.trie import Trie
from app.spoiler.shield import FilmInfo, SpoilerShield
from app.spoiler.text import split_sentences
from app.spoiler.wordlist import terms_from_cast

WORDS = ("dark night star river city love war last king lost red blue home road dream fire stone ghost silent golden "
         "broken hidden iron paper glass winter summer secret wild long little great final first black white").split()


def pct(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(p / 100 * (len(xs) - 1))))]


def bench_trie(n=10_000, q=1_000):
    rnd = random.Random(16)
    t = Trie(k=10)
    titles = []
    for i in range(n):
        title = " ".join(rnd.choice(WORDS) for _ in range(rnd.randint(1, 4))).title() + f" {i}"
        titles.append(title)
        t.insert(title, i, popularity=rnd.random() * 100)
    prefixes = []
    for _ in range(q):
        w = rnd.choice(titles)
        prefixes.append(w[: rnd.randint(2, min(8, len(w)))].lower())
    times = []
    for p in prefixes:
        s = time.perf_counter()
        r = t.search(p)
        times.append((time.perf_counter() - s) * 1000)
        assert len(r) <= 10
    print(f"NFR01 Trie autocomplete: {n:,} titles, {q:,} random prefixes (2-8 letters)")
    print(f"  p50 = {pct(times, 50):.4f} ms   p95 = {pct(times, 95):.4f} ms   max = {max(times):.4f} ms   target p95 <= 100 ms"
          f"   -> {'PASS' if pct(times, 95) <= 100 else 'FAIL'}")


def bench_scan(model_dir: str, n=200):
    plot = ("Child psychologist Malcolm Crowe tries to help Cole Sear, a frightened boy who tells him that he sees dead "
            "people. Malcolm slowly believes the boy and helps the ghosts finish their unfinished business. In the final "
            "scene Malcolm realises that he was shot by a former patient at the start of the story and has been a ghost "
            "himself all along. His wife never answered him because she could not see him.")
    passages = [plot[s:e] for s, e in split_sentences(plot)]
    sh = SpoilerShield(model_dir if os.path.isdir(model_dir) else None)
    if not sh.space.fitted:
        sh.fit_space(passages * 5)
    info = FilmInfo(745, 1, terms_from_cast(["Malcolm Crowe", "Cole Sear", "Lynn Sear"]), passages, [])
    base = ["Bruce Willis is calm and the boy is brilliant.", "The score is quiet and the pacing is patient.",
            "In the end Malcolm was a ghost all along.", "I did not expect that twist at all, rewatch it.",
            "Cole tells Malcolm he sees dead people and it is chilling.", "Lovely cinematography and a moving story."]
    rnd = random.Random(7)
    reviews = [" ".join(rnd.choice(base) for _ in range(rnd.randint(2, 12))) for _ in range(n)]
    sh.scan(reviews[0], info)  # warm-up (loads the per-film caches once)
    times = []
    for r in reviews:
        s = time.perf_counter()
        sh.scan(r, info)
        times.append((time.perf_counter() - s) * 1000)
    st = sh.status()
    layers = ", ".join(k for k in ("ml", "rnn", "semantic") if st.get(k)) or "rules only"
    print(f"\nNFR02 (time) spoiler scan: {n} reviews of 2-12 sentences, layers: {layers}")
    print(f"  mean = {statistics.mean(times):.1f} ms   p50 = {pct(times, 50):.1f} ms   p95 = {pct(times, 95):.1f} ms"
          f"   target <= 20 ms per review   -> {'PASS' if statistics.mean(times) <= 20 else 'NOT MET'}")
    print(f"  caches after the run: {st['caches']}")


if __name__ == "__main__":
    print("CineLog Sprint 2 benchmarks |", time.strftime("%Y-%m-%d %H:%M:%S"), "| single process, build-server CPU (re-run on the demo laptop)\n")
    bench_trie()
    bench_scan(os.path.join(os.path.dirname(os.path.dirname(__file__)), "models"))
