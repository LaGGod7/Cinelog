"""Train the recurrent spoiler model (bidirectional GRU + attention, GloVe word vectors, plot-match features).

    python -m ml.train_rnn --reviews ..\\mltraining\\sample_reviews.json --movies ..\\mltraining\\IMDB_movie_details.json --out models

Needs PyTorch to TRAIN (CPU is fine, ~10-25 min for 150k reviews; the site itself never needs torch):
    pip install torch --index-url https://download.pytorch.org/whl/cpu

The first run downloads GloVe 6B 100-d (public domain, 134 MB, from the gensim-data GitHub release) next to the data.
Same movie split as ml.train_ml (80/10/10 BY MOVIE), so the scores are on films the model never saw.
Writes models/spoiler_rnn.npz, spoiler_rnn_vocab.json, spoiler_rnn_meta.json - the API picks them up on start.
It also trains the TF-IDF baseline on the same split and reports both and the blend, so you can see what the RNN adds.
Afterwards run tune_shield.bat: it tunes the blend weight and thresholds against the ML model the site actually uses.
"""
from __future__ import annotations

import argparse
import collections
import gzip
import json
import os
import time
import urllib.request
from typing import Dict, Optional

import numpy as np
from scipy import sparse
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, roc_auc_score

from app.spoiler.ml import MLBundle
from app.spoiler.retrieval import REVIEW_FEATS, RetrievalSpace, make_passages
from app.spoiler.rnn import META_FILE, PAD, UNK, VOCAB_FILE, WEIGHTS_FILE, tokenize
from ml.train_ml import load, recall_at_fpr, split_by_movie

GLOVE_URL = "https://github.com/RaRe-Technologies/gensim-data/releases/download/glove-wiki-gigaword-100/glove-wiki-gigaword-100.gz"


# ------------------------------------------------------------------ data
def get_glove(path: Optional[str], wanted: set) -> Dict[str, np.ndarray]:
    """GloVe vectors for the words in `wanted` only (the 400k-word file is streamed, not kept in memory)."""
    if not path:
        path = os.path.join(os.path.expanduser("~"), ".cache", "cinelog", "glove-wiki-gigaword-100.gz")
    if not os.path.exists(path):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        print(f"downloading GloVe vectors (134 MB) to {path} ...", flush=True)
        urllib.request.urlretrieve(GLOVE_URL, path)
    vecs = {}
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        for line in fh:
            w, _, rest = line.partition(" ")
            if w in wanted:
                vecs[w] = np.asarray(rest.split(), dtype=np.float32)
    return vecs


def build_vocab(texts, min_count: int, max_size: int) -> Dict[str, int]:
    c = collections.Counter(w for t in texts for w in tokenize(t))
    words = [w for w, n in c.most_common(max_size) if n >= min_count]
    vocab = {"<pad>": PAD, "<unk>": UNK}
    for w in words:
        vocab[w] = len(vocab)
    return vocab


def encode(texts, vocab, max_len):
    out = []
    for t in texts:
        ids = [vocab.get(w, UNK) for w in tokenize(t)[:max_len]]
        out.append(np.asarray(ids or [UNK], dtype=np.int64))
    return out


def dense_features(reviews, plots, space: RetrievalSpace) -> np.ndarray:
    d = np.zeros((len(reviews), len(REVIEW_FEATS)), dtype=np.float32)
    for mid, grp in reviews.groupby("movie_id"):
        ctx = space.film_ctx(make_passages(plots.get(mid, "")))
        d[grp.index.values] = space.reviews_features(grp["review_text"].tolist(), ctx)
    return d


# ------------------------------------------------------------------ model
def make_net(vocab_size, emb_dim, hidden, n_dense, emb_matrix=None, dropout=0.35):
    import torch
    from torch import nn

    class Net(nn.Module):
        def __init__(self):
            super().__init__()
            self.emb = nn.Embedding(vocab_size, emb_dim, padding_idx=PAD)
            if emb_matrix is not None:
                self.emb.weight.data.copy_(torch.from_numpy(emb_matrix))
            self.drop = nn.Dropout(dropout)
            self.gru = nn.GRU(emb_dim, hidden, batch_first=True, bidirectional=True)
            self.att = nn.Linear(2 * hidden, 2 * hidden)
            self.att_v = nn.Linear(2 * hidden, 1, bias=False)
            self.fc1 = nn.Linear(4 * hidden + n_dense, 64)
            self.fc2 = nn.Linear(64, 1)
            self.n_dense = n_dense

        def forward(self, ids, lengths, dense):
            mask = ids != PAD
            x = self.drop(self.emb(ids))
            packed = nn.utils.rnn.pack_padded_sequence(x, lengths.cpu(), batch_first=True, enforce_sorted=False)
            h, _ = self.gru(packed)
            h, _ = nn.utils.rnn.pad_packed_sequence(h, batch_first=True, total_length=ids.shape[1])
            u = self.att_v(torch.tanh(self.att(h))).squeeze(-1).masked_fill(~mask, -1e9)
            a = torch.softmax(u, dim=1) * mask
            a = a / a.sum(dim=1, keepdim=True).clamp_min(1e-9)
            ctx = (a.unsqueeze(-1) * h).sum(dim=1)
            mx = h.masked_fill(~mask.unsqueeze(-1), -1e9).max(dim=1).values
            z = torch.cat([ctx, mx, dense], dim=1)
            z = self.drop(torch.relu(self.fc1(self.drop(z))))
            return self.fc2(z).squeeze(-1)

    return Net()


