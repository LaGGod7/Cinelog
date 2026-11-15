"""Catalogue upsert (TMDB payload -> relational rows) and per-film spoiler context loading."""
from __future__ import annotations

import datetime as dt
from typing import Any, Dict, List

from sqlalchemy import func, delete, select
from sqlalchemy.orm import Session

from ..models import (CastMember, Film, FilmGenre, FilmKeyword, FilmPlot, SpoilerTerm)
from ..spoiler.retrieval import make_passages
from ..spoiler.shield import FilmInfo
from ..spoiler.wordlist import terms_from_actors, terms_from_cast


def upsert_tmdb_film(db: Session, d: Dict[str, Any]) -> Film:
    f = db.scalar(select(Film).where(Film.tmdb_id == d["id"]))
    year = int(d["release_date"][:4]) if d.get("release_date") else None
    if f is None:
        f = Film(tmdb_id=d["id"], title=d.get("title") or "Untitled")
        db.add(f)
    f.title = d.get("title") or f.title
    f.year = year
    f.overview = d.get("overview") or ""
    f.poster_path = d.get("poster_path")
    f.popularity = float(d.get("popularity") or 0)
    f.runtime = d.get("runtime")
    f.imdb_id = d.get("imdb_id") or f.imdb_id
    f.synced_at = dt.datetime.utcnow()
    db.flush()
    if "genres" in d:
        db.execute(delete(FilmGenre).where(FilmGenre.film_id == f.id))
        for g in d["genres"]:
            db.merge(FilmGenre(film_id=f.id, genre=g["name"]))
    kws = (d.get("keywords") or {}).get("keywords", [])
    if kws:
        db.execute(delete(FilmKeyword).where(FilmKeyword.film_id == f.id))
        for k in kws[:30]:
            db.merge(FilmKeyword(film_id=f.id, keyword=k["name"][:80]))
    cast = (d.get("credits") or {}).get("cast", [])
    if cast:
        db.execute(delete(CastMember).where(CastMember.film_id == f.id))
        for i, c in enumerate(cast[:25]):
            db.add(CastMember(film_id=f.id, actor=c.get("name", ""), character=c.get("character", "") or "", billing=i))
    db.flush()
    seed_name_terms(db, f)
    return f


def seed_name_terms(db: Session, film: Film) -> int:
    """Character and actor names -> weak word-list terms. Never touches moderator/convener terms."""
    db.refresh(film)
    existing = {t for (t,) in db.execute(select(SpoilerTerm.term).where(SpoilerTerm.film_id == film.id))}
    added = 0
    batches = ((terms_from_cast(c.character for c in film.cast), "tmdb"),
               (terms_from_actors(c.actor for c in film.cast), "actor"))
    for terms, source in batches:
        for term, kind in terms:
            if term not in existing:
                existing.add(term)
                db.add(SpoilerTerm(film_id=film.id, term=term, kind=kind, source=source))
                added += 1
    if added:
        film.wordlist_version += 1
    return added


def backfill_actor_terms(db: Session) -> int:
    """Films imported before actor names were word-list terms: add them once (idempotent, cheap when done)."""
    has_actor = select(SpoilerTerm.film_id).where(SpoilerTerm.source == "actor")
    has_cast = select(CastMember.film_id)
    n = 0
    for f in db.scalars(select(Film).where(Film.id.in_(has_cast), Film.id.not_in(has_actor))):
        n += seed_name_terms(db, f)
    return n


def set_plot(db: Session, film: Film, text: str, source: str) -> int:
    """Replace the film's plot passages (RAG context)."""
    db.execute(delete(FilmPlot).where(FilmPlot.film_id == film.id, FilmPlot.kind == "plot"))
    n = 0
    for p in make_passages(text):
        db.add(FilmPlot(film_id=film.id, kind="plot", text=p, source=source))
        n += 1
    film.plot_checked = True
    film.wordlist_version += 1
    return n


def add_confirmed_spoilers(db: Session, film: Film, sentences: List[str]) -> None:
    for s in sentences:
        if len(s.split()) >= 4:
            db.add(FilmPlot(film_id=film.id, kind="confirmed_spoiler", text=s, source="moderator"))
    film.wordlist_version += 1


def load_film_info(db: Session, film_id: int) -> FilmInfo:
    film = db.get(Film, film_id)
    terms = [(t.term, t.kind) for t in db.scalars(select(SpoilerTerm).where(SpoilerTerm.film_id == film_id))]
    # overview is spoiler-free marketing text, but still useful context for the shield's vocabulary
    plots, spoilers = [], []
    # in the order the plot was stored: the semantic layer treats the second half of the plot as spoiler territory
    for p in db.scalars(select(FilmPlot).where(FilmPlot.film_id == film_id).order_by(FilmPlot.id)):
        (plots if p.kind == "plot" else spoilers).append(p.text)
    return FilmInfo(film_id, film.wordlist_version, terms, plots, spoilers)


def film_dict(f: Film) -> dict:
    return {"id": f.id, "title": f.title, "year": f.year, "overview": f.overview, "poster": f.poster_path,
            "genres": [g.genre for g in f.genres], "cast": [{"actor": c.actor, "character": c.character} for c in f.cast[:12]],
            "runtime": f.runtime, "popularity": f.popularity}


def film_ratings(db: Session, film_ids) -> dict:
    """{film_id: (average stars, number of ratings)} from everyone's diary entries."""
    ids = list(film_ids)
    if not ids:
        return {}
    from ..models import DiaryEntry
    rows = db.execute(select(DiaryEntry.film_id, func.avg(DiaryEntry.stars), func.count())
                      .where(DiaryEntry.film_id.in_(ids), DiaryEntry.stars.is_not(None)).group_by(DiaryEntry.film_id)).all()
    return {fid: (round(float(a), 2), n) for fid, a, n in rows}


def film_card(f: Film, ratings: dict | None = None) -> dict:
    """Compact film for grids and cards."""
    avg, n = (ratings or {}).get(f.id, (None, 0))
    return {"id": f.id, "title": f.title, "year": f.year, "poster": f.poster_path, "runtime": f.runtime,
            "genres": [g.genre for g in f.genres], "overview": f.overview, "rating": avg, "ratings": n}
