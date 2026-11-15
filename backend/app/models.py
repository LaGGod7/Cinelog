"""Relational schema in 3NF. Every fact is stored once; constraints do the policing."""
from __future__ import annotations

import datetime as dt
from typing import Optional

from sqlalchemy import (true, Boolean, CheckConstraint, Date, DateTime, Float, ForeignKey, Index, Integer, String, Text,
                        UniqueConstraint, event)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)


ROLES = ("viewer", "critic", "convener", "moderator", "admin")
AVATARS = ("reel", "popcorn", "clapper", "camera", "ticket", "mask", "star", "projector", "ghost", "robot", "rocket", "cat")
ASPECTS = ("story", "acting", "visuals", "music", "pacing")


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    password_hash: Mapped[Optional[str]] = mapped_column(String(100))
    display_name: Mapped[str] = mapped_column(String(80))
    google_sub: Mapped[Optional[str]] = mapped_column(String(64), unique=True)
    email_opt_out: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now)
    bio: Mapped[str] = mapped_column(String(300), default="", server_default="")
    avatar: Mapped[str] = mapped_column(String(20), default="", server_default="")  # a key from AVATARS, or empty
    password_changed_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime)  # sessions issued before this are void
    muted_until: Mapped[Optional[dt.datetime]] = mapped_column(DateTime)  # a moderator's mute: no new reviews or posts until then
    spoiler_safe: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())  # hide "possible spoilers" reviews on films you have not seen
    roles: Mapped[list["UserRole"]] = relationship(cascade="all, delete-orphan", lazy="selectin")

    @property
    def role_names(self) -> set[str]:
        return {r.role for r in self.roles}


class UserRole(Base):
    __tablename__ = "user_roles"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    role: Mapped[str] = mapped_column(String(20), primary_key=True)
    __table_args__ = (CheckConstraint("role in ('viewer','critic','convener','moderator','admin')"),)


class Film(Base):
    __tablename__ = "films"
    id: Mapped[int] = mapped_column(primary_key=True)
    tmdb_id: Mapped[Optional[int]] = mapped_column(Integer, unique=True)
    imdb_id: Mapped[Optional[str]] = mapped_column(String(20), unique=True)  # tt..., links Kaggle data
    title: Mapped[str] = mapped_column(String(300), index=True)
    year: Mapped[Optional[int]] = mapped_column(Integer, index=True)
    overview: Mapped[str] = mapped_column(Text, default="")
    poster_path: Mapped[Optional[str]] = mapped_column(String(200))
    popularity: Mapped[float] = mapped_column(Float, default=0.0)
    runtime: Mapped[Optional[int]] = mapped_column(Integer)
    wordlist_version: Mapped[int] = mapped_column(Integer, default=1)
    plot_checked: Mapped[bool] = mapped_column(Boolean, default=False)  # wikipedia plot lookup attempted
    synced_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime)
    genres: Mapped[list["FilmGenre"]] = relationship(cascade="all, delete-orphan", lazy="selectin")
    cast: Mapped[list["CastMember"]] = relationship(cascade="all, delete-orphan", lazy="selectin",
                                                    order_by="CastMember.billing")
    keywords: Mapped[list["FilmKeyword"]] = relationship(cascade="all, delete-orphan", lazy="selectin")


class FilmGenre(Base):
    __tablename__ = "film_genres"
    film_id: Mapped[int] = mapped_column(ForeignKey("films.id", ondelete="CASCADE"), primary_key=True)
    genre: Mapped[str] = mapped_column(String(40), primary_key=True)


class FilmKeyword(Base):
    __tablename__ = "film_keywords"
    film_id: Mapped[int] = mapped_column(ForeignKey("films.id", ondelete="CASCADE"), primary_key=True)
    keyword: Mapped[str] = mapped_column(String(80), primary_key=True)


class CastMember(Base):
    __tablename__ = "cast_members"
    id: Mapped[int] = mapped_column(primary_key=True)
    film_id: Mapped[int] = mapped_column(ForeignKey("films.id", ondelete="CASCADE"), index=True)
    actor: Mapped[str] = mapped_column(String(120))
    character: Mapped[str] = mapped_column(String(160), default="")
    billing: Mapped[int] = mapped_column(Integer, default=0)