DEV = "cpu"   # set to 'cuda' in main() when a GPU is present


def batches(seqs, order, batch):
    """Mini-batches of similar-length reviews (much less padding => much faster on a CPU)."""
    chunk = batch * 50
    out = []
    for i in range(0, len(order), chunk):
        part = sorted(order[i:i + chunk], key=lambda j: len(seqs[j]))
        out += [part[k:k + batch] for k in range(0, len(part), batch)]
    return out


def pad(seqs, idx):
    import torch
    L = max(len(seqs[j]) for j in idx)
    ids = np.zeros((len(idx), L), dtype=np.int64)
    for r, j in enumerate(idx):
        ids[r, : len(seqs[j])] = seqs[j]
    lens = np.array([len(seqs[j]) for j in idx])
    return torch.from_numpy(ids), torch.from_numpy(lens)


def predict(net, seqs, dense, batch=128):
    import torch
    net.eval()
    out = np.zeros(len(seqs))
    order = sorted(range(len(seqs)), key=lambda j: len(seqs[j]))
    with torch.no_grad():
        for i in range(0, len(order), batch):
            idx = order[i:i + batch]
            ids, lens = pad(seqs, idx)
            out[idx] = torch.sigmoid(net(ids.to(DEV), lens, torch.from_numpy(dense[idx]).to(DEV))).cpu().numpy()
    return out


# ------------------------------------------------------------------ baseline + blend
def fit_tfidf_baseline(texts, dense, y, masks, C=2.0):
    """The same recipe as ml.train_ml (TF-IDF 1-2-grams + plot features -> logistic regression), on the same split."""
    tr, va, te = masks
    mean, std = dense[tr].mean(axis=0), dense[tr].std(axis=0) + 1e-6
    vec = TfidfVectorizer(ngram_range=(1, 2), min_df=3, max_features=300000, sublinear_tf=True, strip_accents="unicode")
    Xt = vec.fit_transform(texts[tr])

    def X(m, fit=False):
        t = Xt if fit else vec.transform(texts[m])
        return sparse.hstack([t, sparse.csr_matrix((dense[m] - mean) / std)], format="csr")
    clf = LogisticRegression(C=C, class_weight="balanced", max_iter=300, solver="liblinear").fit(X(tr, True), y[tr])
    return clf.predict_proba(X(va))[:, 1], clf.predict_proba(X(te))[:, 1]


def _z(p):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


def blend(p_ml, p_rnn, w):
    return 1 / (1 + np.exp(-((1 - w) * _z(p_ml) + w * _z(p_rnn))))


