"""Sentence-level evaluation of the Spoiler Shield on the hand-labelled gold set (ml/gold_sentences.json).

    python -m ml.eval_sentences --movies ..\\mltraining\\IMDB_movie_details.json --models models

Two questions, answered separately:
  1. SELECTION - given that a review is blurred, does the shield hide the right sentences?
     (scan(force_blur=True); precision / recall over sentences, share of review hidden, 'hit' = at least one real spoiler hidden)
  2. END TO END - on all gold reviews, how many get blurred / sent to moderators, by whether they hold a real spoiler?
Labels are DRAFTS written from the plot synopsis, not human-verified; 'unsure' sentences count for neither side.
"""
from __future__ import annotations

import argparse
import json
import os

import numpy as np

from app.spoiler.retrieval import make_passages
from app.spoiler.shield import FilmInfo, SpoilerShield
from ml.train_ml import read_jsonl

GOLD = os.path.join(os.path.dirname(__file__), "gold_sentences.json")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--movies", required=True)
    ap.add_argument("--models", default="models")
    ap.add_argument("--gold", default=GOLD)
    ap.add_argument("--no-rnn", action="store_true", help="evaluate the ML model alone (for comparing with the recurrent blend)")
    a = ap.parse_args(argv)
    gold = json.load(open(a.gold, encoding="utf-8"))["reviews"]
    mv = read_jsonl(a.movies).set_index("movie_id")
    plots = {m: ((r.plot_synopsis or "").strip() or (r.plot_summary or "").strip()) for m, r in mv.iterrows()}
    sh = SpoilerShield(a.models)
    infos: dict = {}
    tp = fp = fn = hit = n_rev = 0
    share = []
    e2e = {"real": [0, 0, 0], "flag_only": [0, 0, 0], "clean": [0, 0, 0]}  # n, blurred, to moderators
    for g in gold:
        if g["dataset_spoiler_flag"] and not g["labelled"]:
            continue  # flagged but never labelled (none in the shipped file)
        mid = g["movie_id"]
        if mid not in infos:
            infos[mid] = FilmInfo(len(infos) + 1, 1, [], make_passages(plots.get(mid, "")), [])
        real = {s.strip() for s in g["spoiler_sentences"]}
        unsure = {s.strip() for s in g["unsure_sentences"]}
        kind = "real" if real else ("flag_only" if g["dataset_spoiler_flag"] else "clean")
        res = sh.scan(g["text"], infos[mid], use_rnn=not a.no_rnn)
        row = e2e[kind]; row[0] += 1; row[1] += any(s.blurred for s in res.segments); row[2] += res.uncertain
        if not real:
            continue
        forced = sh.scan(g["text"], infos[mid], force_blur=True, use_rnn=not a.no_rnn)
        chosen = [s.text.strip() for s in forced.segments if s.blurred]
        t = sum(c in real for c in chosen)
        tp += t; fp += sum(c not in real and c not in unsure for c in chosen); fn += len(real) - t
        n_rev += 1; hit += t > 0
        share.append(len(chosen) / max(len(forced.segments), 1))
    pr, rc = tp / max(tp + fp, 1), tp / max(tp + fn, 1)
    print(f"SELECTION (review already blurred), {n_rev} reviews with {tp + fn} real spoiler sentences")
    print(f"  precision {pr:.3f}   recall {rc:.3f}   F1 {2 * pr * rc / max(pr + rc, 1e-9):.3f}   "
          f"reviews where a real spoiler is hidden {hit / n_rev:.3f}   share of each review hidden {np.mean(share):.3f}")
    print("END TO END (the shield's own decision)")
    names = {"real": "contain a real spoiler sentence", "flag_only": "flagged by dataset, no real giveaway", "clean": "clean"}
    out = {}
    for k, (n, b, u) in e2e.items():
        print(f"  {names[k]:40s} n={n:3d}  blurred {b / max(n, 1):.3f}  to moderators {u / max(n, 1):.3f}")
        out[k] = {"n": n, "blurred": b / max(n, 1), "to_moderators": u / max(n, 1)}
    out["selection"] = {"precision": pr, "recall": rc, "review_hit": hit / max(n_rev, 1), "share_hidden": float(np.mean(share))}
    return out


if __name__ == "__main__":
    main()