class FilmPlot(Base):
    """RAG corpus: per-film context passages (plot text, confirmed spoiler sentences)."""
    __tablename__ = "film_plots"
    id: Mapped[int] = mapped_column(primary_key=True)
    film_id: Mapped[int] = mapped_column(ForeignKey("films.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(20), default="plot")  # plot | confirmed_spoiler
    text: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(40), default="")  # kaggle | wikipedia | moderator | seed
    __table_args__ = (CheckConstraint("kind in ('plot','confirmed_spoiler')"),)


class SpoilerTerm(Base):
    __tablename__ = "spoiler_terms"
    id: Mapped[int] = mapped_column(primary_key=True)
    film_id: Mapped[int] = mapped_column(ForeignKey("films.id", ondelete="CASCADE"), index=True)
    term: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(10), default="plot")  # name (weak) | plot (strong)
    source: Mapped[str] = mapped_column(String(20), default="tmdb")  # tmdb | moderator | convener
    added_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    __table_args__ = (UniqueConstraint("film_id", "term"), CheckConstraint("kind in ('name','plot')"))


class DiaryEntry(Base):
    __tablename__ = "diary_entries"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    film_id: Mapped[int] = mapped_column(ForeignKey("films.id", ondelete="CASCADE"))
    watched_on: Mapped[dt.date] = mapped_column(Date)
    format: Mapped[str] = mapped_column(String(10), default="OTT")
    rewatch: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str] = mapped_column(Text, default="")
    stars: Mapped[Optional[float]] = mapped_column(Float)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now)
    __table_args__ = (
        CheckConstraint("stars is null or (stars >= 0.5 and stars <= 5)"),
        CheckConstraint("format in ('Theatre','OTT','IMAX')"),
        Index("ix_diary_user_date", "user_id", "watched_on"),
    )


class WatchlistItem(Base):
    __tablename__ = "watchlist"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    film_id: Mapped[int] = mapped_column(ForeignKey("films.id", ondelete="CASCADE"), primary_key=True)
    added_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now)


class AspectRating(Base):
    __tablename__ = "aspect_ratings"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    film_id: Mapped[int] = mapped_column(ForeignKey("films.id", ondelete="CASCADE"), primary_key=True)
    aspect: Mapped[str] = mapped_column(String(10), primary_key=True)
    value: Mapped[float] = mapped_column(Float)
    __table_args__ = (
        CheckConstraint("value >= 0.5 and value <= 5"),
        CheckConstraint("aspect in ('story','acting','visuals','music','pacing')"),
        Index("ix_aspect_film", "film_id", "aspect"),
    )


class Review(Base):
    __tablename__ = "reviews"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    film_id: Mapped[int] = mapped_column(ForeignKey("films.id", ondelete="CASCADE"), index=True)
    text: Mapped[str] = mapped_column(Text)
    state: Mapped[str] = mapped_column(String(15), default="pending_scan")
    risk: Mapped[float] = mapped_column(Float, default=0.0)
    uncertain: Mapped[bool] = mapped_column(Boolean, default=False)  # in the model's uncertain band
    warn: Mapped[bool] = mapped_column(Boolean, default=False)  # below the blur/moderator bands but above the recall cut-off: readers see "possible spoilers"
    segments_json: Mapped[str] = mapped_column(Text, default="[]")  # scan result
    scan_version: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now)
    __table_args__ = (
        CheckConstraint("state in ('pending_scan','published','hidden','removed')"),
        Index("ix_reviews_film_state", "film_id", "state"),
    )
    author: Mapped[User] = relationship(lazy="joined")


class ReviewReport(Base):
    __tablename__ = "review_reports"
    id: Mapped[int] = mapped_column(primary_key=True)
    review_id: Mapped[int] = mapped_column(ForeignKey("reviews.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    reason: Mapped[str] = mapped_column(String(40), default="spoiler")
    comment: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now)
    __table_args__ = (UniqueConstraint("review_id", "user_id"),)


class Club(Base):
    __tablename__ = "clubs"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    description: Mapped[str] = mapped_column(Text, default="")
    is_public: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now)