def score(y, p):
    return {"roc_auc": float(roc_auc_score(y, p)), "pr_auc": float(average_precision_score(y, p)),
            "recall_at_10pct_false_blur": float(recall_at_fpr(y, p, 0.10)[0])}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--reviews", required=True)
    ap.add_argument("--movies", required=True)
    ap.add_argument("--out", default="models")
    ap.add_argument("--glove", default=None, help="path to glove-wiki-gigaword-100.gz (downloaded automatically if omitted)")
    ap.add_argument("--max-reviews", type=int, default=None)
    ap.add_argument("--epochs", type=int, default=4)
    ap.add_argument("--hidden", type=int, default=96)
    ap.add_argument("--max-len", type=int, default=256)
    ap.add_argument("--batch", type=int, default=64)
    ap.add_argument("--lr", type=float, default=2e-3)
    ap.add_argument("--word-dropout", type=float, default=0.1)
    ap.add_argument("--min-count", type=int, default=3)
    ap.add_argument("--max-vocab", type=int, default=60000)
    ap.add_argument("--no-dense", action="store_true", help="ablation: text only, without the plot-match features")
    ap.add_argument("--cpu", action="store_true", help="do not use the GPU even if there is one")
    ap.add_argument("--no-save", action="store_true", help="experiment only: do not write model files")
    ap.add_argument("--threads", type=int, default=0)
    ap.add_argument("--seed", type=int, default=42)
    a = ap.parse_args(argv)

    import torch
    global DEV
    DEV = "cuda" if (torch.cuda.is_available() and not a.cpu) else "cpu"
    print("training on", DEV, flush=True)
    torch.manual_seed(a.seed)
    if a.threads:
        torch.set_num_threads(a.threads)
    rng = np.random.RandomState(a.seed)
    t0 = time.time()

    reviews, plots = load(a.reviews, a.movies, a.max_reviews, a.seed)
    split = split_by_movie(reviews, a.seed, plots.keys())
    masks = tuple((split == s) for s in ("train", "val", "test"))
    tr, va, te = masks
    y = reviews["is_spoiler"].to_numpy().astype(np.float32)
    texts = reviews["review_text"].to_numpy()
    print(f"{len(reviews)} reviews; train/val/test = {tr.sum()}/{va.sum()}/{te.sum()}; {y.mean():.1%} spoiler", flush=True)

    # plot-match features: use the retrieval space of the ML model the site runs (so serving sees the same numbers)
    ml = MLBundle.load(a.out) if os.path.isdir(a.out) else None
    if ml is not None:
        space = ml.space
        print("plot features: using the retrieval space of the ML model in", a.out, flush=True)
    else:
        train_movies = set(reviews.loc[tr, "movie_id"])
        space = RetrievalSpace().fit([p for m in train_movies for p in make_passages(plots.get(m, ""))])
    dense = dense_features(reviews, plots, space)
    if a.no_dense:
        dense = np.zeros_like(dense)
    mean, std = dense[tr].mean(axis=0), dense[tr].std(axis=0) + 1e-6
    dn = ((dense - mean) / std).astype(np.float32)
    print(f"plot features done ({time.time() - t0:.0f}s)", flush=True)

    vocab = build_vocab(texts[tr], a.min_count, a.max_vocab)
    glove = get_glove(a.glove, set(vocab))
    emb = np.random.RandomState(a.seed).normal(0, 0.1, (len(vocab), 100)).astype(np.float32)
    emb[PAD] = 0
    for w, i in vocab.items():
        if w in glove:
            emb[i] = glove[w]
    cover = sum(w in glove for w in vocab) / len(vocab)
    print(f"vocabulary {len(vocab)} words, {cover:.0%} have GloVe vectors", flush=True)
    seqs = encode(texts, vocab, a.max_len)

    net = make_net(len(vocab), 100, a.hidden, dn.shape[1], emb).to(DEV)
    emb_params = list(net.emb.parameters())
    other = [p for p in net.parameters() if all(p is not q for q in emb_params)]
    opt = torch.optim.AdamW([{"params": other, "lr": a.lr}, {"params": emb_params, "lr": a.lr * 0.25}], weight_decay=1e-2)
    pos = float(y[tr].mean())
    loss_fn = torch.nn.BCEWithLogitsLoss(pos_weight=torch.tensor((1 - pos) / pos, device=DEV))
    train_idx = np.flatnonzero(tr)
    steps = a.epochs * ((len(train_idx) + a.batch - 1) // a.batch)
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=[a.lr, a.lr * 0.25], total_steps=steps, pct_start=0.15)
    best_auc, best_state, step, t1 = -1.0, None, 0, time.time()
    va_idx, te_idx = np.flatnonzero(va), np.flatnonzero(te)
    for ep in range(a.epochs):
        net.train()
        order = list(rng.permutation(train_idx))
        bl = batches(seqs, order, a.batch)
        rng.shuffle(bl)
        for idx in bl:
            ids, lens = pad(seqs, idx)
            if a.word_dropout > 0:  # randomly blank some words: a regulariser that also teaches robustness to new vocabulary
                drop = (torch.rand(ids.shape) < a.word_dropout) & (ids != PAD)
                ids = ids.masked_fill(drop, UNK)
            logits = net(ids.to(DEV), lens, torch.from_numpy(dn[idx]).to(DEV))
            loss = loss_fn(logits, torch.from_numpy(y[idx]).to(DEV))
            opt.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(net.parameters(), 1.0)
            opt.step(); sched.step(); step += 1
            if step % 100 == 0:
                eta = (time.time() - t1) / step * (steps - step) / 60
                print(f"epoch {ep + 1}/{a.epochs} step {step}/{steps} loss {loss.item():.3f} about {eta:.0f} min left", flush=True)
        pv = predict(net, [seqs[j] for j in va_idx], dn[va_idx])
        auc = float(roc_auc_score(y[va_idx], pv))
        print(f"epoch {ep + 1}: validation AUC {auc:.4f}", flush=True)
        if auc > best_auc:
            best_auc, best_state = auc, {k: v.detach().cpu().clone() for k, v in net.state_dict().items()}
    net.load_state_dict(best_state)
    pv_r = predict(net, [seqs[j] for j in va_idx], dn[va_idx])
    pt_r = predict(net, [seqs[j] for j in te_idx], dn[te_idx])
    yv, yt = y[va_idx], y[te_idx]
    print(f"RNN trained in {(time.time() - t1) / 60:.1f} min", flush=True)

    # ---- the TF-IDF baseline on the very same split, and the blend of both
    pv_m, pt_m = fit_tfidf_baseline(texts, dense, y, masks)
    grid = [i / 20 for i in range(21)]
    w_best = max(grid, key=lambda w: roc_auc_score(yv, blend(pv_m, pv_r, w)))
    pv_b, pt_b = blend(pv_m, pv_r, w_best), blend(pt_m, pt_r, w_best)
    report = {"tfidf_ml": score(yt, pt_m), "rnn": score(yt, pt_r), "blend": score(yt, pt_b), "blend_weight_rnn": w_best,
              "val": {"tfidf_ml": score(yv, pv_m), "rnn": score(yv, pv_r), "blend": score(yv, pv_b)}}
    print("\nTEST (films never seen in training)")
    for k in ("tfidf_ml", "rnn", "blend"):
        r = report[k]
        print(f"  {k:9s} AUC {r['roc_auc']:.4f}  PR-AUC {r['pr_auc']:.4f}  recall@10%-false-blur {r['recall_at_10pct_false_blur']:.4f}")
    print(f"  blend weight of the RNN on validation: {w_best}", flush=True)

    thr_high = float(np.quantile(pv_b[yv == 0], 1 - 0.08))
    thr_low = min(float(np.quantile(pv_b[yv == 0], 1 - 0.15)), thr_high - 0.02)
    meta = {"max_len": a.max_len, "hidden": a.hidden, "n_train": int(tr.sum()), "n_reviews": int(len(reviews)),
            "glove_coverage": round(cover, 3), "fusion_weight": w_best, "fused_thr_low": thr_low, "fused_thr_high": thr_high,
            "dense_features": not a.no_dense, "trained_on": os.path.basename(a.reviews), "test": report,
            "minutes": round((time.time() - t0) / 60, 1)}
    if a.no_save:
        return report

    # ---- export for numpy serving (app/spoiler/rnn.py)
    os.makedirs(a.out, exist_ok=True)
    sd = {k: v.detach().cpu().numpy().astype(np.float32) for k, v in net.state_dict().items()}
    weights = {"emb": sd["emb.weight"].astype(np.float16),
               "w_ih_f": sd["gru.weight_ih_l0"], "w_hh_f": sd["gru.weight_hh_l0"], "b_ih_f": sd["gru.bias_ih_l0"], "b_hh_f": sd["gru.bias_hh_l0"],
               "w_ih_b": sd["gru.weight_ih_l0_reverse"], "w_hh_b": sd["gru.weight_hh_l0_reverse"],
               "b_ih_b": sd["gru.bias_ih_l0_reverse"], "b_hh_b": sd["gru.bias_hh_l0_reverse"],
               "att_w": sd["att.weight"], "att_b": sd["att.bias"], "att_v": sd["att_v.weight"].reshape(-1),
               "fc1_w": sd["fc1.weight"], "fc1_b": sd["fc1.bias"], "fc2_w": sd["fc2.weight"], "fc2_b": sd["fc2.bias"],
               "dense_mean": mean.astype(np.float32), "dense_std": std.astype(np.float32)}
    np.savez_compressed(os.path.join(a.out, WEIGHTS_FILE), **weights)
    with open(os.path.join(a.out, VOCAB_FILE), "w", encoding="utf-8") as fh:
        json.dump(vocab, fh)
    with open(os.path.join(a.out, META_FILE), "w", encoding="utf-8") as fh:
        json.dump(meta, fh, indent=1)

    # ---- prove the numpy server gives the same answers as PyTorch (float16 embeddings move scores by ~1e-3)
    from app.spoiler.rnn import RNNScorer
    scorer = RNNScorer.load(a.out)
    pick = te_idx[:48] if len(te_idx) else va_idx[:48]
    served = scorer.predict([texts[j] for j in pick], dense[pick])
    ref = predict(net, [seqs[j] for j in pick], dn[pick])
    print(f"numpy server vs PyTorch on {len(pick)} reviews: largest difference {np.abs(served - ref).max():.4f}")
    print("saved to", a.out, f"({os.path.getsize(os.path.join(a.out, WEIGHTS_FILE)) / 1e6:.1f} MB of weights)")
    return report


if __name__ == "__main__":
    main()
