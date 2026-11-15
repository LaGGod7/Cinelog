"""Finite-state machines as transition relations T ⊆ S × S. Anything not listed is rejected (HTTP 409)."""
from __future__ import annotations

from typing import Dict, Set, Type

from sqlalchemy import update
from sqlalchemy.orm import Session

from .models import CriticApplication, Poll, Review


class InvalidTransition(Exception):
    def __init__(self, src: str, dst: str):
        super().__init__(f"invalid transition {src} -> {dst}")
        self.src, self.dst = src, dst


REVIEW_T: Dict[str, Set[str]] = {
    "pending_scan": {"published", "removed"},
    "published": {"hidden", "pending_scan", "removed"},  # pending_scan again = the author edited it; removed = author deleted
    "hidden": {"published", "removed"},
    "removed": set(),
}
POLL_T: Dict[str, Set[str]] = {
    "draft": {"open", "cancelled"},
    "open": {"closed"},
    "closed": set(),
    "cancelled": set(),
}


APPLICATION_T: Dict[str, Set[str]] = {
    "pending": {"approved", "rejected", "withdrawn"},
    "approved": set(),
    "rejected": set(),
    "withdrawn": set(),
}


def can(table: Dict[str, Set[str]], src: str, dst: str) -> bool:
    return dst in table.get(src, set())


def _cas(db: Session, model: Type, obj_id: int, table: Dict[str, Set[str]], src: str, dst: str) -> None:
    """Compare-and-swap so two concurrent actors cannot both win: first wins, second sees the new state."""
    if not can(table, src, dst):
        raise InvalidTransition(src, dst)
    res = db.execute(update(model).where(model.id == obj_id, model.state == src).values(state=dst))
    if res.rowcount != 1:
        cur = db.execute(model.__table__.select().with_only_columns(model.state).where(model.id == obj_id)).scalar()
        raise InvalidTransition(cur or src, dst)


def review_transition(db: Session, review: Review, dst: str) -> None:
    _cas(db, Review, review.id, REVIEW_T, review.state, dst)
    review.state = dst


def poll_transition(db: Session, poll: Poll, dst: str) -> None:
    _cas(db, Poll, poll.id, POLL_T, poll.state, dst)
    poll.state = dst


def application_transition(db: Session, app_row: CriticApplication, dst: str) -> None:
    _cas(db, CriticApplication, app_row.id, APPLICATION_T, app_row.state, dst)
    app_row.state = dst
