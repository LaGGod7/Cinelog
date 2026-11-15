"""Stress test: disguised spoilers and spoiler-looking clean reviews (ml/gold_adversarial.json, made by ml/make_adversarial.py).

    python -m ml.eval_adversarial --models models

Offline: no database; the film plots and casts come from scripts/seed_demo.py. Three variants of the shield are compared so that it is
clear which layer catches what:  rules only | trained model (+ rules) | trained model + recurrent layer (+ rules, what the site runs).
'b' = blurred, 'fl' = flagged (blurred, sent to moderators, or given the 'possible spoilers' label).
"""
from __future__ import annotations

import argparse
import json
import os
from collections import OrderedDict

import numpy as np

from app.spoiler.retrieval import make_passages
from app.spoiler.shield import FilmInfo, SpoilerShield
from app.spoiler.wordlist import terms_from_actors, terms_from_cast

GOLD = os.path.join(os.path.dirname(__file__), "gold_adversarial.json")


def outcome(res) -> str:
    if any(s.blurred for s in res.segments):
        return "blurred"
    if res.uncertain:
        return "moderators"
    return "label" if res.warn else "shown"


def main(argv=None) -> dict:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default="models")
    ap.add_argument("--gold", default=GOLD)
    ap.add_argument("--misses", action="store_true", help="list every spoiler review that was not blurred")
    a = ap.parse_args(argv)
    from scripts.seed_demo import FILMS
    infos = {}
    for k, (_tid, title, _rd, _g, cast, plot) in enumerate(FILMS, 1):
        # same word list as the site builds for a film: character names plus actor names (both weak 'name' terms)
        infos[title] = FilmInfo(k, 1, terms_from_cast([c for _a, c in cast]) + terms_from_actors([a_ for a_, _c in cast]), make_passages(plot), [])
    gold = json.load(open(a.gold, encoding="utf-8"))["reviews"]
    sh = SpoilerShield(a.models)
    st = sh.status()
    print(f"shield: ml={st['ml']} rnn={st['rnn']} (active: {(st.get('rnn_meta') or {}).get('active')}) semantic={st.get('semantic')}  warn cut-offs: {st['warn_thresholds']}\n")
    variants = OrderedDict([("rules", dict(use_ml=False, use_sem=False)), ("rules+semantic", dict(use_ml=False)),
                            ("model", dict(use_rnn=False, use_sem=False)), ("model+rnn", dict(use_sem=False)), ("FULL", dict())])
    results = {}
    for vname, kw in variants.items():
        rows = []
        for g in gold:
            res = sh.scan(g["text"], infos[g["film"]], **kw)
            rows.append((g, outcome(res), res.p_ml))
        results[vname] = rows
    cats = list(OrderedDict.fromkeys(g["cat"] for g in gold if g["kind"] == "disguised"))

    def rate(rows, pred):
        return sum(pred(o) for _, o in rows), len(rows)

    print(f"{'DISGUISED SPOILERS (want: blurred / flagged)':40s}" + "".join(f"{v:>16s}" for v in variants))
    for cat in cats + ["ALL DISGUISED"]:
        line = f"  {cat:38s}"
        for vname in variants:
            rows = [(g, o) for g, o, _ in results[vname] if g["kind"] == "disguised" and (cat == "ALL DISGUISED" or g["cat"] == cat)]
            b, n = rate(rows, lambda o: o == "blurred")
            f, _ = rate(rows, lambda o: o != "shown")
            line += f"{f'{b}/{n} b, {f} fl':>16s}"
        print(line)
    print(f"\n{'CLEAN BUT SPOILER-LOOKING (want: shown)':40s}" + "".join(f"{v:>16s}" for v in variants))
    line = f"  {'hard clean':38s}"
    for vname in variants:
        rows = [(g, o) for g, o, _ in results[vname] if g["kind"] == "hard_clean"]
        b, n = rate(rows, lambda o: o == "blurred")
        f, _ = rate(rows, lambda o: o != "shown")
        line += f"{f'{b}/{n} b, {f} fl':>16s}"
    print(line)
    full = results["FULL"]
    pm = {k: [p for g, _, p in full if g["kind"] == k and p is not None] for k in ("disguised", "hard_clean")}
    if all(pm.values()):
        print(f"\nmodel probability: disguised spoilers mean {np.mean(pm['disguised']):.2f} (median {np.median(pm['disguised']):.2f}), "
              f"hard clean mean {np.mean(pm['hard_clean']):.2f}; cut-offs for blur/ask {sh.ml.thr_low:.2f}-{sh.ml.thr_high:.2f}")
        from sklearn.metrics import roc_auc_score
        y = [1] * len(pm["disguised"]) + [0] * len(pm["hard_clean"])
        print(f"AUC of the model's probability on this set: {roc_auc_score(y, pm['disguised'] + pm['hard_clean']):.3f}")
    if a.misses:
        print("\nMISSED (not blurred, not flagged) by the full shield:")
        for g, o, p in full:
            if g["kind"] == "disguised" and o == "shown":
                print(f"  [{g['cat']}] p={p if p is None else round(p, 2)}  {g['film']}: {g['text'][:110]}")
    return {v: [(g["cat"], g["kind"], o) for g, o, _ in rows] for v, rows in results.items()}


if __name__ == "__main__":
    main()
