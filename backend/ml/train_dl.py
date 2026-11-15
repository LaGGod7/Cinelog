"""Fine-tune the deep spoiler model (a retrieval-augmented cross-encoder) and export it for app/spoiler/dl.py.

Each training example is   [review]  [SEP]  [the plot passage most similar to that review]   ->  spoiler / not spoiler.
The split is by movie, the same one ml.train_ml uses, so the test score is on films the model never saw.

Needs a GPU to be practical (6 GB of video memory is enough for the defaults):
    pip install torch --index-url https://download.pytorch.org/whl/cu128      (pick the line pytorch.org gives for your GPU)
    pip install transformers tokenizers onnx onnxscript onnxruntime

    python -m ml.train_dl --reviews ..\\mltraining\\IMDB_reviews.json --movies ..\\mltraining\\IMDB_movie_details.json --out models

Writes models/spoiler_dl.onnx, spoiler_dl_tokenizer.json, spoiler_dl_meta.json (the API loads them on start).
`--smoke` runs the whole pipeline on a tiny random model with no downloads, to check the code path only.
"""
from __future__ import annotations

import argparse
import json
import os
import time

import numpy as np

from app.spoiler.dl import META_FILE, ONNX_FILE, TOKENIZER_FILE, DLScorer
from app.spoiler.retrieval import RetrievalSpace, make_passages
from ml.train_ml import load, recall_at_fpr, split_by_movie


def best_passages(reviews, plots, space):
    """For each review, the single plot passage with the highest TF-IDF cosine (the retrieval step of RAG)."""
    cache = {}
    out = []
    for mid, text in zip(reviews["movie_id"], reviews["review_text"], strict=False):
        if mid not in cache:
            ps = make_passages(plots.get(mid, "")) or [""]
            cache[mid] = (ps, space.vec(ps))
        ps, mat = cache[mid]
        sims = (mat @ space.vec([text]).T).toarray().ravel()
        out.append(ps[int(sims.argmax())])
    return out


