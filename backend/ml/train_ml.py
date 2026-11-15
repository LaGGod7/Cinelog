"""Train the spoiler classifier on the Kaggle 'IMDB Spoiler Dataset' (reviews + plot synopses).

    python -m ml.train_ml --reviews IMDB_reviews.json --movies IMDB_movie_details.json --out models

Split is by MOVIE (train/val/test 80/10/10) so the test score is on films the model never saw - like new films
arriving from TMDB. Writes models/spoiler_ml.joblib and models/metrics.json (with ablations).
"""
from __future__ import annotations

import argparse
import json
import os
import time
from typing import Dict

import numpy as np
import pandas as pd
from scipy import sparse
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, f1_score, roc_auc_score, roc_curve

from app.spoiler.ml import MLBundle
from app.spoiler.retrieval import REVIEW_FEATS, RetrievalSpace, make_passages


def read_jsonl(path: str, keep=None) -> pd.DataFrame:
    """Read a JSON-lines file in chunks (the Kaggle reviews file is ~1 GB); keep only the columns we need."""
    parts = []
    for chunk in pd.read_json(path, lines=True, chunksize=50000):
        parts.append(chunk[keep] if keep else chunk)
    return pd.concat(parts, ignore_index=True)


def load(reviews_path: str, movies_path: str, max_reviews: int | None, seed: int):
    movies = read_jsonl(movies_path)
    reviews = read_jsonl(reviews_path, keep=["movie_id", "is_spoiler", "review_text"])
    reviews = reviews[reviews["review_text"].fillna("").str.len() >= 20]
    reviews["is_spoiler"] = reviews["is_spoiler"].astype(int)
    if max_reviews and len(reviews) > max_reviews:
        reviews = reviews.sample(max_reviews, random_state=seed)
    plots: Dict[str, str] = {}
    for _, m in movies.iterrows():
        txt = (m.get("plot_synopsis") or "").strip() or (m.get("plot_summary") or "").strip()
        plots[m["movie_id"]] = txt
    return reviews.reset_index(drop=True), plots


