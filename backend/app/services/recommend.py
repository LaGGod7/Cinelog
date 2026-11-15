"""Film recommendations from what the catalogue already knows: no language model, no outside service.

Content-based: a film is a bag of features (genres, keywords, top-billed cast, decade). A person's profile is the sum of
the features of the films they logged, weighted by how much they liked each one (stars - 3; an unrated log counts a
little). Candidates are scored by the idf-weighted overlap with that profile, then nudged by popularity and by friends
who rated them highly. Every suggestion carries the reason it was made, so it never feels like magic.
"""
from __future__ import annotations

import math
from collections import Counter
from typing import Dict, List, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import DiaryEntry, Film, Follow, User, WatchlistItem
from .catalog import film_card, film_ratings

POOL = 1500          # candidate films considered, most popular first
UNRATED_WEIGHT = 0.25  # logging a film without stars is a mild vote for it
MIN_LOGGED = 3


def features(f: Film) -> Dict[str, float]:
    feats: Dict[str, float] = {}
    for g in f.genres:
        feats[f"g:{g.genre}"] = 1.0
    for k in list(f.keywords)[:12]:
        feats[f"k:{k.keyword}"] = 0.5
    for c in list(f.cast)[:3]:
        feats[f"a:{c.actor}"] = 0.7
    if f.year:
        feats[f"d:{f.year // 10 * 10}"] = 0.4
    return feats


def _label(feat: str) -> str:
    kind, _, name = feat.partition(":")
    return {"g": name, "k": f"“{name}”", "a": f"films with {name}", "d": f"{name}s films"}.get(kind, name)


def _weights(db: Session, uid: int) -> Dict[int, float]:
    """film_id -> how much the person liked it, from -1 (hated) to +1 (loved)."""
    stars: Dict[int, Optional[float]] = {}
    for fid, s in db.execute(select(DiaryEntry.film_id, DiaryEntry.stars).where(DiaryEntry.user_id == uid)
                             .order_by(DiaryEntry.watched_on, DiaryEntry.id)):
        if s is not None or fid not in stars:
            stars[fid] = s
    return {fid: ((s - 3.0) / 2.0 if s is not None else UNRATED_WEIGHT) for fid, s in stars.items()}


def _popular(db: Session, exclude: set, limit: int) -> List[dict]:
    rows = db.execute(select(Film).where(Film.id.not_in(exclude or [0])).order_by(Film.popularity.desc()).limit(limit)).scalars().unique().all()
    ratings = film_ratings(db, [f.id for f in rows])
    return [{**film_card(f, ratings), "reason": "Popular on CineLog", "score": None} for f in rows]


def recommend(db: Session, uid: int, limit: int = 12) -> dict:
    w = _weights(db, uid)
    watched = set(w)
    if len(watched) < MIN_LOGGED:
        return {"ready": False, "logged": len(watched), "needed": MIN_LOGGED, "items": _popular(db, watched, limit)}

    catalogue = list(db.scalars(select(Film).order_by(Film.popularity.desc()).limit(POOL)).unique())
    seen_films = {f.id: f for f in catalogue}
    missing = [i for i in watched if i not in seen_films]
    if missing:
        for f in db.scalars(select(Film).where(Film.id.in_(missing))).unique():
            seen_films[f.id] = f
    feats = {fid: features(f) for fid, f in seen_films.items()}

    df: Counter = Counter()
    for fid in (f.id for f in catalogue):
        df.update(feats[fid].keys())
    n = max(1, len(catalogue))
    idf = lambda k: math.log((n + 1) / (df.get(k, 0) + 1)) + 1.0  # noqa: E731

    profile: Counter = Counter()
    for fid, wt in w.items():
        for k, v in feats.get(fid, {}).items():
            profile[k] += wt * v * idf(k)

    watchlist = {fid for (fid,) in db.execute(select(WatchlistItem.film_id).where(WatchlistItem.user_id == uid))}
    scored = []
    for f in catalogue:
        if f.id in watched:
            continue
        fv = feats[f.id]
        norm = math.sqrt(sum((v * idf(k)) ** 2 for k, v in fv.items())) or 1.0
        s = sum(profile.get(k, 0.0) * v * idf(k) for k, v in fv.items()) / norm
        scored.append((s, f))
    scored.sort(key=lambda t: -t[0])
    short = scored[:60]
    if not short:
        return {"ready": True, "logged": len(watched), "items": []}

    ids = [f.id for _, f in short]
    ratings = film_ratings(db, ids)
    top_s = max(abs(s) for s, _ in short) or 1.0
    friends: Dict[int, List[tuple]] = {}
    for fid, stars, name in db.execute(select(DiaryEntry.film_id, DiaryEntry.stars, User.display_name)
                                       .join(Follow, Follow.followee_id == DiaryEntry.user_id)
                                       .join(User, User.id == DiaryEntry.user_id)
                                       .where(Follow.follower_id == uid, DiaryEntry.film_id.in_(ids), DiaryEntry.stars >= 4)):
        friends.setdefault(fid, []).append((name, stars))
    max_n = max([ratings.get(i, (None, 0))[1] for i in ids] + [1])

    ranked = []
    for s, f in short:
        avg, cnt = ratings.get(f.id, (None, 0))
        total = s / top_s
        total += 0.15 * math.log1p(cnt) / math.log1p(max_n)
        if avg is not None and cnt >= 3:
            total += 0.10 * (avg - 3) / 2
        fr = friends.get(f.id, [])
        total += min(0.75, 0.25 * len(fr))
        if f.id in watchlist:
            total += 0.1
        ranked.append((total, s, f, fr))
    ranked.sort(key=lambda t: -t[0])

    liked = [(fid, wt) for fid, wt in w.items() if wt > 0 and fid in feats]
    items = []
    for total, s, f, fr in ranked[:max(1, min(limit, 30))]:
        fv = feats[f.id]
        reason = None
        if fr:
            name, stars = fr[0]
            reason = f"{name} rated it ★{stars:g}" + (f" and {len(fr) - 1} other{'s' if len(fr) > 2 else ''} you follow" if len(fr) > 1 else "")
        else:
            best, best_sim = None, 0.0
            for fid, wt in liked:  # which film you liked is this most like?
                sim = wt * sum(min(v, feats[fid].get(k, 0.0)) * idf(k) for k, v in fv.items() if k in feats[fid])
                if sim > best_sim:
                    best, best_sim = fid, sim
            top_feats = sorted((k for k in fv if profile.get(k, 0) > 0), key=lambda k: -profile[k] * fv[k] * idf(k))[:2]
            if best is not None and best_sim > 0:
                reason = f"Because you liked {seen_films[best].title}"
                if top_feats:
                    reason += f" · {' and '.join(_label(k) for k in top_feats)}"
            elif top_feats:
                reason = "You like " + " and ".join(_label(k) for k in top_feats)
        items.append({**film_card(f, ratings), "reason": reason or "Matches your taste", "score": round(total, 3),
                      "on_watchlist": f.id in watchlist, "friends": [{"name": n, "stars": s_} for n, s_ in fr[:3]]})
    return {"ready": True, "logged": len(watched), "items": items}
