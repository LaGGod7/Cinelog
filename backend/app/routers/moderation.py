from __future__ import annotations

import datetime as dt
import json
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..audit import audit
from ..dsa.inverted_index import top_k
from ..models import AuditLog, CriticApplication, Film, Review, ReviewReport, User, UserStrike
from ..rbac import get_db, rank_of, require_perm
from ..services import jobs
from ..services.catalog import add_confirmed_spoilers
from ..services.notifications import notify
from ..services.reviews import n_reports, review_view, segments_of
from ..workflow import InvalidTransition, review_transition

router = APIRouter(prefix="/moderation", tags=["moderation"])


def queue_score(risk: float, reports: int) -> float:
    return 0.6 * risk + 0.4 * min(1.0, reports / 3)


@router.get("/queue")
def queue(db: Session = Depends(get_db), _: User = Depends(require_perm("review.moderate"))):
    """Flagged reviews (auto-hidden by reports, or in the model's uncertain band) - riskiest first (max-heap via top-K)."""
    rows = db.scalars(select(Review).where((Review.state == "hidden") | ((Review.state == "published") & Review.uncertain)))
    scored, by_id = [], {}
    for r in rows:
        rep = n_reports(db, r.id)
        scored.append((queue_score(r.risk, rep), r.id))
        by_id[r.id] = (r, rep)
    out = []
    for score, rid in top_k(scored, 100):
        r, rep = by_id[rid]
        v = review_view(r, None, privileged=True, reports=rep)
        v.update({"score": round(score, 3), "film_title": db.get(Film, r.film_id).title})
        out.append(v)
    return out


def _lock_get(db: Session, review_id: int) -> Review:
    r = db.get(Review, review_id)
    if r is None:
        raise HTTPException(404, "review not found")
    return r


class Note(BaseModel):
    note: str = Field("", max_length=300)  # why: the author reads it, and it is saved with the decision


def _with_note(base: str, note: str) -> str:
    return f"{base} | note: {note.strip()}" if note.strip() else base


def _notify(request: Request, db: Session, r: Review, what: str, note: str = "") -> List[int]:
    why = f" ({note.strip()})" if note.strip() else ""
    notify(db, r.user_id, "moderation", f"A moderator {what} your review{why}", f"/films/{r.film_id}")
    return jobs.queue_emails(db, [db.get(User, r.user_id)], f"Your CineLog review was {what}",
                             f"A moderator {what} your review of film #{r.film_id}." + (f"\n\nNote from the moderator: {note.strip()}" if note.strip() else ""))


def _transition(db: Session, r: Review, dst: str) -> None:
    try:
        review_transition(db, r, dst)
    except InvalidTransition as e:
        raise HTTPException(409, str(e)) from e  # e.g. another moderator acted first


@router.post("/{review_id}/approve")
def approve(review_id: int, request: Request, body: Note = Note(), db: Session = Depends(get_db),
            mod: User = Depends(require_perm("review.moderate"))):
    r = _lock_get(db, review_id)
    if r.state == "hidden":
        _transition(db, r, "published")
    elif r.state != "published":
        raise HTTPException(409, f"cannot approve a review in state {r.state}")
    r.uncertain = False
    r.warn = False
    audit(db, mod.id, "review.approve", f"review:{r.id}", _with_note("", body.note).lstrip(" |"))
    ids = _notify(request, db, r, "approved", body.note)
    db.commit(); jobs.dispatch_emails(request.app, ids)
    return {"state": r.state}


class RemoveIn(BaseModel):
    confirm_spoiler: bool = False
    note: str = Field("", max_length=300)


@router.post("/{review_id}/remove")
def remove(review_id: int, body: RemoveIn, request: Request, db: Session = Depends(get_db),
           mod: User = Depends(require_perm("review.moderate"))):
    r = _lock_get(db, review_id)
    if r.state == "published":
        _transition(db, r, "hidden")
    _transition(db, r, "removed")  # Removed is final
    if body.confirm_spoiler:
        film = db.get(Film, r.film_id)
        add_confirmed_spoilers(db, film, [g["text"] for g in segments_of(r) if g["blurred"] or r.risk >= 0.5])
    audit(db, mod.id, "review.remove", f"review:{r.id}", _with_note("confirmed spoiler" if body.confirm_spoiler else "", body.note).lstrip(" |"))
    ids = _notify(request, db, r, "removed", body.note)
    db.commit(); jobs.dispatch_emails(request.app, ids)
    return {"state": r.state}


class ReblurIn(BaseModel):
    segments: List[int] = Field(min_length=1)
    terms: List[str] = []
    note: str = Field("", max_length=300)


