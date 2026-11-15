from __future__ import annotations

import datetime as dt
import json
from typing import Dict

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Film, Poll, Vote
from ..workflow import poll_transition


def counts(db: Session, poll_id: int) -> Dict[int, int]:
    rows = db.execute(select(Vote.option_id, func.count()).where(Vote.poll_id == poll_id).group_by(Vote.option_id)).all()
    return {oid: n for oid, n in rows}


def poll_view(db: Session, p: Poll, my_vote: int | None = None) -> dict:
    if p.state == "closed" and p.result_json:
        res = json.loads(p.result_json)  # frozen at close: never recomputed
        c = {int(k): v for k, v in res["counts"].items()}
    else:
        c = counts(db, p.id)
    total = sum(c.values())
    films = {i: {"title": t, "year": y, "poster": po} for i, t, y, po in db.execute(
        select(Film.id, Film.title, Film.year, Film.poster_path).where(Film.id.in_([o.film_id for o in p.options] or [0])))}
    return {"id": p.id, "club_id": p.club_id, "title": p.title, "state": p.state,
            "deadline": p.deadline.isoformat() if p.deadline else None,
            "screening_date": p.screening_date.isoformat() if p.screening_date else None,
            "winner_film_id": p.winner_film_id, "total_votes": total, "my_vote": my_vote,
            "options": [{"id": o.id, "film_id": o.film_id, "votes": c.get(o.id, 0), **films.get(o.film_id, {})}
                        for o in sorted(p.options, key=lambda o: o.id)]}


def finalize_poll(db: Session, p: Poll) -> None:
    """Open -> Closed: freeze the result and keep it in club history."""
    c = counts(db, p.id)
    poll_transition(db, p, "closed")
    best = sorted(p.options, key=lambda o: (-c.get(o.id, 0), o.id))
    winner = best[0] if best and c.get(best[0].id, 0) > 0 else None
    p.winner_film_id = winner.film_id if winner else None
    p.result_json = json.dumps({"counts": {str(k): v for k, v in c.items()},
                                "total": sum(c.values()), "closed_at": dt.datetime.utcnow().isoformat()})
