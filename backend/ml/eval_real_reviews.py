"""Run the whole shield, exactly as the site does, on real IMDB reviews of films the trained models never saw.

    python -m ml.eval_real_reviews --reviews ..\\mltraining\\small_sample.json --movies ..\\mltraining\\IMDB_movie_details.json --models models

For each review the film's plot synopsis is the plot context; the IMDB data has no cast list, so words that are capitalised
at least twice inside the synopsis stand in for character names (weak 'name' terms, as on the site).
Prints, for IMDB-flagged spoiler reviews and for clean reviews: the share blurred, sent to moderators, and given the label,
overall and by review length. IMDB's flag is set by the review's author and is noisy, so read these as a comparison
between versions of the shield, not as exact accuracy.
"""
from __future__ import annotations

import argparse
import re

import numpy as np

from app.spoiler.retrieval import make_passages
from app.spoiler.shield import FilmInfo, SpoilerShield
from app.spoiler.text import COMMON, STOP, split_sentences, strip_tags
from ml.train_ml import load, split_by_movie


def names_from_plot(plot: str) -> list[tuple[str, str]]:
    seen: dict[str, int] = {}
    for s, e in split_sentences(plot):
        for w in re.findall(r"[A-Za-z][A-Za-z'\-]+", plot[s:e])[1:]:           # skip the sentence-initial word
            lw = w.lower()
            if w[0].isupper() and len(w) >= 4 and lw not in STOP and lw not in COMMON:
                seen[lw] = seen.get(lw, 0) + 1
    return [(k, "name") for k, v in seen.items() if v >= 2]


def main(argv=None) -> dict:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reviews", required=True)
    ap.add_argument("--movies", required=True)
    ap.add_argument("--models", default="models")
    ap.add_argument("--split", default="test", choices=["test", "val", "both"])
    ap.add_argument("--seed", type=int, default=42)
    a = ap.parse_args(argv)
    reviews, plots = load(a.reviews, a.movies, None, a.seed)
    reviews = reviews.assign(split=split_by_movie(reviews, a.seed, plots.keys()))
    sub = reviews[reviews.split != "train"] if a.split == "both" else reviews[reviews.split == a.split]
    sh = SpoilerShield(a.models)
    rows = []
    for k, (mid, g) in enumerate(sub.groupby("movie_id")):
        plot = plots.get(mid, "")
        info = FilmInfo(k + 1, 1, names_from_plot(plot), make_passages(plot), [])
        for text, y in zip(g.review_text, g.is_spoiler):
            clean, _ = strip_tags(text)
            n = len(split_sentences(clean))
            if not n:
                continue
            r = sh.scan(text, info)
            rows.append((int(y), n, any(s.blurred for s in r.segments), r.uncertain, r.warn))
        if k % 25 == 0:
            print(f"  {k} films, {len(rows)} reviews", flush=True)
    R = np.array(rows, dtype=int)
    y, n, blur, unc, warn = R.T
    out = {}

    def line(name, m):
        sp, cl = m & (y == 1), m & (y == 0)
        if not sp.any() or not cl.any():
            return
        out[name] = {"reviews": int(m.sum()), "spoilers_blurred": float(blur[sp].mean()), "clean_blurred": float(blur[cl].mean()),
                     "spoilers_to_moderators": float(unc[sp].mean()), "clean_to_moderators": float(unc[cl].mean()),
                     "spoilers_labelled": float(warn[sp].mean()), "clean_labelled": float(warn[cl].mean()),
                     "blur_precision": float(y[m & (blur == 1)].mean()) if (m & (blur == 1)).any() else None}
        o = out[name]
        print(f"{name:22s} n={o['reviews']:5d}  spoilers: blurred {o['spoilers_blurred']:.1%}, moderators {o['spoilers_to_moderators']:.1%}, "
              f"label {o['spoilers_labelled']:.1%}   clean: blurred {o['clean_blurred']:.1%}, moderators {o['clean_to_moderators']:.1%}, "
              f"label {o['clean_labelled']:.1%}")

    print(f"\nshield layers: {sh.status()}")
    line("all reviews", n > 0)
    line("1-6 sentences", n <= 6)
    line("7-17 sentences", (n >= 7) & (n <= 17))
    line("18+ sentences", n >= 18)
    return out


if __name__ == "__main__":
    main()