def smoke_model(texts, max_len):
    """A tiny untrained BERT + a word-piece tokenizer built from the data: no downloads, for testing the pipeline."""
    from tokenizers import BertWordPieceTokenizer
    from transformers import BertConfig, BertForSequenceClassification, PreTrainedTokenizerFast
    wp = BertWordPieceTokenizer(lowercase=True)
    wp.train_from_iterator(texts, vocab_size=2000, min_frequency=1)
    tok = PreTrainedTokenizerFast(tokenizer_object=wp._tokenizer, unk_token="[UNK]", sep_token="[SEP]", pad_token="[PAD]",
                                  cls_token="[CLS]", mask_token="[MASK]")
    cfg = BertConfig(vocab_size=tok.vocab_size, hidden_size=48, num_hidden_layers=2, num_attention_heads=2,
                     intermediate_size=96, max_position_embeddings=max_len + 8, num_labels=2)
    return tok, BertForSequenceClassification(cfg)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--reviews", required=True)
    ap.add_argument("--movies", required=True)
    ap.add_argument("--out", default="models")
    ap.add_argument("--base", default="distilbert-base-uncased")
    ap.add_argument("--max-reviews", type=int, default=120000)
    ap.add_argument("--epochs", type=int, default=2)
    ap.add_argument("--max-len", type=int, default=256)
    ap.add_argument("--batch", type=int, default=16)
    ap.add_argument("--lr", type=float, default=3e-5)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--smoke", action="store_true", help="tiny random model, no downloads: tests the pipeline only")
    a = ap.parse_args(argv)

    import torch
    from sklearn.metrics import average_precision_score, roc_auc_score

    torch.manual_seed(a.seed)
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"device: {dev}" + (f" ({torch.cuda.get_device_name(0)})" if dev == "cuda" else
                              "  - NO GPU FOUND: this will be very slow. Install the CUDA build of torch (see the top of this file)."),
          flush=True)

    reviews, plots = load(a.reviews, a.movies, a.max_reviews, a.seed)
    split = split_by_movie(reviews, a.seed, plots.keys())
    space = RetrievalSpace().fit(p for t in plots.values() for p in make_passages(t))
    t0 = time.time()
    reviews["passage"] = best_passages(reviews, plots, space)
    tr, va, te = (reviews[split == s].reset_index(drop=True) for s in ("train", "val", "test"))
    print(f"{len(reviews)} reviews; train/val/test = {len(tr)}/{len(va)}/{len(te)}; passages matched in {time.time() - t0:.0f}s", flush=True)

    if a.smoke:
        tok, model = smoke_model(list(reviews["review_text"]) + list(reviews["passage"]), a.max_len)
    else:
        from transformers import AutoModelForSequenceClassification, AutoTokenizer
        tok = AutoTokenizer.from_pretrained(a.base)
        model = AutoModelForSequenceClassification.from_pretrained(a.base, num_labels=2)
    model.to(dev)
    amp = dev == "cuda"

    def enc(df):
        # "longest_first" trims whichever of review / passage is longer, so neither is cut away entirely
        b = tok(list(df["review_text"]), list(df["passage"]), truncation="longest_first", max_length=a.max_len,
                padding=True, return_tensors="pt")
        return {k: v.to(dev) for k, v in b.items() if k in ("input_ids", "attention_mask", "token_type_ids")}

    def predict(df):
        model.eval()
        probs = []
        with torch.no_grad():
            for i in range(0, len(df), a.batch * 4):
                with torch.autocast("cuda", enabled=amp):
                    logits = model(**enc(df.iloc[i:i + a.batch * 4])).logits
                probs.append(torch.softmax(logits.float(), -1)[:, 1].cpu().numpy())
        return np.concatenate(probs) if probs else np.zeros(0)

    # spoilers are the minority (~26%): weight them up so the model does not just learn "not a spoiler"
    pos = float(tr["is_spoiler"].mean())
    weights = torch.tensor([1.0, (1 - pos) / max(pos, 1e-6)], device=dev)
    loss_fn = torch.nn.CrossEntropyLoss(weight=weights)
    opt = torch.optim.AdamW(model.parameters(), lr=a.lr, weight_decay=0.01)
    steps = max(1, a.epochs * ((len(tr) + a.batch - 1) // a.batch))
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=a.lr, total_steps=steps, pct_start=0.06, anneal_strategy="linear")
    scaler = torch.amp.GradScaler("cuda", enabled=amp)
    rng = np.random.RandomState(a.seed)
    best_auc, best_state, step, t0 = -1.0, None, 0, time.time()
    for ep in range(a.epochs):
        model.train()
        order = rng.permutation(len(tr))
        for i in range(0, len(order), a.batch):
            b = tr.iloc[order[i:i + a.batch]]
            y = torch.tensor(b["is_spoiler"].values, dtype=torch.long, device=dev)
            with torch.autocast("cuda", enabled=amp):
                loss = loss_fn(model(**enc(b)).logits.float(), y)
            opt.zero_grad(set_to_none=True)
            scaler.scale(loss).backward()
            scaler.unscale_(opt)
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            scaler.step(opt); scaler.update(); sched.step()
            step += 1
            if step % 200 == 0 or step == steps:
                eta = (time.time() - t0) / step * (steps - step) / 60
                print(f"epoch {ep + 1}/{a.epochs}  step {step}/{steps}  loss {loss.item():.3f}  about {eta:.0f} min left", flush=True)
        pv = predict(va)
        auc = float(roc_auc_score(va["is_spoiler"], pv)) if va["is_spoiler"].nunique() > 1 else 0.5
        print(f"epoch {ep + 1}: validation AUC {auc:.3f}", flush=True)
        if auc > best_auc:  # keep the best epoch, not the last one
            best_auc, best_state = auc, {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
    model.load_state_dict(best_state)

    pv, pt = predict(va), predict(te)
    yv, yt = va["is_spoiler"].values, te["is_spoiler"].values
    _, thr_high = recall_at_fpr(yv, pv, 0.10)   # blur threshold: at most ~10% of clean reviews above it
    _, thr_low = recall_at_fpr(yv, pv, 0.25)    # "ask a moderator" threshold
    thr_low = min(thr_low, thr_high)
    metrics = {"test_roc_auc": float(roc_auc_score(yt, pt)) if len(set(yt)) > 1 else None,
               "test_pr_auc": float(average_precision_score(yt, pt)) if len(set(yt)) > 1 else None,
               "test_recall_at_10pct_false_blur": float(recall_at_fpr(yt, pt, 0.10)[0]) if len(set(yt)) > 1 else None,
               "test_caught_at_thr_high": float((pt[yt == 1] >= thr_high).mean()) if (yt == 1).any() else None,
               "test_wrongly_blurred_at_thr_high": float((pt[yt == 0] >= thr_high).mean()) if (yt == 0).any() else None,
               "val_roc_auc": best_auc, "n_train": int(len(tr)), "n_test": int(len(te))}
    print(json.dumps(metrics, indent=1), flush=True)

    # ---- export: ONNX (runs on the CPU in the API, no torch needed there), int8 weights, tokenizer, thresholds
    os.makedirs(a.out, exist_ok=True)
    model.eval().cpu().float()
    onnx_path = os.path.join(a.out, ONNX_FILE)
    dummy = tok(["a review", "another slightly longer review"], ["a plot passage", "p"], return_tensors="pt", padding=True)
    names = [k for k in ("input_ids", "attention_mask", "token_type_ids") if k in dummy]

    class Wrap(torch.nn.Module):
        def __init__(self, m):
            super().__init__(); self.m = m

        def forward(self, *xs):
            return self.m(**dict(zip(names, xs, strict=False))).logits

    kw = dict(input_names=names, output_names=["logits"], opset_version=17,
              dynamic_axes={**{k: {0: "batch", 1: "seq"} for k in names}, "logits": {0: "batch"}})
    try:
        torch.onnx.export(Wrap(model), tuple(dummy[k] for k in names), onnx_path, dynamo=False, **kw)
    except TypeError:  # older torch has no "dynamo" argument
        torch.onnx.export(Wrap(model), tuple(dummy[k] for k in names), onnx_path, **kw)
    try:
        from onnxruntime.quantization import QuantType, quantize_dynamic
        quantize_dynamic(onnx_path, onnx_path + ".q", weight_type=QuantType.QInt8)
        os.replace(onnx_path + ".q", onnx_path)
    except Exception as exc:  # noqa: BLE001 - quantisation is an optimisation, not a requirement
        print("int8 quantisation skipped:", exc)
    tok.backend_tokenizer.save(os.path.join(a.out, TOKENIZER_FILE))
    meta = {"thr_low": float(thr_low), "thr_high": float(thr_high), "max_len": a.max_len, "base": "smoke" if a.smoke else a.base,
            **metrics}
    json.dump(meta, open(os.path.join(a.out, META_FILE), "w"), indent=1)

    # ---- prove the exported files load and agree with the PyTorch model (quantisation moves scores slightly)
    scorer = DLScorer.load(a.out)
    if scorer is None:
        raise SystemExit("export finished but the files could not be loaded back (is onnxruntime installed?)")
    sample = te.head(64) if len(te) else va.head(64)
    served = scorer.score(list(sample["review_text"]), list(sample["passage"]))
    diff = float(np.abs(served - predict_cpu(model, tok, sample, a.max_len)).max()) if len(sample) else 0.0
    print(f"exported and reloaded OK ({os.path.getsize(onnx_path) / 1e6:.0f} MB); largest score difference vs PyTorch: {diff:.3f}")
    print("saved to", a.out)
    return meta


def predict_cpu(model, tok, df, max_len):
    import torch
    with torch.no_grad():
        b = tok(list(df["review_text"]), list(df["passage"]), truncation="longest_first", max_length=max_len, padding=True, return_tensors="pt")
        b = {k: v for k, v in b.items() if k in ("input_ids", "attention_mask", "token_type_ids")}
        return torch.softmax(model(**b).logits, -1)[:, 1].numpy()


if __name__ == "__main__":
    main()
