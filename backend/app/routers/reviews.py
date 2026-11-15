from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..audit import audit
from ..models import Film, Like, Review, ReviewReport, User
from ..services.notifications import notify
from ..rbac import ensure_can_post, get_db, has_perm, require_perm, user_optional
from ..services import jobs
from ..services.reviews import n_reports, review_view, segments_of
from ..workflow import InvalidTransition, review_transition

router = APIRouter(tags=["reviews"])


class ReviewIn(BaseModel):
    text: str = Field(min_length=10, max_length=5000)
    spoilers: bool = False  # the writer says "this gives away the plot": the whole review is tagged ||...|| and blurred

    @field_validator("text")
    @classmethod
    def _real_text(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 10:  # ten spaces are not a review
            raise ValueError("write at least 10 characters")
        return v


def _tagged(body: ReviewIn) -> str:
    text = body.text.strip()
    return f"||{text}||" if body.spoilers and "||" not in text else text


@router.post("/films/{film_id}/reviews", status_code=202)
def write_review(film_id: int, body: ReviewIn, request: Request, db: Session = Depends(get_db),
                 user: User = Depends(require_perm("review.write"))):
    ensure_can_post(user)
    if db.get(Film, film_id) is None:
        raise HTTPException(404, "film not found")
    if db.scalar(select(Review.id).where(Review.user_id == user.id, Review.film_id == film_id,
                                         Review.state != "removed")):
        raise HTTPException(409, "you already reviewed this film")
    r = Review(user_id=user.id, film_id=film_id, text=_tagged(body), state="pending_scan")
    db.add(r); db.flush()
    rid = r.id
    db.commit()  # the job must see the row
    jobs.submit_scan(request.app, rid)
    db.refresh(r)
    return review_view(r, user)


def _own_review(db: Session, review_id: int, user: User) -> Review:
    r = db.get(Review, review_id)
    if r is None or r.user_id != user.id or r.state == "removed":
        raise HTTPException(404, "review not found")
    return r


@router.patch("/reviews/{review_id}", status_code=202)
def edit_review(review_id: int, body: ReviewIn, request: Request, db: Session = Depends(get_db),
                user: User = Depends(require_perm("review.write"))):
    """Edit your own review. It goes back through the Spoiler Shield (and is hidden from readers until that finishes)."""
    ensure_can_post(user)
    r = _own_review(db, review_id, user)
    if r.state == "pending_scan":
        raise HTTPException(409, "your review is still being checked - try again in a moment")
    if r.state == "hidden":
        raise HTTPException(409, "a moderator hid this review; it can't be edited")
    new_text = _tagged(body)
    if new_text == r.text:
        return review_view(r, user)
    r.text = new_text
    review_transition(db, r, "pending_scan")
    db.execute(delete(ReviewReport).where(ReviewReport.review_id == r.id))  # reports were about the old wording
    audit(db, user.id, "review.edit", f"review:{r.id}", "author edit")
    db.flush()
    rid = r.id
    db.commit()  # the job must see the new text
    jobs.submit_scan(request.app, rid)
    db.refresh(r)
    return review_view(r, user)


@router.delete("/reviews/{review_id}")
def delete_review(review_id: int, db: Session = Depends(get_db), user: User = Depends(require_perm("review.write"))):
    """Delete your own review (kept as 'removed' for the audit trail; likes on it go away; you may write a new one)."""
    r = _own_review(db, review_id, user)
    try:
        review_transition(db, r, "removed")
    except InvalidTransition:
        raise HTTPException(409, "this review changed state - reload and try again") from None
    db.execute(delete(Like).where(Like.kind == "review", Like.target_id == r.id))
    audit(db, user.id, "review.delete", f"review:{r.id}", "author delete")
    return {"ok": True}


@router.get("/reviews/{review_id}")
def get_review(review_id: int, db: Session = Depends(get_db), user: Optional[User] = Depends(user_optional)):
    r = db.get(Review, review_id)
    if r is None:
        raise HTTPException(404, "review not found")
    own = user is not None and user.id == r.user_id
    mod = has_perm(user, "review.moderate")
    if r.state != "published" and not (own or mod):
        raise HTTPException(404, "review not found")  # pending/hidden/removed are invisible to readers
    return review_view(r, user, privileged=mod, reports=n_reports(db, r.id) if (own or mod) else 0)


@router.get("/reviews/{review_id}/segments/{idx}")
def reveal(review_id: int, idx: int, db: Session = Depends(get_db), user: Optional[User] = Depends(user_optional)):
    """Reveal: the blurred text is only sent when this reader asks for it (applies to that reader alone)."""
    r = db.get(Review, review_id)
    own = user is not None and user.id == (r.user_id if r else None)
    if r is None or (r.state != "published" and not (own or has_perm(user, "review.moderate"))):
        raise HTTPException(404, "review not found")
    for g in segments_of(r):
        if g["idx"] == idx:
            return {"idx": idx, "text": g["text"]}
    raise HTTPException(404, "segment not found")


class ReportIn(BaseModel):
    reason: str = Field("spoiler", max_length=40)
    comment: str = Field("", max_length=1000)


@router.post("/reviews/{review_id}/report")
def report(review_id: int, body: ReportIn, request: Request, db: Session = Depends(get_db),
           user: User = Depends(require_perm("review.report"))):
    r = db.get(Review, review_id)
    if r is None or r.state != "published":
        raise HTTPException(404, "review not found")
    if r.user_id == user.id:
        raise HTTPException(400, "you cannot report your own review")
    if db.scalar(select(ReviewReport.id).where(ReviewReport.review_id == r.id, ReviewReport.user_id == user.id)):
        return {"ignored": True, "reports": n_reports(db, r.id)}  # repeat report from the same user is ignored
    try:
        db.add(ReviewReport(review_id=r.id, user_id=user.id, reason=body.reason, comment=body.comment))
        db.flush()
    except IntegrityError:  # two identical reports racing: the UNIQUE constraint decides
        db.rollback()
        return {"ignored": True, "reports": n_reports(db, review_id)}
    n = n_reports(db, r.id)
    hidden = False
    if n >= request.app.state.settings.report_threshold and r.state == "published":
        try:
            review_transition(db, r, "hidden")
            audit(db, None, "review.auto_hide", f"review:{r.id}", f"{n} distinct reports")
            notify(db, r.user_id, "moderation", "Your review was hidden after several reports; a moderator will look at it",
                   f"/films/{r.film_id}")
            hidden = True
        except InvalidTransition:
            pass  # a moderator got there first
    return {"reports": n, "hidden": hidden}
