"""End-to-end evaluation of the hybrid Spoiler Shield (rules + RAG + ML) on held-out movies / a gold set.

    python -m ml.eval_shield --reviews gold_reviews.json --movies IMDB_movie_details.json --models models

Reports the KPI from the project: share of spoiler reviews caught (>=1 sentence blurred or flagged uncertain->moderator)
and share of clean reviews wrongly blurred, with bootstrap 95% confidence intervals.
"""
from __future__ import annotations

import argparse

import numpy as np

from app.spoiler.retrieval import make_passages
from app.spoiler.shield import FilmInfo, SpoilerShield
from ml.train_ml import load, split_by_movie


def ci(x, n=1000, seed=0):
    rng = np.random.RandomState(seed)
    x = np.asarray(x, dtype=float)
    if len(x) == 0:
        return (float("nan"),) * 3
    bs = [rng.choice(x, len(x)).mean() for _ in range(n)]
    return float(x.mean()), float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--reviews", required=True)
    ap.add_argument("--movies", required=True)
    ap.add_argument("--models", default="models")
    ap.add_argument("--max-reviews", type=int, default=3000)
    ap.add_argument("--only-test-split", action="store_true", default=True)
    ap.add_argument("--seed", type=int, default=42)
    a = ap.parse_args(argv)
    reviews, plots = load(a.reviews, a.movies, None, a.seed)
    if a.only_test_split:
        reviews = reviews[split_by_movie(reviews, a.seed, plots.keys()) == "test"]
    reviews = reviews.sample(min(a.max_reviews, len(reviews)), random_state=a.seed)
    sh = SpoilerShield(a.models)
    print("shield:", sh.status()["ml"] and "ML bundle loaded" or "rules+rag only")
    infos = {}
    # (name, scan kwargs). "ml only" = no plot matching, no cues. Soft rules = plot similarity / rare words / cues.
    variants = [
        ("ml only", dict(rag=False, cue=False, gate=False)),
        ("rag only (no ml)", dict(use_ml=False, cue=False)),
        ("rag+cue (no ml)", dict(use_ml=False)),
        ("old fusion: ml+rag+cue noisy-OR", dict(gate=False)),
        ("FULL: model decides, rules pick", dict()),
    ]
    stats = {name: ([], [], []) for name, _ in variants}
    hard_caught = {name: [] for name, _ in variants}
    blur_share = {name: [] for name, _ in variants}
    for _, r in reviews.iterrows():
        mid = r["movie_id"]
        if mid not in infos:
            infos[mid] = FilmInfo(len(infos) + 1, 1, [], make_passages(plots.get(mid, "")), [])
        for name, kw in variants:
            res = sh.scan(r["review_text"], infos[mid], **kw)
            any_blur = any(s.blurred for s in res.segments)
            caught, wrong, flagged = stats[name]
            if r["is_spoiler"]:
                caught.append(any_blur or res.uncertain)
                hard_caught[name].append(any_blur)
            else:
                wrong.append(any_blur)
                flagged.append(res.uncertain)
                blur_share[name].append(np.mean([s.blurred for s in res.segments]) if res.segments else 0.0)
    out = {}
    print(f"{'variant':32s} {'blurred':>8s} {'caught':>7s} {'wrongly blurred':>16s} {'to moderators':>14s} {'sentences blurred in clean':>27s}")
    for name, _ in variants:
        caught, wrong, flagged = stats[name]
        out[name] = {"spoilers_caught": ci(caught), "clean_wrongly_blurred": ci(wrong), "clean_sent_to_moderators": ci(flagged),
                     "clean_sentence_blur_share": float(np.mean(blur_share[name]))}
        out[name]["spoilers_blurred"] = float(np.mean(hard_caught[name]))
        print(f"{name:32s} {out[name]['spoilers_blurred']:8.3f} {out[name]['spoilers_caught'][0]:7.3f} {out[name]['clean_wrongly_blurred'][0]:16.3f} "
              f"{out[name]['clean_sent_to_moderators'][0]:14.3f} {out[name]['clean_sentence_blur_share']:27.3f}")
    out["n_spoiler"], out["n_clean"] = len(stats["ml only"][0]), len(stats["ml only"][1])
    print(f"n_spoiler={out['n_spoiler']} n_clean={out['n_clean']}  (95% CIs are in the returned dict)")
    return out


if __name__ == "__main__":
    main()
