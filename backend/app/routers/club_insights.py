"""For conveners: how the club is doing (analytics) and when things happen (calendar, .ics export)."""
from __future__ import annotations

import calendar
import datetime as dt
from collections import Counter
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import (Club, ClubMember, ClubThread, ClubWatchlist, DiaryEntry, Film, Poll, ThreadReply, User, Vote,
                      Watchalong, WatchalongRsvp)
from ..rbac import CLUB_MATRIX, get_db, require_club_role, user_optional, user_required
from ..services.catalog import film_card
from .community import _club_view_or_403

router = APIRouter(tags=["club-insights"])


# ---------------------------------------------------------------- analytics (club role: convener, co-convener)
@router.get("/clubs/{club_id}/analytics")
def analytics(club_id: int, db: Session = Depends(get_db), user: User = Depends(user_required)):
    _club_view_or_403(db, club_id, user)
    require_club_role(db, club_id, user, CLUB_MATRIX["analytics"])
    now = dt.datetime.utcnow()
    members = db.execute(select(ClubMember.user_id, ClubMember.role).where(ClubMember.club_id == club_id)).all()
    member_ids = [m for m, _ in members]
    n_members = max(1, len(members))

    polls = list(db.scalars(select(Poll).where(Poll.club_id == club_id).order_by(Poll.id.desc())).unique())
    votes = dict(db.execute(select(Vote.poll_id, func.count()).where(Vote.poll_id.in_([p.id for p in polls] or [0]))
                            .group_by(Vote.poll_id)).all())
    voted = [p for p in polls if p.state in ("open", "closed")]
    participation = sum(min(1.0, votes.get(p.id, 0) / n_members) for p in voted) / len(voted) if voted else None
    winners = {f.id: f for f in db.scalars(select(Film).where(Film.id.in_([p.winner_film_id for p in polls if p.winner_film_id] or [0])))}

    walongs = list(db.scalars(select(Watchalong).where(Watchalong.club_id == club_id).order_by(Watchalong.starts_at)))
    rsvps = dict(db.execute(select(WatchalongRsvp.watchalong_id, func.count()).where(
        WatchalongRsvp.watchalong_id.in_([w.id for w in walongs] or [0])).group_by(WatchalongRsvp.watchalong_id)).all())
    past = [w for w in walongs if w.starts_at < now]
    nxt = next((w for w in walongs if w.starts_at >= now), None)
    avg_rsvp = sum(rsvps.get(w.id, 0) for w in past) / len(past) if past else None

    # posts per week, last eight weeks, and who writes them
    today = dt.date.today()
    monday = today - dt.timedelta(days=today.weekday())
    weeks = [monday - dt.timedelta(weeks=i) for i in range(7, -1, -1)]
    since = dt.datetime.combine(weeks[0], dt.time())
    threads = list(db.execute(select(ClubThread.user_id, ClubThread.created_at).where(ClubThread.club_id == club_id)).all())
    replies = list(db.execute(select(ThreadReply.user_id, ThreadReply.created_at).join(ClubThread, ClubThread.id == ThreadReply.thread_id)
                              .where(ClubThread.club_id == club_id)).all())
    per_week = Counter()
    for _, at in threads + replies:
        if at >= since:
            per_week[(at.date() - dt.timedelta(days=at.date().weekday()))] += 1
    writers = Counter(uid for uid, _ in threads + replies)
    names = {u.id: u.display_name for u in db.scalars(select(User).where(User.id.in_(list(writers) or [0])))}

    # how the club's films went down with its own members
    film_ids = {w.film_id for w in past} | {p.winner_film_id for p in polls if p.state == "closed" and p.winner_film_id}
    films = {f.id: f for f in db.scalars(select(Film).where(Film.id.in_(film_ids or [0])))}
    rows = db.execute(select(DiaryEntry.film_id, func.count(func.distinct(DiaryEntry.user_id)), func.avg(DiaryEntry.stars))
                      .where(DiaryEntry.film_id.in_(film_ids or [0]), DiaryEntry.user_id.in_(member_ids or [0]))
                      .group_by(DiaryEntry.film_id)).all()
    club_films = sorted(({**film_card(films[fid]), "watched_by": n, "avg": round(float(a), 2) if a is not None else None}
                         for fid, n, a in rows if fid in films), key=lambda x: (-(x["avg"] or 0), -x["watched_by"]))
    return {
        "members": {"total": len(members), "by_role": dict(Counter(r for _, r in members))},
        "polls": {"total": len(polls), "open": sum(p.state == "open" for p in polls), "closed": sum(p.state == "closed" for p in polls),
                  "participation": round(participation, 2) if participation is not None else None,
                  "recent": [{"id": p.id, "title": p.title, "state": p.state, "votes": votes.get(p.id, 0),
                              "winner": winners[p.winner_film_id].title if p.winner_film_id in winners else None} for p in polls[:5]]},
        "watchalongs": {"upcoming": sum(w.starts_at >= now for w in walongs), "past": len(past),
                        "avg_rsvps": round(avg_rsvp, 1) if avg_rsvp is not None else None,
                        "rsvp_rate": round(avg_rsvp / n_members, 2) if avg_rsvp is not None else None,
                        "next": ({"id": nxt.id, "starts_at": nxt.starts_at.isoformat(), "going": rsvps.get(nxt.id, 0),
                                  "title": db.get(Film, nxt.film_id).title} if nxt else None)},
        "discussion": {"threads": len(threads), "replies": len(replies),
                       "weekly": [{"week": w.isoformat(), "posts": per_week.get(w, 0)} for w in weeks],
                       "top_writers": [{"id": i, "name": names.get(i, "?"), "posts": n} for i, n in writers.most_common(5)]},
        "watchlist": db.scalar(select(func.count()).select_from(ClubWatchlist).where(ClubWatchlist.club_id == club_id)) or 0,
        "films": club_films[:6],
    }


