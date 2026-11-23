from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..audit import audit
from ..models import (AspectRating, CriticPick, DiaryEntry, Film, FilmPlot, Review, SpoilerTerm, User, UserRole, WatchlistItem)
from ..rbac import get_db, require_perm, user_optional
from ..services.catalog import film_dict, set_plot
from ..services.online import find_online
from ..services.reviews import review_view
from .critics import picks_for_film, rating_split

router = APIRouter(tags=["films"])


def _films_in_order(db: Session, ids: List[int]) -> List[Film]:
    if not ids:
        return []
    by_id = {f.id: f for f in db.scalars(select(Film).where(Film.id.in_(ids)))}
    return [by_id[i] for i in ids if i in by_id]


ONLINE_SLOTS = 3  # places in a 10-item list kept for films TMDB knows and we do not have yet


def _with_online(app, q: str, ids: List[int], k: int = 10) -> List[int]:
    """Local matches first, plus up to 3 films TMDB found that are new to us (imported on the spot).

    Before this, TMDB was asked only when the local catalogue had no match (autocomplete) or fewer than 3 (search),
    so a new release never appeared once a few older films shared its words ('superman', 'dune'). Answers are
    remembered for 10 minutes per query and TMDB is skipped for 45 s after a failure (services/online.py)."""
    if len(q.strip()) < 3:
        return ids[:k]
    new = [i for i in find_online(app, q, 5) if i not in ids][:ONLINE_SLOTS]
    return ids[: k - len(new)] + new


@router.get("/films/autocomplete")
def autocomplete(q: str, request: Request, db: Session = Depends(get_db)):
    ids = _with_online(request.app, q, request.app.state.search.autocomplete(q))
    return [{"id": f.id, "title": f.title, "year": f.year} for f in _films_in_order(db, ids)]


@router.get("/films/search")
def search(request: Request, q: str = "", genre: Optional[str] = None, cast: Optional[str] = None,
           year: Optional[int] = None, db: Session = Depends(get_db)):
    ids = request.app.state.search.search(q, genre, cast, year, 10)
    if not (genre or cast or year):  # filters search the local catalogue only
        ids = _with_online(request.app, q, ids)
    return [film_dict(f) for f in _films_in_order(db, ids)]


@router.get("/films/{film_id}")
def film_detail(film_id: int, db: Session = Depends(get_db), user: Optional[User] = Depends(user_optional)):
    f = db.get(Film, film_id)
    if f is None:
        raise HTTPException(404, "film not found")
    rows = db.execute(select(AspectRating.aspect, func.avg(AspectRating.value), func.count())
                      .where(AspectRating.film_id == film_id).group_by(AspectRating.aspect)).all()
    out = film_dict(f)
    out["aspects"] = {a: {"avg": round(float(avg), 2), "n": n} for a, avg, n in rows}
    out["has_plot_context"] = bool(db.scalar(select(func.count()).select_from(FilmPlot).where(
        FilmPlot.film_id == film_id, FilmPlot.kind == "plot")))
    stars = [x for (x,) in db.execute(select(DiaryEntry.stars).where(
        DiaryEntry.film_id == film_id, DiaryEntry.stars.is_not(None)))]
    hist = [0] * 10  # half-star buckets 0.5 .. 5.0
    for x in stars:
        hist[int(round(x * 2)) - 1] += 1
    out["rating"] = {"avg": round(sum(stars) / len(stars), 2) if stars else None, "n": len(stars), "hist": hist}
    out["rating_split"] = rating_split(db, film_id)  # critics vs everyone else
    out["picks"] = picks_for_film(db, film_id)
    out["reviews"] = db.scalar(select(func.count()).select_from(Review).where(
        Review.film_id == film_id, Review.state == "published")) or 0
    if user:
        out["my_stars"] = db.scalar(select(DiaryEntry.stars).where(
            DiaryEntry.film_id == film_id, DiaryEntry.user_id == user.id).order_by(DiaryEntry.id.desc()).limit(1))
        mine = {a.aspect: a.value for a in db.scalars(select(AspectRating).where(
            AspectRating.film_id == film_id, AspectRating.user_id == user.id))}
        out["my_aspects"] = mine
        out["on_watchlist"] = db.get(WatchlistItem, (user.id, film_id)) is not None
        out["i_watched"] = db.scalar(select(DiaryEntry.id).where(DiaryEntry.user_id == user.id, DiaryEntry.film_id == film_id).limit(1)) is not None
        out["my_pick"] = db.get(CriticPick, (user.id, film_id)) is not None
    return out


