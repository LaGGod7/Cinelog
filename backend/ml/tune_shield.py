"""Pick the shield's blur / moderator thresholds from data instead of by hand.

    python -m ml.tune_shield --reviews ..\\mltraining\\small_sample.json --movies ..\\mltraining\\IMDB_movie_details.json --models models

If the recurrent model (spoiler_rnn.npz, from ml.train_rnn) is present it also tunes the BLEND of the two models: the weight
of the RNN (chosen by validation AUC; 0 means it adds nothing and is not used) and the blend's own thresholds. This is done
against the ML model that is actually deployed, which is why it is a separate step after training.

Scores the validation movies (never seen in training), then sets
  thr_high  = model probability at which `--blur-fpr` of clean reviews would be blurred   (default 8 %)
  thr_low   = probability at which `--ask-fpr` of clean reviews would reach a moderator    (default 15 %)
and writes models/shield_thresholds.json, which the shield reads at start-up (the big model file is not touched).
"""
from __future__ import annotations

import argparse
import json
import os

import numpy as np

from sklearn.metrics import roc_auc_score

from app.spoiler.ml import MLBundle
from app.spoiler.rnn import RNNScorer
from app.spoiler.retrieval import make_passages
from ml.train_ml import load, split_by_movie

FILE = "shield_thresholds.json"


def score(bundle: MLBundle, reviews, plots) -> np.ndarray:
    out = np.zeros(len(reviews))
    pos = {i: k for k, i in enumerate(reviews.index)}
    for mid, g in reviews.groupby("movie_id"):
        ctx = bundle.space.film_ctx(make_passages(plots.get(mid, "")), [])
        texts = g["review_text"].tolist()
        p = bundle.predict(texts, bundle.space.reviews_features(texts, ctx))
        for i, v in zip(g.index, p, strict=False):
            out[pos[i]] = v
    return out


def score_rnn(bundle: MLBundle, rnn: RNNScorer, reviews, plots):
    """(ML probabilities, RNN probabilities) for the same reviews."""
    pm, pr = np.zeros(len(reviews)), np.zeros(len(reviews))
    pos = {i: k for k, i in enumerate(reviews.index)}
    for mid, g in reviews.groupby("movie_id"):
        ctx = bundle.space.film_ctx(make_passages(plots.get(mid, "")), [])
        texts = g["review_text"].tolist()
        dense = bundle.space.reviews_features(texts, ctx)
        a, b = bundle.predict(texts, dense), rnn.predict(texts, dense)
        for i, x, z in zip(g.index, a, b, strict=False):
            pm[pos[i]], pr[pos[i]] = x, z
    return pm, pr