class ClubMember(Base):
    __tablename__ = "club_members"
    club_id: Mapped[int] = mapped_column(ForeignKey("clubs.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    role: Mapped[str] = mapped_column(String(12), default="member")
    __table_args__ = (CheckConstraint("role in ('convener','co_convener','member')"),)
    user: Mapped[User] = relationship(lazy="joined")


class ClubWatchlist(Base):
    __tablename__ = "club_watchlist"
    club_id: Mapped[int] = mapped_column(ForeignKey("clubs.id", ondelete="CASCADE"), primary_key=True)
    film_id: Mapped[int] = mapped_column(ForeignKey("films.id", ondelete="CASCADE"), primary_key=True)
    added_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class Poll(Base):
    __tablename__ = "polls"
    id: Mapped[int] = mapped_column(primary_key=True)
    club_id: Mapped[int] = mapped_column(ForeignKey("clubs.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(160))
    state: Mapped[str] = mapped_column(String(10), default="draft")
    deadline: Mapped[Optional[dt.datetime]] = mapped_column(DateTime)
    screening_date: Mapped[Optional[dt.datetime]] = mapped_column(DateTime)
    winner_film_id: Mapped[Optional[int]] = mapped_column(ForeignKey("films.id", ondelete="SET NULL"))
    result_json: Mapped[Optional[str]] = mapped_column(Text)  # frozen at close
    created_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now)
    __table_args__ = (CheckConstraint("state in ('draft','open','closed','cancelled')"),)
    options: Mapped[list["PollOption"]] = relationship(cascade="all, delete-orphan", lazy="selectin")


class PollOption(Base):
    __tablename__ = "poll_options"
    id: Mapped[int] = mapped_column(primary_key=True)
    poll_id: Mapped[int] = mapped_column(ForeignKey("polls.id", ondelete="CASCADE"), index=True)
    film_id: Mapped[int] = mapped_column(ForeignKey("films.id", ondelete="CASCADE"))
    __table_args__ = (UniqueConstraint("poll_id", "film_id"),)


class Vote(Base):
    __tablename__ = "votes"
    id: Mapped[int] = mapped_column(primary_key=True)
    poll_id: Mapped[int] = mapped_column(ForeignKey("polls.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    option_id: Mapped[int] = mapped_column(ForeignKey("poll_options.id", ondelete="CASCADE"))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now)
    __table_args__ = (UniqueConstraint("poll_id", "user_id", name="uq_one_vote_per_member"),)  # one member, one vote


class Follow(Base):
    __tablename__ = "follows"
    follower_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    followee_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    __table_args__ = (CheckConstraint("follower_id != followee_id"),)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[dt.datetime] = mapped_column(DateTime, default=now, index=True)
    actor_id: Mapped[Optional[int]] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String(60), index=True)
    target: Mapped[str] = mapped_column(String(120), default="")
    detail: Mapped[str] = mapped_column(Text, default="")


class Outbox(Base):
    """E-mail queue (also the dev 'mailbox' when no SMTP server is configured)."""
    __tablename__ = "outbox"
    id: Mapped[int] = mapped_column(primary_key=True)
    to_email: Mapped[str] = mapped_column(String(254))
    subject: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(10), default="queued")  # queued | sent | logged | failed
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now)


class PasswordReset(Base):
    """One-time password-reset token. Only the SHA-256 of the token is stored, so a leaked database cannot be used to reset."""
    __tablename__ = "password_resets"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime)
    used_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now)


class Notification(Base):
    """In-app notification shown under the bell. `link` is a front-end path such as /film/12."""
    __tablename__ = "notifications"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(20))
    text: Mapped[str] = mapped_column(String(300))
    link: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now)
    read_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime)
    __table_args__ = (Index("ix_notifications_user", "user_id", "read_at", "id"),)


@event.listens_for(AuditLog, "before_update")
def _audit_no_update(*_a):  # append-only
    raise RuntimeError("audit log is append-only")


@event.listens_for(AuditLog, "before_delete")
def _audit_no_delete(*_a):
    raise RuntimeError("audit log is append-only")


# ------------------------------------------------------------------ community & gamification (added tables only)
LIKE_KINDS = ("review", "list", "thread")