@router.post("/{review_id}/reblur")
def reblur(review_id: int, body: ReblurIn, request: Request, db: Session = Depends(get_db),
           mod: User = Depends(require_perm("review.moderate"))):
    """Publish the review with the chosen sentences blurred; those sentences also teach the film's RAG context."""
    r = _lock_get(db, review_id)
    segs = segments_of(r)
    chosen = []
    for g in segs:
        if g["idx"] in body.segments:
            g["blurred"] = True
            chosen.append(g["text"])
    if not chosen:
        raise HTTPException(400, "no such segments")
    if r.state == "hidden":
        _transition(db, r, "published")
    elif r.state != "published":
        raise HTTPException(409, f"cannot re-blur a review in state {r.state}")
    r.segments_json = json.dumps(segs)
    r.uncertain = False
    r.warn = False
    film = db.get(Film, r.film_id)
    add_confirmed_spoilers(db, film, chosen)
    audit(db, mod.id, "review.reblur", f"review:{r.id}", _with_note(f"segments {body.segments}", body.note))
    ids = _notify(request, db, r, "published with spoilers blurred", body.note)
    db.commit(); jobs.dispatch_emails(request.app, ids)
    return {"state": r.state}


# ================================================================= sanctions (strikes and mutes)
STRIKE_WINDOW_DAYS, STRIKES_TO_MUTE, AUTO_MUTE_DAYS = 30, 3, 3


class SanctionIn(BaseModel):
    reason: str = Field(min_length=5, max_length=300)
    review_id: Optional[int] = None


class MuteIn(BaseModel):
    days: int = Field(ge=1, le=30)
    reason: str = Field(min_length=5, max_length=300)


def _sanction_target(db: Session, mod: User, uid: int) -> User:
    """A moderator can only act on someone of a strictly lower role: a moderator cannot sanction another moderator
    or an admin; an admin can sanction a moderator but not another admin."""
    u = db.get(User, uid)
    if u is None:
        raise HTTPException(404, "user not found")
    if u.id == mod.id:
        raise HTTPException(400, "you cannot sanction yourself")
    if rank_of(u.role_names) >= rank_of(mod.role_names):
        raise HTTPException(403, "you can only sanction someone with a lower role than yours")
    return u


def _recent_strikes(db: Session, uid: int) -> int:
    since = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None) - dt.timedelta(days=STRIKE_WINDOW_DAYS)
    return db.scalar(select(func.count()).select_from(UserStrike).where(UserStrike.user_id == uid, UserStrike.created_at >= since)) or 0


def _mute(u: User, days: int) -> dt.datetime:
    until = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None) + dt.timedelta(days=days)
    u.muted_until = max(until, u.muted_until) if u.muted_until else until
    return u.muted_until


@router.get("/users/{uid}")
def sanction_history(uid: int, db: Session = Depends(get_db), mod: User = Depends(require_perm("user.sanction"))):
    u = db.get(User, uid)
    if u is None:
        raise HTTPException(404, "user not found")
    rows = db.scalars(select(UserStrike).where(UserStrike.user_id == uid).order_by(UserStrike.id.desc()).limit(20))
    muted = u.muted_until is not None and u.muted_until > dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    return {"id": u.id, "name": u.display_name, "roles": sorted(u.role_names), "muted_until": u.muted_until.isoformat() if muted else None,
            "recent_strikes": _recent_strikes(db, uid), "can_sanction": rank_of(u.role_names) < rank_of(mod.role_names) and u.id != mod.id,
            "strikes": [{"id": x.id, "reason": x.reason, "review_id": x.review_id, "at": x.created_at.isoformat(), "by": x.issued_by} for x in rows]}


@router.post("/users/{uid}/strike", status_code=201)
def strike(uid: int, body: SanctionIn, db: Session = Depends(get_db), mod: User = Depends(require_perm("user.sanction"))):
    u = _sanction_target(db, mod, uid)
    db.add(UserStrike(user_id=uid, issued_by=mod.id, review_id=body.review_id, reason=body.reason.strip()))
    db.flush()
    audit(db, mod.id, "user.strike", f"user:{uid}", body.reason.strip())
    n = _recent_strikes(db, uid)
    notify(db, uid, "moderation", f"Warning from a moderator: {body.reason.strip()}", "/me", mod.id)
    auto = False
    if n >= STRIKES_TO_MUTE:
        until = _mute(u, AUTO_MUTE_DAYS)
        audit(db, mod.id, "user.automute", f"user:{uid}", f"{n} strikes in {STRIKE_WINDOW_DAYS} days; muted until {until.isoformat()}")
        notify(db, uid, "moderation", f"You are muted until {until.strftime('%d %b %H:%M')} UTC after {n} warnings", "/me", mod.id)
        auto = True
    return {"strikes": n, "auto_muted": auto, "muted_until": u.muted_until.isoformat() if u.muted_until else None}