@router.get("/films/{film_id}/reviews")
def film_reviews(film_id: int, critic_only: bool = False, sort: str = "recent", limit: int = 20, offset: int = 0,
                 db: Session = Depends(get_db), user: Optional[User] = Depends(user_optional)):
    """Only Published reviews are listed: Pending / Hidden / Removed never reach readers (the author still sees their own).
    sort = recent | popular (most liked) | friends (people the reader follows)."""
    from ..models import Follow
    from .community import like_info
    stmt = select(Review).where(Review.film_id == film_id, Review.state == "published")
    if critic_only:
        stmt = stmt.where(Review.user_id.in_(select(UserRole.user_id).where(UserRole.role == "critic")))
    if sort == "friends":
        if user is None:
            return []
        stmt = stmt.where(Review.user_id.in_(select(Follow.followee_id).where(Follow.follower_id == user.id)))
    rows = list(db.scalars(stmt.order_by(Review.id.desc()).limit(200 if sort == "popular" else min(limit, 50)).offset(offset)))
    likes = like_info(db, "review", [r.id for r in rows], user)
    if sort == "popular":
        rows.sort(key=lambda r: (-likes[r.id][0], -r.id))
        rows = rows[:min(limit, 50)]
    if user and offset == 0:
        own = db.scalar(select(Review).where(Review.film_id == film_id, Review.user_id == user.id,
                                             Review.state.in_(("pending_scan", "hidden"))))
        if own is not None:
            rows.insert(0, own)
    out = []
    for r in rows:
        v = review_view(r, user)
        v["likes"], v["liked"] = likes.get(r.id, (0, False))
        out.append(v)
    return out


# ---------------------------------------------------------------- per-film spoiler word list
class Terms(BaseModel):
    terms: List[str] = Field(min_length=1, max_length=50)


@router.get("/films/{film_id}/spoiler-terms")
def list_terms(film_id: int, db: Session = Depends(get_db), _: User = Depends(require_perm("wordlist.edit"))):
    return [{"id": t.id, "term": t.term, "kind": t.kind, "source": t.source}
            for t in db.scalars(select(SpoilerTerm).where(SpoilerTerm.film_id == film_id).order_by(SpoilerTerm.term))]


@router.post("/films/{film_id}/spoiler-terms", status_code=201)
def add_terms(film_id: int, body: Terms, request: Request, db: Session = Depends(get_db),
              user: User = Depends(require_perm("wordlist.edit"))):
    f = db.get(Film, film_id)
    if f is None:
        raise HTTPException(404, "film not found")
    from ..spoiler.wordlist import usable
    source = "moderator" if {"moderator", "admin"} & user.role_names else "convener"
    have = {t for (t,) in db.execute(select(SpoilerTerm.term).where(SpoilerTerm.film_id == film_id))}
    added = []
    for raw in body.terms:
        t = raw.strip().lower()
        if not usable(t) or t in have:
            continue
        db.add(SpoilerTerm(film_id=film_id, term=t, kind="plot", source=source, added_by=user.id))
        added.append(t)
    if added:
        f.wordlist_version += 1
        audit(db, user.id, "wordlist.add", f"film:{film_id}", ", ".join(added))
    return {"added": added, "skipped": len(body.terms) - len(added)}


@router.delete("/films/{film_id}/spoiler-terms/{term_id}")
def delete_term(film_id: int, term_id: int, db: Session = Depends(get_db),
                user: User = Depends(require_perm("wordlist.edit"))):
    t = db.get(SpoilerTerm, term_id)
    if t is None or t.film_id != film_id:
        raise HTTPException(404, "term not found")
    f = db.get(Film, film_id)
    f.wordlist_version += 1
    audit(db, user.id, "wordlist.remove", f"film:{film_id}", t.term)
    db.delete(t)
    return {"ok": True}


class PlotBody(BaseModel):
    text: str = Field(min_length=50, max_length=60000)


@router.put("/films/{film_id}/plot")
def put_plot(film_id: int, body: PlotBody, db: Session = Depends(get_db),
             user: User = Depends(require_perm("wordlist.edit"))):
    """Moderators/conveners can supply the plot used as RAG context when Wikipedia has none."""
    f = db.get(Film, film_id)
    if f is None:
        raise HTTPException(404, "film not found")
    n = set_plot(db, f, body.text, "moderator")
    audit(db, user.id, "plot.set", f"film:{film_id}", f"{n} passages")
    return {"passages": n}