def split_by_movie(reviews: pd.DataFrame, seed: int, all_ids=None):
    """80/10/10 by movie. Pass all_ids (every movie in IMDB_movie_details.json, i.e. plots.keys()) so the split does not
    change when a sample of the reviews is used instead of the full file - otherwise a sample's 'test' films can be
    training films of the model."""
    ids = np.array(sorted(set(all_ids) if all_ids is not None else reviews["movie_id"].unique()))
    rng = np.random.RandomState(seed)
    rng.shuffle(ids)
    n = len(ids)
    val_ids, test_ids = set(ids[: n // 10]), set(ids[n // 10: n // 5])
    split = np.where(reviews["movie_id"].isin(test_ids), "test", np.where(reviews["movie_id"].isin(val_ids), "val", "train"))
    return split


def recall_at_fpr(y, p, fpr_cap: float):
    fpr, tpr, thr = roc_curve(y, p)
    ok = np.flatnonzero(fpr <= fpr_cap)
    i = ok[-1] if len(ok) else 0
    return float(tpr[i]), float(thr[i])


def metrics(y, p, thr_high) -> Dict[str, float]:
    rec10, _ = recall_at_fpr(y, p, 0.10)
    pred = p >= thr_high
    return {"roc_auc": float(roc_auc_score(y, p)), "pr_auc": float(average_precision_score(y, p)),
            "recall_at_10pct_false_blur": rec10, "f1_at_thr_high": float(f1_score(y, pred)),
            "caught": float(pred[y == 1].mean()), "wrongly_blurred": float(pred[y == 0].mean()),
            "n": int(len(y)), "pos_rate": float(np.mean(y))}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--reviews", required=True)
    ap.add_argument("--movies", required=True)
    ap.add_argument("--out", default="models")
    ap.add_argument("--max-reviews", type=int, default=None, help="subsample for a quick run, e.g. 100000")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--C", type=float, default=2.0)
    ap.add_argument("--max-features", type=int, default=300000)
    ap.add_argument("--min-df", type=int, default=3)
    a = ap.parse_args(argv)
    t0 = time.time()

    reviews, plots = load(a.reviews, a.movies, a.max_reviews, a.seed)
    split = split_by_movie(reviews, a.seed, plots.keys())
    reviews["split"] = split
    print(f"{len(reviews)} reviews, {reviews['movie_id'].nunique()} movies, "
          f"{reviews['is_spoiler'].mean():.1%} spoiler; train/val/test = "
          f"{(split=='train').sum()}/{(split=='val').sum()}/{(split=='test').sum()}")

    # --- retrieval space: fit idf on TRAIN movies' plots only (no peeking at test films)
    train_movies = set(reviews.loc[reviews.split == "train", "movie_id"])
    space = RetrievalSpace().fit([p for mid in train_movies for p in make_passages(plots.get(mid, ""))])

    # --- dense retrieval features, batched per movie
    dense = np.zeros((len(reviews), len(REVIEW_FEATS)), dtype=np.float32)
    for mid, grp in reviews.groupby("movie_id"):
        ctx = space.film_ctx(make_passages(plots.get(mid, "")))
        dense[grp.index.values] = space.reviews_features(grp["review_text"].tolist(), ctx)
    print(f"features done in {time.time()-t0:.0f}s")

    tr, va, te = (reviews.split == s for s in ("train", "val", "test"))
    y = reviews["is_spoiler"].values
    texts = reviews["review_text"].values
    mean, std = dense[tr.values].mean(axis=0), dense[tr.values].std(axis=0) + 1e-6

    vec = TfidfVectorizer(ngram_range=(1, 2), min_df=a.min_df, max_features=a.max_features, sublinear_tf=True,
                          strip_accents="unicode")
    Xt = vec.fit_transform(texts[tr.values])
    D = lambda mask: sparse.csr_matrix((dense[mask.values] - mean) / std)  # noqa: E731
    X = {"train": sparse.hstack([Xt, D(tr)], format="csr"),
         "val": sparse.hstack([vec.transform(texts[va.values]), D(va)], format="csr"),
         "test": sparse.hstack([vec.transform(texts[te.values]), D(te)], format="csr")}
    ys = {"train": y[tr.values], "val": y[va.values], "test": y[te.values]}

    def fit(Xtr):
        return LogisticRegression(C=a.C, class_weight="balanced", max_iter=300, solver="liblinear").fit(Xtr, ys["train"])

    clf = fit(X["train"])
    p_val = clf.predict_proba(X["val"])[:, 1]
    _, thr_high = recall_at_fpr(ys["val"], p_val, 0.10)
    _, thr_low = recall_at_fpr(ys["val"], p_val, 0.35)
    thr_low = min(thr_low, thr_high - 0.02)

    report = {"full_text+retrieval": metrics(ys["test"], clf.predict_proba(X["test"])[:, 1], thr_high)}
    # ablations (same thresholds logic on val) - answers "what does RAG add?"
    n_text = Xt.shape[1]
    for name, cols in (("text_only", slice(0, n_text)), ("retrieval_only", slice(n_text, None))):
        m = fit(X["train"][:, cols])
        pv = m.predict_proba(X["val"][:, cols])[:, 1]
        _, th = recall_at_fpr(ys["val"], pv, 0.10)
        report[name] = metrics(ys["test"], m.predict_proba(X["test"][:, cols])[:, 1], th)
    for k, v in report.items():
        print(f"{k:22s} AUC={v['roc_auc']:.3f} PR-AUC={v['pr_auc']:.3f} "
              f"recall@10%FPR={v['recall_at_10pct_false_blur']:.3f} caught={v['caught']:.3f} wrong={v['wrongly_blurred']:.3f}")

    meta = {"trained_on": os.path.basename(a.reviews), "n_reviews": int(len(reviews)), "thr_low": float(thr_low),
            "thr_high": float(thr_high), "test": report["full_text+retrieval"], "seconds": round(time.time() - t0)}
    bundle = MLBundle(vec, space, clf, mean, std, float(thr_low), float(thr_high), meta)
    path = bundle.save(a.out)
    json.dump({"meta": meta, "ablation": report}, open(os.path.join(a.out, "metrics.json"), "w"), indent=2)
    print("saved", path)
    return report


if __name__ == "__main__":
    main()
