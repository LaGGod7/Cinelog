"""Recurrent spoiler scorer: bidirectional GRU + attention over the review's words (+ the plot-match features).

Why a recurrent layer next to the linear TF-IDF model: TF-IDF sees isolated words and word pairs; the GRU reads the sentence
in order, and starts from GloVe word vectors, so "she turns out to be the killer" and "the murderer is revealed to be her"
land close together even though they share almost no words. The attention weights say which words drove the decision.

Trained with ml/train_rnn.py (PyTorch). SERVED HERE WITH NUMPY ONLY - no torch, no onnxruntime - so nothing new has to be
installed to run the site. If the files are missing this module is simply inactive.

Files in the models folder:  spoiler_rnn.npz (weights)   spoiler_rnn_vocab.json   spoiler_rnn_meta.json
"""
from __future__ import annotations

import json
import math
import os
import re
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

WEIGHTS_FILE = "spoiler_rnn.npz"
VOCAB_FILE = "spoiler_rnn_vocab.json"
META_FILE = "spoiler_rnn_meta.json"
TOKEN_RE = re.compile(r"[a-z0-9]+(?:'[a-z]+)?|[!?]")
PAD, UNK = 0, 1


def tokenize(text: str) -> List[str]:
    return TOKEN_RE.findall(text.lower())


def _sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(x, -30, 30)))


def logit(p: float) -> float:
    p = min(max(p, 1e-6), 1 - 1e-6)
    return math.log(p / (1 - p))


def _gru_direction(xp: np.ndarray, mask: np.ndarray, w_hh: np.ndarray, b_hh: np.ndarray, reverse: bool) -> np.ndarray:
    """One GRU pass. xp = x @ W_ih.T + b_ih for every step, shape (B, T, 3H); gate order r, z, n (PyTorch's layout).
    Padded steps leave the state untouched, so a reversed pass really starts at each sequence's last word."""
    B, T, H3 = xp.shape
    H = H3 // 3
    h = np.zeros((B, H), dtype=np.float32)
    out = np.zeros((B, T, H), dtype=np.float32)
    steps = range(T - 1, -1, -1) if reverse else range(T)
    for t in steps:
        gh = h @ w_hh.T + b_hh
        xt = xp[:, t]
        r = _sigmoid(xt[:, :H] + gh[:, :H])
        z = _sigmoid(xt[:, H:2 * H] + gh[:, H:2 * H])
        n = np.tanh(xt[:, 2 * H:] + r * gh[:, 2 * H:])
        h_new = (1 - z) * n + z * h
        m = mask[:, t, None]
        h = np.where(m, h_new, h)
        out[:, t] = np.where(m, h_new, 0.0)
    return out


