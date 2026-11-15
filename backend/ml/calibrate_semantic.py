"""Set the cut-offs of the semantic plot-match layer from real clean reviews (no spoiler labels are needed for this).

    python -m ml.calibrate_semantic --reviews ..\\mltraining\\small_sample.json --movies ..\\mltraining\\IMDB_movie_details.json --models models

The layer is a fixed public encoder, so nothing is trained: the only question is how similar a review sentence must be to the late plot
before it is called a giveaway. That is answered by looking at reviews that are NOT spoilers (IMDB-flagged clean reviews of films the
site's models are not tested on) and choosing the similarity that only `--blur-fpr` (default 3%) / `--warn-fpr` (default 10%) of them reach.
The two cut-offs come from SHORT reviews (<= 6 sentences, like the reviews written on this site). A longer review has more sentences
that can match by chance, so the script also stores the tail of the per-sentence score on clean reviews ("sentence_tail"); the shield
uses it to raise the cut-off with the number of sentences so that the share of clean reviews blurred stays near --blur-fpr at any length.
The IMDB spoiler flag is reported for information only.
Writes <models>/semantic/meta.json.
"""
from __future__ import annotations

import argparse
import json
import os
import time

import numpy as np

from app.spoiler.semantic import SemanticMatcher
from app.spoiler.text import split_sentences
from ml.train_ml import load, split_by_movie


def main(argv=None) -> dict:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reviews", required=True)
    ap.add_argument("--movies", required=True)
    ap.add_argument("--models", default="models")
    ap.add_argument("--blur-fpr", type=float, default=0.03)
    ap.add_argument("--warn-fpr", type=float, default=0.10)
    ap.add_argument("--max-short", type=int, default=6)
    ap.add_argument("--max-clean", type=int, default=2500)
    ap.add_argument("--tail-reviews", type=int, default=1500, help="clean reviews of ANY length whose sentences give the tail table "
                    "used to raise the cut-off for longer reviews")
    ap.add_argument("--seed", type=int, default=42)
    a = ap.parse_args(argv)
    sem = SemanticMatcher.load(a.models)
    if sem is None:
        raise SystemExit("no semantic encoder in " + os.path.join(a.models, "semantic"))
    reviews, plots = load(a.reviews, a.movies, None, a.seed)
    split = split_by_movie(reviews, a.seed, plots.keys())
    reviews = reviews.assign(split=split)
    from app.spoiler.retrieval import make_passages
    t0 = time.time()
    cache, rows = {}, []
    clean_seen = 0
    tail_scores, tail_seen, long_test = [], 0, []      # per-sentence scores of clean reviews of any length; (max score, n, y) of test reviews

    def plot_of(mid):
        if mid not in cache:
            ps = plots.get(mid, "")
            cache[mid] = sem.plot_matrix(make_passages(ps)) if len(ps) > 200 else None
        return cache[mid]

    for mid, t, y, sp in zip(reviews.movie_id, reviews.review_text, reviews.is_spoiler, reviews.split):
        sents = [t[s:e].strip() for s, e in split_sentences(t) if t[s:e].strip()]
        if not sents:
            continue
        if len(sents) > a.max_short:
            # longer reviews: clean ones from non-test films feed the tail table, test ones check it afterwards
            if sp == "test" and len(long_test) < 1500 and plot_of(mid) is not None:
                long_test.append((float(sem.scores(sents, plot_of(mid)).max()), len(sents), int(y)))
            elif sp != "test" and y == 0 and tail_seen < a.tail_reviews and plot_of(mid) is not None:
                tail_scores.append(sem.scores(sents, plot_of(mid)))
                tail_seen += 1
            continue
        if y == 0 and sp != "test":
            if clean_seen >= a.max_clean:
                continue
            clean_seen += 1
        elif sp != "test":
            continue          # spoiler-flagged reviews of training films are not needed
        if plot_of(mid) is None:
            continue
        sc = sem.scores(sents, cache[mid])
        if y == 0 and sp != "test":
            tail_scores.append(sc)
        rows.append((float(sc.max()), int(y), sp))
        if len(rows) % 500 == 0:
            print(f"  {len(rows)} reviews scored, {time.time() - t0:.0f}s", flush=True)
    s = np.array([r[0] for r in rows]); y = np.array([r[1] for r in rows]); sp = np.array([r[2] for r in rows])
    cal = (y == 0) & (sp != "test")
    thr_blur = float(np.quantile(s[cal], 1 - a.blur_fpr)); thr_warn = float(np.quantile(s[cal], 1 - a.warn_fpr))
    t = sp == "test"
    rep = {"calibrated_on_clean_short_reviews": int(cal.sum()),
           "test_short_clean": int(((y == 0) & t).sum()), "test_short_spoiler_flagged": int(((y == 1) & t).sum()),
           "test_clean_over_blur": float((s[(y == 0) & t] >= thr_blur).mean()), "test_clean_over_warn": float((s[(y == 0) & t] >= thr_warn).mean()),
           "test_imdb_spoiler_over_blur": float((s[(y == 1) & t] >= thr_blur).mean()) if ((y == 1) & t).any() else None,
           "test_imdb_spoiler_over_warn": float((s[(y == 1) & t] >= thr_warn).mean()) if ((y == 1) & t).any() else None}
    meta = {**sem.meta, "thr_blur": thr_blur, "thr_warn": thr_warn, "blur_fpr": a.blur_fpr, "warn_fpr": a.warn_fpr,
            "max_short_sentences": a.max_short, "report": rep, "encoder": sem.meta.get("encoder", "all-MiniLM-L6-v2 (int8 ONNX)")}
    if tail_scores:
        # tail of the per-sentence score on clean reviews: lets the shield raise the cut-off for a review with many sentences
        allc = np.concatenate(tail_scores)
        ps = [p for p in (0.2, 0.1, 0.05, 0.03, 0.02, 0.01, 0.005, 0.003, 0.002, 0.001, 0.0005) if p * len(allc) >= 5]
        meta["sentence_tail"] = {"p": ps, "score": [float(np.quantile(allc, 1 - p)) for p in ps], "n_sentences": int(len(allc))}
        chk = SemanticMatcher(sem.session, sem.tokenizer, meta)
        if long_test:
            lt = np.array(long_test)
            over = np.array([m >= chk.blur_threshold(int(n)) for m, n, _ in long_test])
            flat = lt[:, 0] >= thr_blur
            cl = lt[:, 2] == 0
            rep["test_long_clean"] = int(cl.sum())
            rep["test_long_clean_over_blur_flat_cutoff"] = float(flat[cl].mean()) if cl.any() else None
            rep["test_long_clean_over_blur_length_adjusted"] = float(over[cl].mean()) if cl.any() else None
    with open(os.path.join(a.models, "semantic", "meta.json"), "w", encoding="utf-8") as fh:
        json.dump(meta, fh, indent=1)
    print(f"thr_blur = {thr_blur:.3f} (clean short reviews over it: {a.blur_fpr:.0%}),  thr_warn = {thr_warn:.3f} ({a.warn_fpr:.0%})")
    print(json.dumps(rep, indent=1))
    return meta


if __name__ == "__main__":
    main()
