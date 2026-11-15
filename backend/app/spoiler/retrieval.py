"""RAG retrieval space: find the plot / confirmed-spoiler passages a review sentence is closest to.

No generation - retrieval only. Uses a hashed TF-IDF space so words never seen at fit time (new films,
fresh character names) still land in a bucket and count as *rare* (maximum idf).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence

import numpy as np
from scipy import sparse
from sklearn.feature_extraction.text import HashingVectorizer, TfidfTransformer

from .text import split_sentences

N_FEATURES = 2 ** 18
SENT_FEATS = ["max_plot", "top3_plot", "max_spoiler", "rare_overlap", "rare_frac"]
REVIEW_FEATS = ["max_plot", "top3_plot", "max_spoiler", "rare_overlap", "rare_frac", "mean_plot", "frac_hot",
                "log_sents", "log_words", "has_plot"]


def make_hasher() -> HashingVectorizer:
    return HashingVectorizer(n_features=N_FEATURES, alternate_sign=False, norm=None, lowercase=True,
                             stop_words="english", token_pattern=r"(?u)\b[a-zA-Z][a-zA-Z']{2,}\b",
                             dtype=np.float32)


def make_passages(text: str, window: int = 2) -> List[str]:
    """Sliding windows of `window` sentences over a plot text."""
    sp = split_sentences(text)
    sents = [text[s:e] for s, e in sp]
    if len(sents) <= window:
        return [" ".join(sents)] if sents else []
    return [" ".join(sents[i:i + window]) for i in range(len(sents) - window + 1)]


@dataclass
class FilmCtx:
    plot: Optional[sparse.csr_matrix]          # passages x D (l2-normalised tf-idf)
    spoiler: Optional[sparse.csr_matrix]
    plot_rare: Optional[sparse.csr_matrix]     # 1 x D binary: rare buckets present in this film's plot
    n_plot: int = 0


class RetrievalSpace:
    def __init__(self) -> None:
        self.hasher = make_hasher()
        self.tfidf = TfidfTransformer(sublinear_tf=True)
        self.rare_mask: Optional[sparse.csr_matrix] = None
        self.fitted = False

    # ---- fitting
    def fit(self, passages: Iterable[str]) -> "RetrievalSpace":
        passages = [p for p in passages if p and p.strip()]
        if not passages:
            passages = ["placeholder context"]
        counts = self.hasher.transform(passages)
        self.tfidf.fit(counts)
        n = counts.shape[0]
        idf = self.tfidf.idf_
        df_cut = max(2.0, 0.01 * n)
        thr = math.log((1 + n) / (1 + df_cut)) + 1
        self.rare_mask = sparse.csr_matrix((idf >= thr - 1e-9).astype(np.float32).reshape(1, -1))
        self.fitted = True
        return self

    def vec(self, texts: Sequence[str]) -> sparse.csr_matrix:
        return self.tfidf.transform(self.hasher.transform(list(texts)))

    # ---- contexts
    def film_ctx(self, plot_passages: Sequence[str], spoiler_passages: Sequence[str] = ()) -> FilmCtx:
        plot = self.vec(plot_passages) if plot_passages else None
        spoil = self.vec(spoiler_passages) if spoiler_passages else None
        plot_rare = None
        if plot is not None:
            binary = (plot > 0).astype(np.float32).sum(axis=0)
            binary = sparse.csr_matrix((np.asarray(binary) > 0).astype(np.float32))
            plot_rare = binary.multiply(self.rare_mask).tocsr()
        return FilmCtx(plot, spoil, plot_rare, plot.shape[0] if plot is not None else 0)

    # ---- features
    def sentence_features(self, sentences: Sequence[str], ctx: FilmCtx) -> np.ndarray:
        n = len(sentences)
        out = np.zeros((n, len(SENT_FEATS)), dtype=np.float32)
        if n == 0:
            return out
        S = self.vec(sentences)
        if ctx.plot is not None:
            cos = (S @ ctx.plot.T).toarray()
            srt = np.sort(cos, axis=1)[:, ::-1]
            out[:, 0] = srt[:, 0]
            out[:, 1] = srt[:, :3].mean(axis=1)
        if ctx.spoiler is not None:
            out[:, 2] = (S @ ctx.spoiler.T).toarray().max(axis=1)
        sb = (S > 0).astype(np.float32)
        sbr = sb.multiply(self.rare_mask).tocsr()
        rare_total = np.asarray(sbr.sum(axis=1)).ravel()
        if ctx.plot_rare is not None:
            out[:, 3] = np.asarray((sbr @ ctx.plot_rare.T).todense()).ravel()
        out[:, 4] = np.where(rare_total > 0, out[:, 3] / np.maximum(rare_total, 1), 0.0)
        return out

    @staticmethod
    def aggregate(sent: np.ndarray, n_words: int, has_plot: bool) -> np.ndarray:
        """Review-level dense features from per-sentence features."""
        if sent.shape[0] == 0:
            return np.zeros(len(REVIEW_FEATS), dtype=np.float32)
        return np.array([*sent.max(axis=0), sent[:, 0].mean(), float((sent[:, 0] > 0.25).mean()),
                         math.log1p(sent.shape[0]), math.log1p(n_words), 1.0 if has_plot else 0.0],
                        dtype=np.float32)

    def review_features(self, text: str, ctx: FilmCtx) -> np.ndarray:
        return self.reviews_features([text], ctx)[0]

    def reviews_features(self, texts: Sequence[str], ctx: FilmCtx) -> np.ndarray:
        """Batch version (one hashing call for all sentences of all reviews of a film) - used by training too."""
        sents: List[str] = []
        owner: List[int] = []
        for i, t in enumerate(texts):
            for s, e in split_sentences(t):
                sents.append(t[s:e]); owner.append(i)
        feats = self.sentence_features(sents, ctx)
        owner_arr = np.array(owner, dtype=np.int64)
        out = np.zeros((len(texts), len(REVIEW_FEATS)), dtype=np.float32)
        for i, t in enumerate(texts):
            idx = np.flatnonzero(owner_arr == i) if len(owner_arr) else np.array([], dtype=np.int64)
            out[i] = self.aggregate(feats[idx], len(t.split()), ctx.plot is not None)
        return out
