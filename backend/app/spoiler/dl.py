"""Optional deep-learning scorer (retrieval-augmented cross-encoder exported to ONNX).

Trained with ml/train_dl.py on a GPU (free Colab/Kaggle) or CPU; served here with onnxruntime.
Input = review sentence/review  [SEP]  best-matching plot passage. If the files are missing this
module is simply inactive - the shield falls back to the classical model + rules.
"""
from __future__ import annotations

import json
import os
from typing import Optional, Sequence

import numpy as np

ONNX_FILE = "spoiler_dl.onnx"
TOKENIZER_FILE = "spoiler_dl_tokenizer.json"
META_FILE = "spoiler_dl_meta.json"


class DLScorer:
    def __init__(self, session, tokenizer, meta: dict) -> None:
        self.session, self.tokenizer, self.meta = session, tokenizer, meta
        self.thr_low = meta.get("thr_low", 0.35)
        self.thr_high = meta.get("thr_high", 0.6)
        self.max_len = meta.get("max_len", 256)
        self.input_names = {i.name for i in session.get_inputs()}

    @staticmethod
    def load(directory: str) -> Optional["DLScorer"]:
        onnx_path = os.path.join(directory, ONNX_FILE)
        tok_path = os.path.join(directory, TOKENIZER_FILE)
        if not (os.path.exists(onnx_path) and os.path.exists(tok_path)):
            return None
        try:
            import onnxruntime as ort
            from tokenizers import Tokenizer
        except ImportError:
            return None
        meta = {}
        mp = os.path.join(directory, META_FILE)
        if os.path.exists(mp):
            meta = json.load(open(mp))
        so = ort.SessionOptions()
        so.intra_op_num_threads = 2
        sess = ort.InferenceSession(onnx_path, so, providers=["CPUExecutionProvider"])
        tok = Tokenizer.from_file(tok_path)
        tok.enable_truncation(max_length=meta.get("max_len", 256))
        tok.enable_padding()
        return DLScorer(sess, tok, meta)

    def score(self, texts: Sequence[str], passages: Sequence[str]) -> np.ndarray:
        enc = self.tokenizer.encode_batch(list(zip(texts, passages, strict=False)))
        feed = {"input_ids": np.array([e.ids for e in enc], dtype=np.int64),
                "attention_mask": np.array([e.attention_mask for e in enc], dtype=np.int64)}
        if "token_type_ids" in self.input_names:
            feed["token_type_ids"] = np.array([e.type_ids for e in enc], dtype=np.int64)
        logits = self.session.run(None, {k: v for k, v in feed.items() if k in self.input_names})[0]
        if logits.shape[-1] == 2:
            e = np.exp(logits - logits.max(axis=-1, keepdims=True))
            return (e / e.sum(axis=-1, keepdims=True))[:, 1]
        return 1 / (1 + np.exp(-logits.reshape(-1)))
