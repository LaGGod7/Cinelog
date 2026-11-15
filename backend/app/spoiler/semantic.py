"""Semantic plot matching: does a review sentence say what happens LATE in the film's plot, in any words?

The word-based layers (TF-IDF plot match, word lists, the trained model) miss spoilers that are reworded ("the guy on the poster does
not make it to the credits"). This layer embeds every review sentence and every plot sentence with a small public sentence encoder
(all-MiniLM-L6-v2, int8 ONNX, 23 MB; a classifier of meaning, not a text generator) and compares them by cosine similarity.
Only the SECOND HALF of the plot counts as spoiler territory: matching the first half is usually just a premise recap, which measured
as no signal at all (AUC 0.49) while matching the second half scored AUC 0.77-0.80 on the stress set.

Files in <models>/semantic/:  model.onnx  tokenizer.json  meta.json  (meta holds the cut-offs from ml.calibrate_semantic).
Needs `onnxruntime` and `tokenizers`; if either the files or the packages are missing this layer is simply off.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from typing import List, Optional, Sequence, Tuple

import numpy as np

from .text import split_sentences

log = logging.getLogger("cinelog.semantic")
EARLY_WEIGHT = 0.5          # score = similarity to the late plot - EARLY_WEIGHT * similarity to the early plot (a premise recap matches both)


def plot_sentences(passages: Sequence[str]) -> List[str]:
    """The film's plot as single sentences, in order (passages are overlapping 2-sentence windows, so repeats are dropped)."""
    seen, out = set(), []
    for p in passages:
        for s, e in split_sentences(p):
            x = p[s:e].strip()
            if x and x not in seen:
                seen.add(x)
                out.append(x)
    return out


class SemanticMatcher:
    def __init__(self, session, tokenizer, meta: dict) -> None:
        self.session, self.tokenizer, self.meta = session, tokenizer, meta
        self.thr_blur = float(meta.get("thr_blur", 0.45))
        self.thr_warn = float(meta.get("thr_warn", 0.33))
        self.max_len = int(meta.get("max_len", 96))
        # (tail probability, score) pairs measured on sentences of real clean reviews, rarest last (from ml.calibrate_semantic).
        # A long review has more sentences that can match by chance, so its cut-off must be higher: see blur_threshold().
        tail = meta.get("sentence_tail") or {}
        self._tail_p = np.array(tail.get("p") or [], dtype=float)
        self._tail_s = np.array(tail.get("score") or [], dtype=float)
        self.blur_fpr = float(meta.get("blur_fpr", 0.03))
        self.warn_fpr = float(meta.get("warn_fpr", 0.10))
        self._names = {i.name for i in session.get_inputs()}
        self._lock = threading.Lock()           # one ONNX session; scans run on a few worker threads

    @staticmethod
    def load(directory: str) -> Optional["SemanticMatcher"]:
        d = os.path.join(directory, "semantic")
        mp, tp, jp = os.path.join(d, "model.onnx"), os.path.join(d, "tokenizer.json"), os.path.join(d, "meta.json")
        if not (os.path.exists(mp) and os.path.exists(tp)):
            return None
        try:
            import onnxruntime as ort
            from tokenizers import Tokenizer
        except ImportError:
            log.info("semantic layer off: onnxruntime/tokenizers are not installed (pip install onnxruntime tokenizers)")
            return None
        try:
            meta = json.load(open(jp, encoding="utf-8")) if os.path.exists(jp) else {}
            tok = Tokenizer.from_file(tp)
            tok.enable_padding()
            tok.enable_truncation(int(meta.get("max_len", 96)))
            so = ort.SessionOptions()
            so.intra_op_num_threads = 2
            return SemanticMatcher(ort.InferenceSession(mp, so, providers=["CPUExecutionProvider"]), tok, meta)
        except Exception as exc:  # noqa: BLE001 - a damaged model file must never stop the site from starting
            log.warning("semantic layer could not be loaded (%s): continuing without it", exc)
            return None

    def _threshold(self, n_sentences: int, fpr: float, floor: float) -> float:
        """Cut-off that keeps the share of clean REVIEWS over it near `fpr` whatever the review's length.

        thr_blur / thr_warn were measured on short reviews (<= 6 sentences). A review with n sentences gets n tries, so each
        sentence may only pass with probability 1 - (1 - fpr)^(1/n); the matching score is read from the clean-sentence tail table.
        Never lower than the short-review cut-off; without a table (old meta.json) the flat cut-off is used."""
        tail_p, tail_s = getattr(self, "_tail_p", ()), getattr(self, "_tail_s", ())
        if n_sentences <= 1 or len(tail_p) < 2:
            return floor
        q = 1.0 - (1.0 - fpr) ** (1.0 / n_sentences)
        q = min(max(q, float(np.min(tail_p))), float(np.max(tail_p)))
        # the table is sorted by falling probability; interpolate on log(p)
        score = float(np.interp(-np.log(q), -np.log(tail_p), tail_s))
        return max(floor, score)

    def blur_threshold(self, n_sentences: int) -> float:
        return self._threshold(n_sentences, getattr(self, "blur_fpr", 0.03), self.thr_blur)

    def warn_threshold(self, n_sentences: int) -> float:
        return min(self._threshold(n_sentences, getattr(self, "warn_fpr", 0.10), self.thr_warn), self.blur_threshold(n_sentences))

    def embed(self, texts: Sequence[str], batch: int = 32) -> np.ndarray:
        """Unit-length sentence vectors (mean pooling), shape (len(texts), D)."""
        if not len(texts):
            return np.zeros((0, 1), dtype=np.float32)
        order = np.argsort([len(t) for t in texts])
        out = [None] * len(texts)
        with self._lock:
            for i in range(0, len(texts), batch):
                idx = order[i:i + batch]
                enc = self.tokenizer.encode_batch([texts[j] for j in idx])
                ids = np.array([e.ids for e in enc], dtype=np.int64)
                mask = np.array([e.attention_mask for e in enc], dtype=np.int64)
                feed = {"input_ids": ids, "attention_mask": mask}
                if "token_type_ids" in self._names:
                    feed["token_type_ids"] = np.zeros_like(ids)
                h = self.session.run(None, feed)[0]
                v = (h * mask[..., None]).sum(1) / np.maximum(mask.sum(1, keepdims=True), 1)
                v = v / np.maximum(np.linalg.norm(v, axis=1, keepdims=True), 1e-9)
                for k, j in enumerate(idx):
                    out[j] = v[k]
        return np.vstack(out).astype(np.float32)

    def plot_matrix(self, passages: Sequence[str]) -> Tuple[np.ndarray, np.ndarray]:
        """(vectors of the plot's sentences, relative position 0..1 of each)."""
        sents = plot_sentences(passages)
        if not sents:
            return np.zeros((0, 1), dtype=np.float32), np.zeros(0)
        n = len(sents)
        return self.embed(sents), np.array([i / max(n - 1, 1) for i in range(n)])

    def scores(self, sentences: Sequence[str], plot: Tuple[np.ndarray, np.ndarray]) -> np.ndarray:
        """Per review sentence: similarity to the late plot minus half the similarity to the early plot."""
        P, pos = plot
        if not len(sentences) or not len(P):
            return np.zeros(len(sentences))
        late_mask = pos >= 0.5
        if not late_mask.any():      # a one-sentence plot is a premise: there is no late part to give away
            return np.zeros(len(sentences))
        C = self.embed(sentences) @ P.T
        late = C[:, late_mask].max(axis=1)
        early = C[:, ~late_mask].max(axis=1) if (~late_mask).any() else np.zeros(len(C))
        return late - EARLY_WEIGHT * early
