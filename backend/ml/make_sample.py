"""Write a random sample of the Kaggle reviews (only the 3 columns the shield needs) to a smaller JSON-lines file.

    python -m ml.make_sample --reviews ..\\mltraining\\IMDB_reviews.json --out ..\\mltraining\\sample_reviews.json --n 120000
"""
from __future__ import annotations

import argparse

import pandas as pd


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--reviews", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--n", type=int, default=120000)
    ap.add_argument("--total", type=int, default=573913, help="approximate number of reviews in the full file")
    ap.add_argument("--seed", type=int, default=42)
    a = ap.parse_args(argv)
    frac = min(1.0, a.n / a.total)
    kept = 0
    with open(a.out, "w", encoding="utf-8") as f:
        for i, chunk in enumerate(pd.read_json(a.reviews, lines=True, chunksize=50000)):
            part = chunk[["movie_id", "is_spoiler", "review_text"]].sample(frac=frac, random_state=a.seed + i)
            part.to_json(f, orient="records", lines=True, force_ascii=True)
            kept += len(part)
            print(f"chunk {i + 1}: kept {kept} reviews so far", flush=True)
    print(f"wrote {kept} reviews to {a.out}")


if __name__ == "__main__":
    main()
