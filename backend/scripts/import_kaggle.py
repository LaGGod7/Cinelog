"""Import the Kaggle IMDB movie details (plot synopses) into the catalogue as RAG context.

The Kaggle file has IMDb ids but no titles, so each id is resolved through TMDB's /find endpoint (needs TMDB_API_KEY).

    python -m scripts.import_kaggle --movies IMDB_movie_details.json [--limit 500]
"""
from __future__ import annotations

import argparse
import json


from app.config import Settings
from app.main import create_app
from app.services.catalog import set_plot, upsert_tmdb_film


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--movies", required=True)
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    app = create_app(Settings(start_workers=False))
    tmdb = app.state.tmdb
    if tmdb is None:
        raise SystemExit("Set TMDB_API_KEY first (copy backend/.env.example to .env)")
    n = done = 0
    for line in open(a.movies, encoding="utf-8"):
        if not line.strip():
            continue
        m = json.loads(line)
        text = (m.get("plot_synopsis") or "").strip() or (m.get("plot_summary") or "").strip()
        if not text:
            continue
        n += 1
        if a.limit and n > a.limit:
            break
        try:
            hit = tmdb.find_imdb(m["movie_id"])
            if not hit:
                continue
            d = tmdb.details(hit["id"])
            with app.state.db.session() as s:
                f = upsert_tmdb_film(s, d)
                f.imdb_id = m["movie_id"]
                set_plot(s, f, text, "kaggle")
            done += 1
            if done % 50 == 0:
                print(done, "films imported")
        except Exception as exc:  # noqa: BLE001
            print("skip", m.get("movie_id"), exc)
    print(f"imported {done} films with plot context")


if __name__ == "__main__":
    main()
