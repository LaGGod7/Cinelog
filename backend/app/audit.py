from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from .models import AuditLog


def audit(db: Session, actor_id: Optional[int], action: str, target: str = "", detail: str = "") -> None:
    db.add(AuditLog(actor_id=actor_id, action=action, target=target, detail=detail))
