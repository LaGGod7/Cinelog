from __future__ import annotations

import datetime as dt
import secrets
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import audit
from ..models import AVATARS, Outbox, PasswordReset, User, UserRole, now
from ..rbac import get_db, get_wdb, permissions_of, user_required
from ..security import (CSRF_COOKIE, SESSION_COOKIE, hash_password, hash_reset_token, make_token, new_csrf,
                        new_reset_token, verify_password)
from ..services import jobs
from ..services.notifications import notify

router = APIRouter(prefix="/auth", tags=["auth"])


class Register(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    display_name: str = Field(min_length=1, max_length=80)


class Login(BaseModel):
    email: EmailStr
    password: str = Field(max_length=128)


def user_json(u: User) -> dict:
    roles = sorted(u.role_names)
    return {"id": u.id, "email": u.email, "display_name": u.display_name, "roles": roles,
            "permissions": sorted(permissions_of(set(roles))), "email_opt_out": u.email_opt_out,
            "bio": u.bio or "", "avatar": u.avatar or "", "has_password": bool(u.password_hash),
            "spoiler_safe": bool(u.spoiler_safe if u.spoiler_safe is not None else True),
            "muted_until": u.muted_until.isoformat() if u.muted_until and u.muted_until > dt.datetime.utcnow() else None}


def start_session(resp: Response, user: User, request: Request) -> str:
    s = request.app.state.settings
    csrf = new_csrf()
    resp.set_cookie(SESSION_COOKIE, make_token(user.id, s), httponly=True, secure=s.cookie_secure, samesite="lax",
                    max_age=s.session_hours * 3600, path="/")
    resp.set_cookie(CSRF_COOKIE, csrf, httponly=False, secure=s.cookie_secure, samesite="lax",
                    max_age=s.session_hours * 3600, path="/")
    return csrf


@router.post("/register", status_code=201)
def register(body: Register, request: Request, response: Response, db: Session = Depends(get_db)):
    email = body.email.lower()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(409, "email already registered")
    first = db.scalar(select(User.id).limit(1)) is None
    u = User(email=email, display_name=body.display_name.strip(),
             password_hash=hash_password(body.password, request.app.state.settings.bcrypt_rounds))
    u.roles = [UserRole(role="viewer")] + ([UserRole(role="admin")] if first else [])  # first account owns the install
    db.add(u); db.flush()
    audit(db, u.id, "user.register", f"user:{u.id}", "first user -> admin" if first else "")
    csrf = start_session(response, u, request)
    return {"user": user_json(u), "csrf": csrf}


@router.post("/login")
def login(body: Login, request: Request, response: Response, db: Session = Depends(get_db)):
    u = db.scalar(select(User).where(User.email == body.email.lower()))
    if u is None or not verify_password(body.password, u.password_hash):
        raise HTTPException(401, "invalid email or password")  # generic: never reveal which part was wrong
    csrf = start_session(response, u, request)
    return {"user": user_json(u), "csrf": csrf}


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")
    return {"ok": True}


@router.get("/me")
def me(user: User = Depends(user_required)):
    return user_json(user)


class Profile(BaseModel):
    display_name: Optional[str] = Field(None, min_length=1, max_length=80)
    email_opt_out: Optional[bool] = None
    bio: Optional[str] = Field(None, max_length=300)
    avatar: Optional[str] = Field(None, max_length=20)
    spoiler_safe: Optional[bool] = None


@router.patch("/me")
def update_me(body: Profile, user: User = Depends(user_required), db: Session = Depends(get_db)):
    u = db.get(User, user.id)
    if body.display_name is not None:
        u.display_name = body.display_name.strip()
    if body.bio is not None:
        u.bio = " ".join(body.bio.split())  # one tidy paragraph: no stray newlines or runs of spaces
    if body.avatar is not None:
        if body.avatar and body.avatar not in AVATARS:
            raise HTTPException(400, f"avatar must be one of: {', '.join(AVATARS)} (or empty)")
        u.avatar = body.avatar
    if body.email_opt_out is not None:
        u.email_opt_out = body.email_opt_out
    if body.spoiler_safe is not None:
        u.spoiler_safe = body.spoiler_safe
    return user_json(u)


# ---------------------------------------------------------------- password reset & change
RESET_MINUTES = 60
RESET_COOLDOWN_SECONDS = 60  # at most one reset e-mail per account per minute: nobody can be mail-bombed through us


class Forgot(BaseModel):
    email: EmailStr


class Reset(BaseModel):
    token: str = Field(min_length=20, max_length=100)
    password: str = Field(min_length=8, max_length=128)


@router.post("/forgot")
def forgot(body: Forgot, request: Request, db: Session = Depends(get_db)):
    """Always answers the same way, so the form cannot be used to find out who has an account."""
    u = db.scalar(select(User).where(User.email == body.email.lower()))
    if u is not None:
        recent = db.scalar(select(PasswordReset.id).where(
            PasswordReset.user_id == u.id,
            PasswordReset.created_at > now() - dt.timedelta(seconds=RESET_COOLDOWN_SECONDS)))
        if recent is None:
            tok, hashed = new_reset_token()
            db.add(PasswordReset(user_id=u.id, token_hash=hashed, expires_at=now() + dt.timedelta(minutes=RESET_MINUTES)))
            link = f"{request.app.state.settings.frontend_url.rstrip('/')}/reset?token={tok}"
            o = Outbox(to_email=u.email, subject="Reset your CineLog password",
                       body=f"Someone asked to reset the password for this CineLog account.\n\nOpen this link within "
                            f"{RESET_MINUTES} minutes to choose a new password:\n{link}\n\nIf it was not you, ignore this "
                            "message; your password stays as it is.")  # security mail ignores the marketing opt-out
            db.add(o); db.flush()
            audit(db, u.id, "user.reset_requested", f"user:{u.id}")
            db.commit()
            jobs.dispatch_emails(request.app, [o.id])
    return {"ok": True, "message": "If that address has an account, a reset link is on its way."}


@router.post("/reset")
def reset_password(body: Reset, request: Request, db: Session = Depends(get_db)):
    row = db.scalar(select(PasswordReset).where(PasswordReset.token_hash == hash_reset_token(body.token)))
    if row is None or row.used_at is not None or row.expires_at < now():
        raise HTTPException(400, "this reset link is invalid or has expired; ask for a new one")
    u = db.get(User, row.user_id)
    u.password_hash = hash_password(body.password, request.app.state.settings.bcrypt_rounds)
    u.password_changed_at = now()
    for other in db.scalars(select(PasswordReset).where(PasswordReset.user_id == u.id, PasswordReset.used_at.is_(None))):
        other.used_at = now()  # one successful reset retires every outstanding link
    audit(db, u.id, "user.password_reset", f"user:{u.id}")
    notify(db, u.id, "security", "Your password was changed. If this wasn't you, reset it again right away.")
    return {"ok": True}


class ChangePassword(BaseModel):
    current_password: str = Field("", max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


@router.post("/change-password")
def change_password(body: ChangePassword, request: Request, response: Response, user: User = Depends(user_required),
                    db: Session = Depends(get_db)):
    u = db.get(User, user.id)
    if u.password_hash and not verify_password(body.current_password, u.password_hash):
        raise HTTPException(403, "current password is wrong")
    u.password_hash = hash_password(body.new_password, request.app.state.settings.bcrypt_rounds)
    u.password_changed_at = now()  # every other device is signed out; this one gets a fresh session below
    audit(db, u.id, "user.password_change", f"user:{u.id}")
    csrf = start_session(response, u, request)
    return {"ok": True, "csrf": csrf}


# ---------------------------------------------------------------- Google OAuth 2.0 (authorisation-code flow)
def _google_exchange(request: Request, code: str) -> dict:
    s = request.app.state.settings
    with httpx.Client(timeout=15) as http:
        tok = http.post("https://oauth2.googleapis.com/token", data={
            "code": code, "client_id": s.google_client_id, "client_secret": s.google_client_secret,
            "redirect_uri": s.google_redirect_uri, "grant_type": "authorization_code"})
        if tok.status_code != 200:
            raise HTTPException(400, "google token exchange failed")
        info = http.get("https://oauth2.googleapis.com/tokeninfo", params={"id_token": tok.json()["id_token"]})
        if info.status_code != 200:
            raise HTTPException(400, "google id token rejected")
        d = info.json()
        if d.get("aud") != s.google_client_id or d.get("email_verified") not in (True, "true"):
            raise HTTPException(400, "google identity not verified")
        return {"sub": d["sub"], "email": d["email"], "name": d.get("name") or d["email"].split("@")[0]}


@router.get("/google/login")
def google_login(request: Request):
    s = request.app.state.settings
    if not s.google_client_id:
        raise HTTPException(501, "Google sign-in is not configured; use email sign-in")
    state = secrets.token_urlsafe(16)
    url = ("https://accounts.google.com/o/oauth2/v2/auth?response_type=code&scope=openid%20email%20profile"
           f"&client_id={s.google_client_id}&redirect_uri={s.google_redirect_uri}&state={state}")
    resp = RedirectResponse(url)
    resp.set_cookie("cl_oauth_state", state, httponly=True, samesite="lax", max_age=600, secure=s.cookie_secure)
    return resp


@router.get("/google/callback")
def google_callback(request: Request, code: str, state: str, db: Session = Depends(get_wdb)):
    if not state or state != request.cookies.get("cl_oauth_state"):
        raise HTTPException(400, "oauth state mismatch")
    ex = request.app.state.google_exchange or (lambda c: _google_exchange(request, c))
    info = ex(code)
    u = db.scalar(select(User).where(User.google_sub == info["sub"])) or \
        db.scalar(select(User).where(User.email == info["email"].lower()))
    if u is None:
        u = User(email=info["email"].lower(), display_name=info["name"], google_sub=info["sub"])
        u.roles = [UserRole(role="viewer")]  # first Google sign-in creates a Viewer
        db.add(u); db.flush()
        audit(db, u.id, "user.register", f"user:{u.id}", "google")
    elif not u.google_sub:
        u.google_sub = info["sub"]
    resp = RedirectResponse(request.app.state.settings.frontend_url)
    start_session(resp, u, request)
    resp.delete_cookie("cl_oauth_state")
    return resp