# ---------------------------------------------------------------- calendar
def _month_bounds(month: Optional[str]):
    try:
        y, m = (int(x) for x in (month or dt.date.today().strftime("%Y-%m")).split("-"))
        first = dt.date(y, m, 1)
    except ValueError as e:
        raise HTTPException(422, "month must look like 2026-10") from e
    nxt = dt.date(y + (m == 12), m % 12 + 1, 1)
    return first, nxt


def _events(db: Session, club_ids: List[int], start: dt.datetime, end: dt.datetime, viewer: Optional[User]) -> List[dict]:
    clubs = {c.id: c.name for c in db.scalars(select(Club).where(Club.id.in_(club_ids or [0])))}
    out = []
    rows = db.execute(select(Watchalong, Film).join(Film, Film.id == Watchalong.film_id)
                      .where(Watchalong.club_id.in_(club_ids or [0]), Watchalong.starts_at >= start, Watchalong.starts_at < end)).all()
    going = dict(db.execute(select(WatchalongRsvp.watchalong_id, func.count()).where(
        WatchalongRsvp.watchalong_id.in_([w.id for w, _ in rows] or [0])).group_by(WatchalongRsvp.watchalong_id)).all())
    mine = set()
    if viewer:
        mine = {i for (i,) in db.execute(select(WatchalongRsvp.watchalong_id).where(WatchalongRsvp.user_id == viewer.id))}
    for w, f in rows:
        out.append({"type": "watchalong", "id": w.id, "club_id": w.club_id, "club": clubs.get(w.club_id), "at": w.starts_at.isoformat(),
                    "title": f.title, "runtime": f.runtime, "film": film_card(f), "going": going.get(w.id, 0), "rsvp": w.id in mine})
    for p in db.scalars(select(Poll).where(Poll.club_id.in_(club_ids or [0]), Poll.state == "open",
                                           Poll.deadline.is_not(None), Poll.deadline >= start, Poll.deadline < end)):
        out.append({"type": "poll_deadline", "id": p.id, "club_id": p.club_id, "club": clubs.get(p.club_id), "at": p.deadline.isoformat(),
                    "title": f"Voting closes: {p.title}"})
    return sorted(out, key=lambda e: e["at"])