class RNNScorer:
    def __init__(self, weights: Dict[str, np.ndarray], vocab: Dict[str, int], meta: dict) -> None:
        self.w = {k: np.asarray(v, dtype=np.float32) for k, v in weights.items()}
        self.vocab = vocab
        self.meta = meta
        self.max_len = int(meta.get("max_len", 256))
        self.weight = float(meta.get("fusion_weight", 0.5))        # share of the RNN in the fused logit
        self.thr_low = float(meta.get("fused_thr_low", 0.4))        # thresholds of the FUSED probability (ML + RNN)
        self.thr_high = float(meta.get("fused_thr_high", 0.6))
        # The blend is only trusted once ml.tune_shield has measured it against the ML model that is actually deployed
        # (the numbers saved at training time were measured against a different ML model).
        self.tuned = False

    # ---------------------------------------------------------------- loading
    @staticmethod
    def load(directory: str) -> Optional["RNNScorer"]:
        wp, vp = os.path.join(directory, WEIGHTS_FILE), os.path.join(directory, VOCAB_FILE)
        if not (os.path.exists(wp) and os.path.exists(vp)):
            return None
        try:
            with np.load(wp) as z:
                weights = {k: z[k] for k in z.files}
            with open(vp, encoding="utf-8") as fh:
                vocab = json.load(fh)
            meta = {}
            mp = os.path.join(directory, META_FILE)
            if os.path.exists(mp):
                with open(mp, encoding="utf-8") as fh:
                    meta = json.load(fh)
            scorer = RNNScorer(weights, vocab, meta)
            scorer.apply_thresholds(directory)
            return scorer
        except Exception as exc:  # a damaged file must never stop the site from starting
            import logging
            logging.getLogger("cinelog.shield").warning("RNN files could not be loaded (%s): continuing without them", exc)
            return None

    def apply_thresholds(self, directory: str) -> bool:
        """shield_thresholds.json (from ml.tune_shield) holds the fused thresholds and weight tuned with the DEPLOYED ML model."""
        try:
            with open(os.path.join(directory, "shield_thresholds.json"), encoding="utf-8") as fh:
                t = json.load(fh).get("fused")
            if not t:
                return False
            lo, hi, w = float(t["thr_low"]), float(t["thr_high"]), float(t["rnn_weight"])
            if 0 < lo < hi < 1 and 0 <= w <= 1:
                self.thr_low, self.thr_high, self.weight = lo, hi, w
                self.meta = {**self.meta, "thresholds": "tuned", "deployed": {"auc": t.get("auc_test"), "gain_95ci": t.get("auc_gain_95ci")}}
                self.tuned = True
                return True
        except (OSError, ValueError, KeyError, TypeError):
            pass
        return False

    # ---------------------------------------------------------------- inference
    def encode(self, texts: Sequence[str]) -> Tuple[np.ndarray, np.ndarray, List[List[str]]]:
        toks = [tokenize(t)[: self.max_len] or ["."] for t in texts]
        T = max(len(t) for t in toks)
        ids = np.zeros((len(toks), T), dtype=np.int64)
        mask = np.zeros((len(toks), T), dtype=bool)
        for i, t in enumerate(toks):
            ids[i, : len(t)] = [self.vocab.get(w, UNK) for w in t]
            mask[i, : len(t)] = True
        return ids, mask, toks

    def _forward(self, ids: np.ndarray, mask: np.ndarray, dense: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        w = self.w
        x = w["emb"][ids]                                                     # (B, T, D)
        fwd = _gru_direction(x @ w["w_ih_f"].T + w["b_ih_f"], mask, w["w_hh_f"], w["b_hh_f"], False)
        bwd = _gru_direction(x @ w["w_ih_b"].T + w["b_ih_b"], mask, w["w_hh_b"], w["b_hh_b"], True)
        h = np.concatenate([fwd, bwd], axis=-1)                               # (B, T, 2H)
        u = np.tanh(h @ w["att_w"].T + w["att_b"]) @ w["att_v"]               # (B, T)
        u = np.where(mask, u, -1e9)
        a = np.exp(u - u.max(axis=1, keepdims=True)) * mask
        a = a / np.maximum(a.sum(axis=1, keepdims=True), 1e-9)
        ctx = (a[:, :, None] * h).sum(axis=1)
        mx = np.where(mask[:, :, None], h, -1e9).max(axis=1)
        d = (dense - w["dense_mean"]) / w["dense_std"]
        z = np.concatenate([ctx, mx, d], axis=1)
        z = np.maximum(z @ w["fc1_w"].T + w["fc1_b"], 0.0)
        logits = (z @ w["fc2_w"].T + w["fc2_b"]).reshape(-1)
        return logits, a

    def predict(self, texts: Sequence[str], dense: np.ndarray, batch: int = 64) -> np.ndarray:
        """P(spoiler) per text. `dense` = the plot-match features (retrieval.REVIEW_FEATS) of each text, same as the ML model."""
        if not len(texts):
            return np.zeros(0)
        order = np.argsort([len(t) for t in texts])  # similar lengths together: less padding
        out = np.zeros(len(texts))
        for i in range(0, len(texts), batch):
            idx = order[i:i + batch]
            ids, mask, _ = self.encode([texts[j] for j in idx])
            logits, _ = self._forward(ids, mask, np.asarray(dense, dtype=np.float32)[idx])
            out[idx] = _sigmoid(logits)
        return out

    def attention_words(self, text: str, dense: np.ndarray, k: int = 4) -> List[str]:
        """The words the network paid most attention to (a hint for moderators, not a proof)."""
        ids, mask, toks = self.encode([text])
        _, a = self._forward(ids, mask, np.asarray(dense, dtype=np.float32).reshape(1, -1))
        stop = {"the", "a", "an", "and", "of", "to", "is", "was", "it", "in", "that", "this", "i", "he", "she", "his", "her",
                "!", "?", "but", "for", "with", "on", "as", "at", "be", "you", "they", "are", "its", "it's"}
        order = np.argsort(-a[0, : len(toks[0])])
        seen, words = set(), []
        for j in order:
            w = toks[0][int(j)]
            if w not in stop and w not in seen:
                seen.add(w); words.append(w)
            if len(words) >= k:
                break
        return words

    def fuse(self, p_ml: np.ndarray, p_rnn: np.ndarray) -> np.ndarray:
        """Combine the two models in logit space (a weighted average of their log-odds)."""
        zl = np.log(np.clip(p_ml, 1e-6, 1 - 1e-6) / (1 - np.clip(p_ml, 1e-6, 1 - 1e-6)))
        zr = np.log(np.clip(p_rnn, 1e-6, 1 - 1e-6) / (1 - np.clip(p_rnn, 1e-6, 1 - 1e-6)))
        return _sigmoid((1 - self.weight) * zl + self.weight * zr)
