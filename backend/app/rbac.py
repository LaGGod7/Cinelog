"""Role, permission & workflow engine: deny-by-default permission matrix (SE engine)."""
from __future__ import annotations

import datetime as dt
from typing import Callable, Dict, FrozenSet, Optional, Set

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import ClubMember, User
from .security import SESSION_COOKIE, read_token_full

ALL = frozenset({"viewer", "critic", "convener", "moderator", "admin"})

# permission -> roles that hold it. Anything not listed is denied.
MATRIX: Dict[str, FrozenSet[str]] = {
    "diary.write": ALL,
    "rating.write": ALL,
    "review.write": ALL,
    "review.report": ALL,
    "club.join": ALL,
    "social.follow": ALL,
    "like.write": ALL,
    "list.write": ALL,
    "thread.write": ALL,
    "club.create": frozenset({"convener", "admin"}),
    "wordlist.edit": frozenset({"convener", "moderator", "admin"}),
    "review.moderate": frozenset({"moderator", "admin"}),
    "audit.read": frozenset({"moderator", "admin"}),
    "role.manage": frozenset({"admin"}),
    "catalog.sync": frozenset({"admin"}),
    "model.manage": frozenset({"admin"}),
    "critic.apply": ALL,
    "critic.review": frozenset({"moderator", "admin"}),
    "critic.pick": frozenset({"critic", "admin"}),
    "user.sanction": frozenset({"moderator", "admin"}),
}

# What each permission means (shown on the Admin > Permissions page, so the table explains itself).
PERMISSION_INFO: Dict[str, tuple] = {
    "diary.write": ("Everyday use", "Log films and keep a watchlist"),
    "rating.write": ("Everyday use", "Rate a film and its craft (story, acting, ...)"),
    "review.write": ("Everyday use", "Write, edit and delete your own reviews"),
    "review.report": ("Everyday use", "Report a review that spoils a film"),
    "like.write": ("Everyday use", "Like reviews, lists and club threads"),
    "list.write": ("Everyday use", "Make and edit film lists"),
    "social.follow": ("Everyday use", "Follow other people"),
    "club.join": ("Clubs", "Join public clubs"),
    "thread.write": ("Clubs", "Start and reply to club discussions"),
    "club.create": ("Clubs", "Found a club and become its convener"),
    "wordlist.edit": ("Spoiler shield", "Edit a film's spoiler words and plot summary"),
    "review.moderate": ("Moderation", "Work the review queue: approve, re-blur, remove"),
    "user.sanction": ("Moderation", "Warn (strike) or mute someone; cannot target an equal or higher role"),
    "critic.apply": ("Critics", "Apply to be verified as a critic"),
    "critic.review": ("Critics", "Decide critic applications"),
    "critic.pick": ("Critics", "Publish a critic's pick on a film"),
    "audit.read": ("Administration", "Read the audit log and system status"),
    "role.manage": ("Administration", "Grant and revoke roles; read the dev mailbox"),
    "catalog.sync": ("Administration", "Import films from TMDB"),
    "model.manage": ("Administration", "Reload the spoiler-model files"),
}

ROLE_INFO: Dict[str, str] = {
    "viewer": "Everyone. The base role: log, rate, review, list, follow, join clubs.",
    "critic": "A verified reviewer (approved by a moderator). Gets a badge, a separate score and can publish picks.",
    "convener": "Can found clubs. Runs them as the club's convener.",
    "moderator": "Keeps reviews spoiler-free and the community civil: queue, strikes, mutes, critic applications.",
    "admin": "Owns the install: roles, catalogue, models, audit log.",
}
RANK = ["viewer", "critic", "convener", "moderator", "admin"]  # low -> high; a sanction needs a strictly higher rank


def rank_of(roles: Set[str]) -> int:
    return max((RANK.index(r) for r in roles if r in RANK), default=0)

CLUB_MANAGE = {"convener", "co_convener"}

