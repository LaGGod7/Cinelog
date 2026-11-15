"""Tiny synthetic data in the Kaggle 'IMDB Spoiler Dataset' format - for tests and smoke runs only."""
from __future__ import annotations

import json
import random
from typing import List, Tuple

NAMES = ["Arlo", "Besnik", "Corvina", "Dmitri", "Elowen", "Fenwick", "Galatea", "Hadrian", "Ismene", "Jorund"]
PLACES = ["Valtoria", "Ketterdam", "Mount Sorrel", "Port Anselm", "the Glass Harbour", "Dunmere"]
TWISTS = ["secretly the brother of {b}", "dies saving {b} in the final scene", "betrays {b} and flees to {p}",
          "was dead the whole time", "turns out to be the real villain", "burns down {p} to hide the truth"]
GENERIC = ["The acting was superb and the music stayed with me.", "Pacing drags a little in the middle.",
           "Visually stunning, every frame looks like a painting.", "I would recommend it to anyone who likes drama.",
           "The cinematography is gorgeous.", "A fun ride with a great soundtrack.", "Not my favourite but worth a watch."]


def make(n_movies: int = 40, reviews_per_movie: int = 30, seed: int = 0) -> Tuple[List[dict], List[dict]]:
    rnd = random.Random(seed)
    movies, reviews = [], []
    for m in range(n_movies):
        a, b, c = rnd.sample(NAMES, 3)
        p, q = rnd.sample(PLACES, 2)
        tw1, tw2 = rnd.choice(TWISTS), rnd.choice(TWISTS)
        plot_sents = [
            f"{a} lives quietly in {p} and works as a clockmaker.",
            f"One winter {b} arrives in {p} carrying a sealed letter for {a}.",
            f"{c} hunts the letter across {q} with a band of mercenaries.",
            f"In the finale {a} is {tw1.format(b=b, p=q)}.",
            f"{c} {tw2.format(b=a, p=p)} and the story ends in {q}.",
        ]
        movies.append({"movie_id": f"tt{m:07d}", "plot_summary": plot_sents[0] + " " + plot_sents[1],
                       "plot_synopsis": " ".join(plot_sents), "genre": ["Drama"], "rating": "7.0",
                       "release_date": "2010-01-01", "duration": "2h"})
        for r in range(reviews_per_movie):
            spoiler = rnd.random() < 0.4
            sents = rnd.sample(GENERIC, 3)
            if spoiler:
                sents.insert(rnd.randint(0, 3), rnd.choice([
                    f"{a} is {tw1.format(b=b, p=q)}, which I did not expect.",
                    f"The ending where {c} {tw2.format(b=a, p=p)} ruined it for me.",
                    f"Spoiler: {a} is {tw1.format(b=b, p=q)}."]))
            else:
                sents.insert(rnd.randint(0, 3), f"{a} is a great character and {p} looks beautiful.")
            reviews.append({"review_date": "1 January 2015", "movie_id": f"tt{m:07d}", "user_id": f"ur{r}",
                            "is_spoiler": spoiler, "review_text": " ".join(sents), "rating": "7",
                            "review_summary": "ok"})
    return movies, reviews


def write(dirpath: str, **kw) -> Tuple[str, str]:
    import os
    os.makedirs(dirpath, exist_ok=True)
    movies, reviews = make(**kw)
    mp, rp = os.path.join(dirpath, "IMDB_movie_details.json"), os.path.join(dirpath, "IMDB_reviews.json")
    with open(mp, "w") as f:
        f.write("\n".join(json.dumps(x) for x in movies))
    with open(rp, "w") as f:
        f.write("\n".join(json.dumps(x) for x in reviews))
    return mp, rp
