from __future__ import annotations

import json
import logging
from typing import List, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Review, ReviewReport, User
from ..workflow import InvalidTransition, review_transition
from .catalog import load_film_info

log = logging.getLogger("cinelog.reviews")


def scan_review(app, review_id: int) -> None:
    """Background job (USER priority): scan a review and publish it. Rules-only fallback if the ML path errors."""
    shield = app.state.shield
    with app.state.db.session() as s:
        r = s.get(Review, review_id)
        if r is None or r.state != "pending_scan":
            return
        info = load_film_info(s, r.film_id)
        try:
            res = shield.scan(r.text, info)
        except Exception as exc:  # noqa: BLE001
            log.warning("ML scan failed for review %s (%s); falling back to rules", review_id, exc)
            res = shield.scan(r.text, info, use_ml=False)
        r.segments_json = json.dumps([g.to_dict() for g in res.segments])
        r.risk, r.uncertain, r.scan_version = res.risk, res.uncertain, info.version
        r.warn = res.warn
        try:
            review_transition(s, r, "published")
        except InvalidTransition:
            return  # the author deleted it while it was being scanned
        s.flush()
        from ..gamification import award
        award(s, r.user_id)


def segments_of(r: Review) -> List[dict]:
    try:
        return json.loads(r.segments_json or "[]")
    except ValueError:
        return []


def n_reports(db: Session, review_id: int) -> int:
    return db.scalar(select(func.count()).select_from(ReviewReport).where(ReviewReport.review_id == review_id)) or 0


def review_view(r: Review, viewer: Optional[User], privileged: bool = False, reports: int = 0) -> dict:
    """Public view hides blurred text (fetched via the Reveal endpoint) and the reasons that would leak it."""
    own = viewer is not None and viewer.id == r.user_id
    segs = []
    segs_raw = segments_of(r)
    for g in segs_raw:
        item = {"idx": g["idx"], "blurred": g["blurred"], "length": len(g["text"])}
        if not g["blurred"]:
            item["text"] = g["text"]
        elif own or privileged:
            item["text"] = g["text"]
            item["reasons"] = g["reasons"]
            item["risk"] = g["risk"]
        segs.append(item)
    out = {"id": r.id, "film_id": r.film_id, "author": {"id": r.user_id, "name": r.author.display_name,
                                                        "critic": "critic" in r.author.role_names},
           "state": r.state, "created_at": r.created_at.isoformat(), "segments": segs,
           "warn": bool(r.warn) and r.state == "published" and not any(g["blurred"] for g in segs_raw)}
    if own or privileged:
        out.update({"risk": r.risk, "uncertain": r.uncertain, "reports": reports})
    if own:
        out["text"] = r.text  # so the author can edit it
    if r.state == "pending_scan":
        out["segments"] = []
        out["message"] = "Scanning for spoilers - this review will appear shortly."
    return out