class Like(Base):
    """One generic like/upvote table. To make something new likeable, add its kind to LIKE_KINDS."""
    __tablename__ = "likes"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    kind: Mapped[str] = mapped_column(String(12), primary_key=True)
    target_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now)
    __table_args__ = (Index("ix_likes_target", "kind", "target_id"),)


class UserBadge(Base):
    """A badge stays earned once reached (definitions live in app/gamification.py)."""
    __tablename__ = "user_badges"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    key: Mapped[str] = mapped_column(String(40), primary_key=True)
    earned_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now)


class FilmList(Base):
    __tablename__ = "film_lists"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now)
    author: Mapped["User"] = relationship(lazy="joined")
    items: Mapped[list["FilmListItem"]] = relationship(cascade="all, delete-orphan", lazy="selectin",
                                                       order_by="FilmListItem.position")


class FilmListItem(Base):
    __tablename__ = "film_list_items"
    list_id: Mapped[int] = mapped_column(ForeignKey("film_lists.id", ondelete="CASCADE"), primary_key=True)
    film_id: Mapped[int] = mapped_column(ForeignKey("films.id", ondelete="CASCADE"), primary_key=True)
    position: Mapped[int] = mapped_column(Integer, default=0)


class ClubThread(Base):
    __tablename__ = "club_threads"
    id: Mapped[int] = mapped_column(primary_key=True)
    club_id: Mapped[int] = mapped_column(ForeignKey("clubs.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text, default="")
    tag: Mapped[str] = mapped_column(String(20), default="Discussion")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now)
    author: Mapped["User"] = relationship(lazy="joined")
    replies: Mapped[list["ThreadReply"]] = relationship(cascade="all, delete-orphan", lazy="selectin",
                                                        order_by="ThreadReply.id")


class ThreadReply(Base):
    __tablename__ = "thread_replies"
    id: Mapped[int] = mapped_column(primary_key=True)
    thread_id: Mapped[int] = mapped_column(ForeignKey("club_threads.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now)
    author: Mapped["User"] = relationship(lazy="joined")


class Watchalong(Base):
    __tablename__ = "watchalongs"
    id: Mapped[int] = mapped_column(primary_key=True)
    club_id: Mapped[int] = mapped_column(ForeignKey("clubs.id", ondelete="CASCADE"), index=True)
    film_id: Mapped[int] = mapped_column(ForeignKey("films.id", ondelete="CASCADE"))
    starts_at: Mapped[dt.datetime] = mapped_column(DateTime)
    poll_id: Mapped[Optional[int]] = mapped_column(ForeignKey("polls.id", ondelete="SET NULL"), unique=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))


class WatchalongRsvp(Base):
    __tablename__ = "watchalong_rsvps"
    watchalong_id: Mapped[int] = mapped_column(ForeignKey("watchalongs.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)


# ------------------------------------------------------------------ roles in action: critics, sanctions, goals
class CriticApplication(Base):
    """A viewer's request to be verified as a critic. A moderator or admin decides; approval grants the `critic` role."""
    __tablename__ = "critic_applications"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    statement: Mapped[str] = mapped_column(Text)
    links: Mapped[str] = mapped_column(String(300), default="")
    state: Mapped[str] = mapped_column(String(10), default="pending")
    decided_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    decision_note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now)
    decided_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime)
    __table_args__ = (CheckConstraint("state in ('pending','approved','rejected','withdrawn')"),)


class CriticPick(Base):
    """A critic's one-line recommendation of a film. Only holders of `critic.pick` can write one."""
    __tablename__ = "critic_picks"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    film_id: Mapped[int] = mapped_column(ForeignKey("films.id", ondelete="CASCADE"), primary_key=True)
    blurb: Mapped[str] = mapped_column(String(280))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now)
    __table_args__ = (Index("ix_critic_picks_recent", "created_at"),)


class UserStrike(Base):
    """A moderator's formal warning. Three within 30 days mute the account for three days."""
    __tablename__ = "user_strikes"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    issued_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    review_id: Mapped[Optional[int]] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(300))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now)


class WatchGoal(Base):
    """'I want to watch N films in YEAR'."""
    __tablename__ = "watch_goals"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    year: Mapped[int] = mapped_column(Integer, primary_key=True)
    target: Mapped[int] = mapped_column(Integer)
    __table_args__ = (CheckConstraint("target >= 1 and target <= 1000"),)