@router.get("/clubs/{club_id}/calendar")
def calendar_month(club_id: int, month: Optional[str] = None, db: Session = Depends(get_db),
                   viewer: Optional[User] = Depends(user_optional)):
    _club_view_or_403(db, club_id, viewer)
    first, nxt = _month_bounds(month)
    ev = _events(db, [club_id], dt.datetime.combine(first, dt.time()), dt.datetime.combine(nxt, dt.time()), viewer)
    return {"month": first.strftime("%Y-%m"), "days": calendar.monthrange(first.year, first.month)[1],
            "first_weekday": first.weekday(), "events": ev}


def _ics_text(s: str) -> str:
    return s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\r", "").replace("\n", "\\n")


def _fold(line: str) -> str:
    """RFC 5545: lines are at most 75 octets; longer ones continue on the next line after a space."""
    raw, out = line.encode(), []
    while len(raw) > 75:
        cut = 75
        while cut > 0 and (raw[cut] & 0xC0) == 0x80:  # never split a multi-byte character
            cut -= 1
        out.append(raw[:cut].decode()); raw = b" " + raw[cut:]
    out.append(raw.decode())
    return "\r\n".join(out)


def build_ics(events: List[dict], name: str) -> str:
    stamp = dt.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//CineLog//Club calendar//EN", "CALSCALE:GREGORIAN",
             f"X-WR-CALNAME:{_ics_text(name)}"]
    for e in events:
        start = dt.datetime.fromisoformat(e["at"])
        mins = (e.get("runtime") or 120) + 15 if e["type"] == "watchalong" else 30
        end = start + dt.timedelta(minutes=mins)
        desc = (e.get("club") or "") + (" · %d going" % e["going"] if e["type"] == "watchalong" else "")
        label = ("Watch-along: " if e["type"] == "watchalong" else "") + e["title"]
        lines += ["BEGIN:VEVENT", f"UID:cinelog-{e['type']}-{e['id']}@cinelog", f"DTSTAMP:{stamp}",
                  f"DTSTART:{start.strftime('%Y%m%dT%H%M%SZ')}", f"DTEND:{end.strftime('%Y%m%dT%H%M%SZ')}",
                  f"SUMMARY:{_ics_text(label)}", f"DESCRIPTION:{_ics_text(desc)}",
                  "END:VEVENT"]
    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold(x) for x in lines) + "\r\n"


@router.get("/clubs/{club_id}/calendar.ics")
def club_ics(club_id: int, db: Session = Depends(get_db), viewer: Optional[User] = Depends(user_optional)):
    club = _club_view_or_403(db, club_id, viewer)
    now = dt.datetime.utcnow()
    ev = _events(db, [club_id], now - dt.timedelta(days=30), now + dt.timedelta(days=365), viewer)
    return Response(build_ics(ev, f"{club.name} · CineLog"), media_type="text/calendar",
                    headers={"Content-Disposition": f"attachment; filename=cinelog_club_{club_id}.ics"})


@router.get("/me/calendar.ics")
def my_ics(db: Session = Depends(get_db), user: User = Depends(user_required)):
    ids = [c for (c,) in db.execute(select(ClubMember.club_id).where(ClubMember.user_id == user.id))]
    now = dt.datetime.utcnow()
    ev = _events(db, ids, now - dt.timedelta(days=30), now + dt.timedelta(days=365), user)
    return Response(build_ics(ev, "My CineLog clubs"), media_type="text/calendar",
                    headers={"Content-Disposition": "attachment; filename=cinelog_my_clubs.ics"})