@router.post("/users/{uid}/mute")
def mute(uid: int, body: MuteIn, db: Session = Depends(get_db), mod: User = Depends(require_perm("user.sanction"))):
    u = _sanction_target(db, mod, uid)
    until = _mute(u, body.days)
    audit(db, mod.id, "user.mute", f"user:{uid}", f"{body.days} days: {body.reason.strip()}")
    notify(db, uid, "moderation", f"You are muted until {until.strftime('%d %b %H:%M')} UTC: {body.reason.strip()}", "/me", mod.id)
    return {"muted_until": until.isoformat()}


@router.delete("/users/{uid}/mute")
def unmute(uid: int, db: Session = Depends(get_db), mod: User = Depends(require_perm("user.sanction"))):
    u = _sanction_target(db, mod, uid)
    u.muted_until = None
    audit(db, mod.id, "user.unmute", f"user:{uid}")
    notify(db, uid, "moderation", "A moderator lifted your mute", "/me", mod.id)
    return {"muted_until": None}


# ================================================================= the moderator's dashboard
@router.get("/stats")
def stats(db: Session = Depends(get_db), _: User = Depends(require_perm("review.moderate"))):
    now = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    n = lambda *cond: db.scalar(select(func.count()).select_from(Review).where(*cond)) or 0  # noqa: E731
    week, month = now - dt.timedelta(days=7), now - dt.timedelta(days=30)
    decisions = ("review.approve", "review.reblur", "review.remove")
    by_action: Dict[str, int] = dict(db.execute(select(AuditLog.action, func.count()).where(
        AuditLog.at >= week, AuditLog.action.in_(decisions + ("user.strike", "user.mute", "critic.approve", "critic.reject")))
        .group_by(AuditLog.action)).all())
    movers = db.execute(select(AuditLog.actor_id, func.count()).where(AuditLog.at >= month, AuditLog.action.in_(decisions))
                        .group_by(AuditLog.actor_id).order_by(func.count().desc()).limit(8)).all()
    names = {u.id: u.display_name for u in db.scalars(select(User).where(User.id.in_([a for a, _ in movers if a] or [0])))}
    top = db.execute(select(Film.id, Film.title, func.count(ReviewReport.id)).join(Review, Review.film_id == Film.id)
                     .join(ReviewReport, ReviewReport.review_id == Review.id).group_by(Film.id, Film.title)
                     .order_by(func.count(ReviewReport.id).desc()).limit(5)).all()
    return {"queue": {"reported": n(Review.state == "hidden"), "uncertain": n(Review.state == "published", Review.uncertain),
                      "warned": n(Review.state == "published", Review.warn)},
            "critic_applications_waiting": db.scalar(select(func.count()).select_from(CriticApplication).where(CriticApplication.state == "pending")) or 0,
            "last_7_days": by_action, "decisions_30_days": [{"id": a, "name": names.get(a, "system"), "n": c} for a, c in movers],
            "most_reported_films": [{"id": i, "title": t, "reports": c} for i, t, c in top],
            "strikes_30_days": db.scalar(select(func.count()).select_from(UserStrike).where(UserStrike.created_at >= month)) or 0}


# ================================================================= decisions as labelled data
@router.get("/labels")
def labels(limit: int = 500, db: Session = Depends(get_db), _: User = Depends(require_perm("review.moderate"))):
    """Every moderator decision as a labelled example (clean / spoiler), newest decision per review. This is the training
    set for a plot-conditioned classifier: the shield's own mistakes, corrected by people."""
    rows = db.execute(select(AuditLog).where(AuditLog.action.in_(("review.approve", "review.reblur", "review.remove")))
                      .order_by(AuditLog.id)).scalars()
    latest: Dict[int, AuditLog] = {}
    for a in rows:
        if a.target.startswith("review:"):
            latest[int(a.target.split(":")[1])] = a
    out = []
    for rid, a in sorted(latest.items(), key=lambda kv: -kv[1].id)[:max(1, min(limit, 5000))]:
        r = db.get(Review, rid)
        if r is None:
            continue
        spoiler = a.action == "review.reblur" or (a.action == "review.remove" and a.detail.startswith("confirmed spoiler"))
        if a.action == "review.remove" and not spoiler:
            continue  # removed for another reason (abuse...): says nothing about spoilers
        f = db.get(Film, r.film_id)
        segs = segments_of(r)
        out.append({"review_id": rid, "film_id": r.film_id, "film": f.title if f else "", "year": f.year if f else None,
                    "label": "spoiler" if spoiler else "clean", "text": r.text,
                    "spoiler_sentences": [g["text"] for g in segs if g["blurred"]] if spoiler else [],
                    "decision": a.action, "at": a.at.isoformat()})
    return out