# Club roles are separate from the site roles: they only apply inside one club. Every route reads this table.
CLUB_MATRIX: Dict[str, FrozenSet[str]] = {
    "read": frozenset({"convener", "co_convener", "member"}),
    "post": frozenset({"convener", "co_convener", "member"}),
    "vote": frozenset({"convener", "co_convener", "member"}),
    "rsvp": frozenset({"convener", "co_convener", "member"}),
    "manage_members": frozenset({"convener", "co_convener"}),
    "run_polls": frozenset({"convener", "co_convener"}),
    "schedule": frozenset({"convener", "co_convener"}),
    "curate_watchlist": frozenset({"convener", "co_convener"}),
    "analytics": frozenset({"convener", "co_convener"}),
    "appoint_co_convener": frozenset({"convener"}),
    "hand_over": frozenset({"convener"}),
}
CLUB_INFO: Dict[str, str] = {
    "read": "Read a private club's threads, polls and calendar",
    "post": "Start and reply to discussions",
    "vote": "Vote in polls",
    "rsvp": "RSVP to watch-alongs",
    "manage_members": "Add and remove members",
    "run_polls": "Create, open, close and cancel polls",
    "schedule": "Schedule watch-alongs and fix screening dates",
    "curate_watchlist": "Edit the club watchlist",
    "analytics": "See the club's analytics",
    "appoint_co_convener": "Appoint co-conveners",
    "hand_over": "Hand the club to someone else",
}


def permissions_of(roles: Set[str]) -> Set[str]:
    """A user's rights are the union of the permission sets of their roles."""
    return {p for p, holders in MATRIX.items() if roles & holders}


def has_perm(user: Optional[User], perm: str) -> bool:
    return bool(user) and perm in permissions_of(user.role_names)


# ---------------------------------------------------------------- FastAPI dependencies
def get_db(request: Request):
    """Session for the request. Page views (GET) get a lock-free read transaction; anything else may write."""
    with request.app.state.db.session(readonly=request.method in ("GET", "HEAD", "OPTIONS")) as s:
        yield s


def get_wdb(request: Request):
    """A session that may write, even on a GET (the few GET handlers that save something as a side effect)."""
    with request.app.state.db.session() as s:
        yield s


def user_optional(request: Request) -> Optional[User]:
    """Load the caller in a short-lived session of its own (returned detached) so authentication never holds the
    request's write lock - handlers that open their own session (votes) would otherwise deadlock on SQLite."""
    tok = request.cookies.get(SESSION_COOKIE)
    if not tok:
        auth = request.headers.get("authorization", "")
        tok = auth[7:] if auth.lower().startswith("bearer ") else None
    if not tok:
        return None
    got = read_token_full(tok, request.app.state.settings)
    if not got:
        return None
    uid, issued = got
    with request.app.state.db.session(readonly=True) as s:
        u = s.get(User, uid)
    if u is not None and u.password_changed_at is not None:
        changed = u.password_changed_at.replace(tzinfo=dt.timezone.utc).timestamp()
        if issued < int(changed):  # signed in before the password was changed/reset: that session is void
            return None
    return u


def user_required(user: Optional[User] = Depends(user_optional)) -> User:
    if user is None:
        raise HTTPException(401, "authentication required")
    return user


def require_perm(perm: str) -> Callable[..., User]:
    def dep(user: User = Depends(user_required)) -> User:
        if not has_perm(user, perm):
            raise HTTPException(403, f"missing permission: {perm}")
        return user

    return dep


def ensure_can_post(user: User) -> None:
    """A moderator's mute blocks new reviews and club posts (reading, rating and logging stay open)."""
    until = getattr(user, "muted_until", None)
    if until is not None and until > dt.datetime.now(dt.timezone.utc).replace(tzinfo=None):
        raise HTTPException(403, f"you are muted until {until.strftime('%d %b %Y %H:%M')} UTC")


def club_role(db: Session, club_id: int, user_id: int) -> Optional[str]:
    m = db.scalar(select(ClubMember.role).where(ClubMember.club_id == club_id, ClubMember.user_id == user_id))
    return m


def require_club_role(db: Session, club_id: int, user: User, allowed: Set[str]) -> str:
    role = club_role(db, club_id, user.id)
    if role is None or role not in allowed:
        raise HTTPException(403, "club role does not allow this action")
    return role
