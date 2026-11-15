"""Trained spoiler classifier bundle (TF-IDF text + retrieval features -> logistic regression)."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

import joblib
import numpy as np
from scipy import sparse

from .retrieval import FilmCtx, RetrievalSpace

BUNDLE_FILE = "spoiler_ml.joblib"


def calibrate(p: float, lo: float, hi: float) -> float:
    """Map a raw model probability onto the shield's risk scale: <0.3 show, 0.3-0.7 uncertain, >=0.7 blur."""
    if p <= lo:
        return 0.3 * p / max(lo, 1e-9)
    if p < hi:
        return 0.3 + 0.4 * (p - lo) / max(hi - lo, 1e-9)
    return 0.7 + 0.3 * (p - hi) / max(1 - hi, 1e-9)


@dataclass
class MLBundle:
    text_vec: object                      # TfidfVectorizer over review text
    space: RetrievalSpace                 # hashed retrieval space (also used by RAG at serving time)
    clf: object                           # LogisticRegression
    dense_mean: np.ndarray
    dense_std: np.ndarray
    thr_low: float = 0.35
    thr_high: float = 0.6
    meta: Dict = field(default_factory=dict)

    # ---- features
    def matrix(self, texts: Sequence[str], dense: np.ndarray) -> sparse.csr_matrix:
        d = (dense - self.dense_mean) / self.dense_std
        return sparse.hstack([self.text_vec.transform(texts), sparse.csr_matrix(d)], format="csr")

    def predict(self, texts: Sequence[str], dense: np.ndarray) -> np.ndarray:
        return self.clf.predict_proba(self.matrix(texts, dense))[:, 1]

    def predict_one(self, text: str, ctx: FilmCtx) -> float:
        dense = self.space.review_features(text, ctx).reshape(1, -1)
        return float(self.predict([text], dense)[0])

    def predict_sentences(self, sentences: Sequence[str], ctx: FilmCtx) -> np.ndarray:
        if not sentences:
            return np.zeros(0)
        dense = np.vstack([self.space.review_features(s, ctx) for s in sentences])
        return self.predict(list(sentences), dense)

    def _feature_names(self) -> np.ndarray:
        """sklearn rebuilds this ~300k-word array on every call (0.5 s); build it once."""
        names = self.__dict__.get("_names")
        if names is None:
            names = self.text_vec.get_feature_names_out()
            self.__dict__["_names"] = names
        return names

    def __getstate__(self):
        d = dict(self.__dict__)
        d.pop("_names", None)  # derived; keeps the saved bundle small
        return d

    def top_words(self, text: str, k: int = 5) -> List[str]:
        """Words that pushed the score up the most (linear model => directly explainable)."""
        X = self.text_vec.transform([text])
        n_text = X.shape[1]
        coefs = self.clf.coef_[0][:n_text]
        contrib = X.multiply(coefs).tocoo()
        names = self._feature_names()
        pairs = sorted(zip(contrib.data, contrib.col, strict=False), reverse=True)[:k]
        return [str(names[c]) for v, c in pairs if v > 0]

    # ---- persistence
    def save(self, directory: str) -> str:
        os.makedirs(directory, exist_ok=True)
        path = os.path.join(directory, BUNDLE_FILE)
        joblib.dump(self, path, compress=3)
        return path

    @staticmethod
    def load(directory: str) -> Optional["MLBundle"]:
        path = os.path.join(directory, BUNDLE_FILE)
        if not os.path.exists(path):
            return None
        bundle = joblib.load(path)  # only load files you trained yourself (pickle)
        bundle.apply_thresholds(directory)
        return bundle

    def apply_thresholds(self, directory: str) -> bool:
        """models/shield_thresholds.json (from ml.tune_shield) overrides the thresholds saved with the model."""
        try:
            with open(os.path.join(directory, "shield_thresholds.json"), encoding="utf-8") as fh:
                t = json.load(fh)
            lo, hi = float(t["thr_low"]), float(t["thr_high"])
            if 0 < lo < hi < 1:
                self.thr_low, self.thr_high = lo, hi
                self.meta = {**self.meta, "thresholds": "tuned"}
                return True
        except (OSError, ValueError, KeyError, TypeError):
            pass
        return False
