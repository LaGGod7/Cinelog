from __future__ import annotations

import datetime as dt
from typing import List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from ..models import Notification, User, now
from ..rbac import get_db, user_required

router = APIRouter(prefix="/notifications", tags=["notifications"])
KEEP_DAYS = 60  # older, already-read items are pruned when the list is opened


def _view(n: Notification) -> dict:
    return {"id": n.id, "kind": n.kind, "text": n.text, "link": n.link, "read": n.read_at is not None,
            "at": n.created_at.replace(tzinfo=dt.timezone.utc).timestamp()}


@router.get("")
def list_notifications(limit: int = 30, db: Session = Depends(get_db), user: User = Depends(user_required)):
    unread = db.scalar(select(func.count()).select_from(Notification).where(
        Notification.user_id == user.id, Notification.read_at.is_(None))) or 0
    rows = db.scalars(select(Notification).where(Notification.user_id == user.id)
                      .order_by(Notification.id.desc()).limit(max(1, min(limit, 100))))
    return {"unread": unread, "items": [_view(n) for n in rows]}


class ReadIn(BaseModel):
    ids: Optional[List[int]] = Field(None, max_length=200)  # omitted = everything


@router.post("/read")
def mark_read(body: ReadIn, db: Session = Depends(get_db), user: User = Depends(user_required)):
    q = update(Notification).where(Notification.user_id == user.id, Notification.read_at.is_(None))
    if body.ids is not None:
        q = q.where(Notification.id.in_(body.ids))
    db.execute(q.values(read_at=now()))
    db.execute(Notification.__table__.delete().where(
        Notification.user_id == user.id, Notification.read_at < now() - dt.timedelta(days=KEEP_DAYS)))
    unread = db.scalar(select(func.count()).select_from(Notification).where(
        Notification.user_id == user.id, Notification.read_at.is_(None))) or 0
    return {"unread": unread}