def paired_ci(y, p_a, p_b, n=500, seed=0):
    """95% interval of AUC(b) - AUC(a), resampling reviews (so it says whether a gain could be luck)."""
    rng = np.random.RandomState(seed)
    d = []
    for _ in range(n):
        i = rng.randint(0, len(y), len(y))
        if y[i].min() == y[i].max():
            continue
        d.append(roc_auc_score(y[i], p_b[i]) - roc_auc_score(y[i], p_a[i]))
    return float(np.percentile(d, 2.5)), float(np.percentile(d, 97.5))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--reviews", required=True)
    ap.add_argument("--movies", required=True)
    ap.add_argument("--models", default="models")
    ap.add_argument("--blur-fpr", type=float, default=0.08)
    ap.add_argument("--ask-fpr", type=float, default=0.15)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--recall", type=float, default=None,
                    help="also set a third, lighter cut-off: reviews scoring above it get a reader-visible 'possible spoilers' label "
                         "(no blur, no moderator queue) so that this share of validation spoiler reviews is flagged in one way or another. "
                         "The price - the share of clean reviews that get the label - is printed.")
    a = ap.parse_args(argv)
    bundle = MLBundle.load(a.models)
    if bundle is None:
        raise SystemExit("no trained model in " + a.models)
    reviews, plots = load(a.reviews, a.movies, None, a.seed)
    split = split_by_movie(reviews, a.seed, plots.keys())
    val, test = reviews[split == "val"], reviews[split == "test"]
    pv, pt = score(bundle, val, plots), score(bundle, test, plots)
    yv, yt = val["is_spoiler"].to_numpy().astype(bool), test["is_spoiler"].to_numpy().astype(bool)
    hi = float(np.quantile(pv[~yv], 1 - a.blur_fpr))
    lo = float(np.quantile(pv[~yv], 1 - a.ask_fpr))
    lo = min(lo, hi - 0.02)

    def report(p, y):
        blur, ask = p >= hi, (p >= lo) & (p < hi)
        return {"n": int(len(p)), "spoilers_blurred": float(blur[y].mean()), "spoilers_to_moderators": float(ask[y].mean()),
                "clean_wrongly_blurred": float(blur[~y].mean()), "clean_to_moderators": float(ask[~y].mean())}

    def warn_level(p, y, ceiling):
        """Cut-off that flags `--recall` of the spoiler reviews (blur, moderators or label); never above the moderator cut-off."""
        return min(float(np.quantile(p[y], 1 - a.recall)), ceiling)

    def flagged(p, y, thr):
        return {"spoilers_flagged": float((p[y] >= thr).mean()), "clean_flagged": float((p[~y] >= thr).mean())}

    res = {"thr_low": lo, "thr_high": hi, "blur_fpr": a.blur_fpr, "ask_fpr": a.ask_fpr,
           "validation": report(pv, yv), "test": report(pt, yt), "n_val": int(len(pv)), "n_test": int(len(pt))}
    if a.recall:
        res["thr_warn"] = warn_level(pv, yv, lo)
        res["recall_target"] = a.recall
        res["flagged"] = {"validation": flagged(pv, yv, res["thr_warn"]), "test": flagged(pt, yt, res["thr_warn"])}
    rnn = RNNScorer.load(a.models)
    if rnn is not None:
        pm_v, pr_v = score_rnn(bundle, rnn, val, plots)
        pm_t, pr_t = score_rnn(bundle, rnn, test, plots)
        fuse = lambda w, pm, pr: RNNScorer({}, {}, {"fusion_weight": w}).fuse(pm, pr)  # noqa: E731
        grid = [i / 20 for i in range(21)]
        w = max(grid, key=lambda g: roc_auc_score(yv, fuse(g, pm_v, pr_v)))
        fv, ft = fuse(w, pm_v, pr_v), fuse(w, pm_t, pr_t)
        fhi = float(np.quantile(fv[~yv], 1 - a.blur_fpr))
        flo = min(float(np.quantile(fv[~yv], 1 - a.ask_fpr)), fhi - 0.02)
        lift = paired_ci(yt, pm_t, ft)
        res["fused"] = {"rnn_weight": w, "thr_low": flo, "thr_high": fhi,
                        "auc_test": {"ml_only": float(roc_auc_score(yt, pm_t)), "rnn_only": float(roc_auc_score(yt, pr_t)),
                                     "blend": float(roc_auc_score(yt, ft))},
                        "auc_gain_95ci": list(lift), "validation": report(fv, yv), "test": report(ft, yt)}
        print(f"RNN blend: weight {w:.2f}  thr_low={flo:.3f} thr_high={fhi:.3f}")
        print(f"  test AUC  ML {res['fused']['auc_test']['ml_only']:.4f}   RNN {res['fused']['auc_test']['rnn_only']:.4f}   "
              f"blend {res['fused']['auc_test']['blend']:.4f}   (gain 95% interval {lift[0]:+.4f} .. {lift[1]:+.4f})")
        for k in ("validation", "test"):
            print("  blend", k, {x: round(v, 3) if isinstance(v, float) else v for x, v in res["fused"][k].items()})
        if a.recall:
            res["fused"]["thr_warn"] = warn_level(fv, yv, flo)
            res["fused"]["flagged"] = {"validation": flagged(fv, yv, res["fused"]["thr_warn"]), "test": flagged(ft, yt, res["fused"]["thr_warn"])}
        if w == 0:
            print("  the RNN adds nothing on validation, so the site will use the ML model alone")
    with open(os.path.join(a.models, FILE), "w", encoding="utf-8") as fh:
        json.dump(res, fh, indent=2)
    print(f"thr_low={lo:.3f} thr_high={hi:.3f}")
    if a.recall:
        pick = res["fused"] if (rnn is not None and res["fused"]["rnn_weight"] > 0) else res
        t = pick["flagged"]["test"]
        print(f"\n'possible spoilers' label from {pick['thr_warn']:.3f} (target: flag {a.recall:.0%} of spoiler reviews)")
        print(f"  on films never seen: {t['spoilers_flagged']:.0%} of spoiler reviews flagged (blurred, to moderators or labelled), "
              f"at the price of {t['clean_flagged']:.0%} of clean reviews flagged the same way")
    for k in ("validation", "test"):
        print(k, {x: round(v, 3) if isinstance(v, float) else v for x, v in res[k].items()})
    return res


if __name__ == "__main__":
    main()
