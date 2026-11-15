from __future__ import annotations

import csv
import datetime as dt
import io
from typing import Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import ASPECTS, AspectRating, DiaryEntry, Film, User, WatchlistItem
from ..gamification import award
from ..rbac import get_db, require_perm, user_required
from ..services.catalog import film_card, film_ratings

router = APIRouter(tags=["diary"])


def _step(v: Optional[float]) -> Optional[float]:
    if v is None:
        return v
    if not (0.5 <= v <= 5) or abs(v * 2 - round(v * 2)) > 1e-9:
        raise ValueError("rating must be between 0.5 and 5 in steps of 0.5")
    return v


class DiaryIn(BaseModel):
    film_id: int
    watched_on: dt.date = Field(default_factory=dt.date.today)
    format: str = "OTT"
    rewatch: bool = False
    notes: str = Field("", max_length=2000)
    stars: Optional[float] = None

    _v = field_validator("stars")(_step)

    @field_validator("watched_on")
    @classmethod
    def _date(cls, v: dt.date) -> dt.date:
        if v < dt.date(1888, 1, 1):  # the first film ever shot
            raise ValueError("films didn't exist then - check the year")
        if v > dt.date.today() + dt.timedelta(days=1):  # a day of slack for time zones
            raise ValueError("you can't log a film you haven't watched yet")
        return v

    @field_validator("format")
    @classmethod
    def _fmt(cls, v: str) -> str:
        if v not in ("Theatre", "OTT", "IMAX"):
            raise ValueError("format must be Theatre, OTT or IMAX")
        return v


def _entry(e: DiaryEntry, title: str = "", film: Optional[Film] = None) -> dict:
    out = {"id": e.id, "film_id": e.film_id, "title": title, "watched_on": e.watched_on.isoformat(),
           "format": e.format, "rewatch": e.rewatch, "notes": e.notes, "stars": e.stars}
    if film is not None:
        out.update({"year": film.year, "poster": film.poster_path, "runtime": film.runtime})
    return out


@router.post("/diary", status_code=201)
def add_entry(body: DiaryIn, db: Session = Depends(get_db), user: User = Depends(require_perm("diary.write"))):
    film = db.get(Film, body.film_id)
    if film is None:
        raise HTTPException(404, "film not found")
    seen_before = db.scalar(select(func.count()).select_from(DiaryEntry).where(
        DiaryEntry.user_id == user.id, DiaryEntry.film_id == body.film_id)) or 0
    e = DiaryEntry(user_id=user.id, film_id=body.film_id, watched_on=body.watched_on, format=body.format,
                   rewatch=body.rewatch or seen_before > 0, notes=body.notes, stars=body.stars)
    db.add(e); db.flush()
    w = db.get(WatchlistItem, (user.id, body.film_id))
    if w:
        db.delete(w)  # watched films leave the watchlist
    db.flush()
    out = _entry(e, film.title, film)
    out["new_badges"] = award(db, user.id)
    return out


@router.get("/diary")
def list_entries(limit: int = 100, offset: int = 0, db: Session = Depends(get_db), user: User = Depends(user_required)):
    rows = db.execute(select(DiaryEntry, Film).join(Film, Film.id == DiaryEntry.film_id)
                      .where(DiaryEntry.user_id == user.id).order_by(DiaryEntry.watched_on.desc(), DiaryEntry.id.desc())
                      .limit(min(limit, 500)).offset(offset)).all()
    return [_entry(e, f.title, f) for e, f in rows]


@router.delete("/diary/{entry_id}")
def delete_entry(entry_id: int, db: Session = Depends(get_db), user: User = Depends(user_required)):
    e = db.get(DiaryEntry, entry_id)
    if e is None or e.user_id != user.id:
        raise HTTPException(404, "entry not found")
    db.delete(e)
    return {"ok": True}


@router.get("/diary/export")
def export(format: str = "json", db: Session = Depends(get_db), user: User = Depends(user_required)):
    rows = [_entry(e, t) for e, t in db.execute(select(DiaryEntry, Film.title).join(Film, Film.id == DiaryEntry.film_id)
                                                 .where(DiaryEntry.user_id == user.id).order_by(DiaryEntry.id)).all()]
    if format == "csv":
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=["id", "film_id", "title", "watched_on", "format", "rewatch", "notes", "stars"])
        w.writeheader(); w.writerows(rows)
        return Response(buf.getvalue(), media_type="text/csv",
                        headers={"Content-Disposition": "attachment; filename=cinelog_diary.csv"})
    return rows


# ---------------------------------------------------------------- watchlist
@router.get("/watchlist")
def watchlist(db: Session = Depends(get_db), user: User = Depends(user_required)):
    films = list(db.scalars(select(Film).join(WatchlistItem, WatchlistItem.film_id == Film.id)
                            .where(WatchlistItem.user_id == user.id).order_by(WatchlistItem.added_at.desc())))
    ratings = film_ratings(db, [f.id for f in films])
    return [film_card(f, ratings) for f in films]


@router.put("/watchlist/{film_id}")
def add_watchlist(film_id: int, db: Session = Depends(get_db), user: User = Depends(require_perm("diary.write"))):
    if db.get(Film, film_id) is None:
        raise HTTPException(404, "film not found")
    if db.get(WatchlistItem, (user.id, film_id)) is None:
        db.add(WatchlistItem(user_id=user.id, film_id=film_id))
    return {"on_watchlist": True}


@router.delete("/watchlist/{film_id}")
def remove_watchlist(film_id: int, db: Session = Depends(get_db), user: User = Depends(require_perm("diary.write"))):
    w = db.get(WatchlistItem, (user.id, film_id))
    if w:
        db.delete(w)
    return {"on_watchlist": False}


# ---------------------------------------------------------------- aspect ratings + taste radar
class Aspects(BaseModel):
    values: Dict[str, float]

    @field_validator("values")
    @classmethod
    def _ok(cls, v: Dict[str, float]) -> Dict[str, float]:
        if not v:
            raise ValueError("give at least one aspect")
        for k, x in v.items():
            if k not in ASPECTS:
                raise ValueError(f"unknown aspect {k}")
            _step(x)
        return v


@router.put("/films/{film_id}/aspects")
def rate_aspects(film_id: int, body: Aspects, db: Session = Depends(get_db),
                 user: User = Depends(require_perm("rating.write"))):
    if db.get(Film, film_id) is None:
        raise HTTPException(404, "film not found")
    for a, v in body.values.items():
        db.merge(AspectRating(user_id=user.id, film_id=film_id, aspect=a, value=v))  # partial sets are fine
    db.flush()
    return {"ok": True}


@router.get("/me/taste")
def taste(db: Session = Depends(get_db), user: User = Depends(user_required)):
    rows = db.execute(select(AspectRating.aspect, func.avg(AspectRating.value), func.count())
                      .where(AspectRating.user_id == user.id).group_by(AspectRating.aspect)).all()
    total = sum(n for _, _, n in rows)
    if total < 3:
        return {"ready": False, "ratings": total, "needed": 3, "radar": {}}
    return {"ready": True, "ratings": total, "radar": {a: round(float(avg), 2) for a, avg, _ in rows}}
