"""In-app notifications (the bell). Writing one is a plain INSERT inside the caller's transaction, so it commits or
rolls back together with the action that caused it."""
from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from ..models import Notification


def notify(db: Session, user_id: Optional[int], kind: str, text: str, link: str = "", actor_id: Optional[int] = None) -> None:
    """Tell `user_id` something happened. Never notifies someone about their own action."""
    if user_id is None or user_id == actor_id:
        return
    db.add(Notification(user_id=user_id, kind=kind, text=text[:300], link=link[:200]))
