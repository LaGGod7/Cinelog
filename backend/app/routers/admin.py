from __future__ import annotations


from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..audit import audit
from ..models import AuditLog, Outbox, ROLES, User, UserRole, UserStrike
from ..rbac import CLUB_INFO, CLUB_MATRIX, MATRIX, PERMISSION_INFO, RANK, ROLE_INFO, get_db, rank_of, require_perm
from ..services.notifications import notify
from ..services import jobs
from .auth import user_json

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/users")
def users(q: str = "", db: Session = Depends(get_db), _: User = Depends(require_perm("role.manage"))):
    stmt = select(User).order_by(User.id).limit(50)
    if q:
        stmt = select(User).where(User.email.ilike(f"%{q}%") | User.display_name.ilike(f"%{q}%")).limit(50)
    rows = list(db.scalars(stmt))
    strikes = dict(db.execute(select(UserStrike.user_id, func.count()).where(UserStrike.user_id.in_([u.id for u in rows] or [0]))
                              .group_by(UserStrike.user_id)).all())
    return [{**user_json(u), "strikes": strikes.get(u.id, 0)} for u in rows]


class RoleChange(BaseModel):
    role: str
    action: str  # grant | revoke
    reason: str = Field("", max_length=200)


@router.post("/users/{uid}/roles")
def change_role(uid: int, body: RoleChange, admin: User = Depends(require_perm("role.manage")),
                db: Session = Depends(get_db)):
    if body.role not in ROLES or body.action not in ("grant", "revoke"):
        raise HTTPException(400, "unknown role or action")
    u = db.get(User, uid)
    if u is None:
        raise HTTPException(404, "user not found")
    have = body.role in u.role_names
    if body.action == "grant" and not have:
        u.roles.append(UserRole(user_id=u.id, role=body.role))
    elif body.action == "revoke" and have:
        if body.role == "admin":
            admins = db.scalar(select(func.count()).select_from(UserRole).where(UserRole.role == "admin"))
            if admins <= 1:
                raise HTTPException(409, "cannot remove the last admin")
        if body.role == "viewer":
            raise HTTPException(409, "the viewer role is the base role and cannot be revoked")
        u.roles = [r for r in u.roles if r.role != body.role]
    db.flush()
    audit(db, admin.id, f"role.{body.action}", f"user:{u.id}", f"{body.role}: {body.reason.strip()}" if body.reason.strip() else body.role)
    notify(db, u.id, "role", f"You were {'given' if body.action == 'grant' else 'removed from'} the {body.role} role"
           + (f" ({body.reason.strip()})" if body.reason.strip() else ""), "/me", admin.id)
    db.flush()
    return user_json(u)  # applies on the user's next request: roles are read from the DB each time


@router.get("/audit")
def audit_log(limit: int = 100, prefix: str = "", db: Session = Depends(get_db), _: User = Depends(require_perm("audit.read"))):
    stmt = select(AuditLog).order_by(AuditLog.id.desc()).limit(max(1, min(limit, 500)))
    if prefix:
        stmt = stmt.where(AuditLog.action.like(prefix.replace("%", "").replace("_", "\\_") + "%", escape="\\"))
    rows = db.scalars(stmt)
    return [{"id": a.id, "at": a.at.isoformat(), "actor": a.actor_id, "action": a.action, "target": a.target,
             "detail": a.detail} for a in rows]


@router.post("/sync", status_code=202)
def sync(request: Request, pages: int = 5, _: User = Depends(require_perm("catalog.sync"))):
    if request.app.state.tmdb is None:
        raise HTTPException(503, "TMDB_API_KEY is not configured")
    jobs.submit_sync(request.app, max(1, min(pages, 500)))
    return {"queued": True, "pages": pages}


@router.get("/stats")
def stats(request: Request, db: Session = Depends(get_db), _: User = Depends(require_perm("audit.read"))):
    st = request.app.state
    return {"queue_depth": len(st.pool.queue), "jobs": st.pool.stats, "failed_jobs": st.pool.failed_jobs[-20:],
            "sync": st.sync_status, "tmdb": {"configured": st.tmdb is not None, **st.tmdb_status}, "films_indexed": st.search.size, "shield": st.shield.status(),
            "outbox": {s: n for s, n in db.execute(select(Outbox.status, func.count()).group_by(Outbox.status))}}


@router.post("/model/reload")
def reload_model(request: Request, _: User = Depends(require_perm("model.manage"))):
    st = request.app.state
    status = st.shield.reload(st.settings.model_dir)
    jobs.refit_shield_space(request.app)
    return status


@router.get("/outbox")
def outbox(limit: int = 30, db: Session = Depends(get_db), _: User = Depends(require_perm("role.manage"))):
    """The dev mailbox. With no SMTP server configured, e-mails (password-reset links!) can be read here. Admin only."""
    rows = db.scalars(select(Outbox).order_by(Outbox.id.desc()).limit(max(1, min(limit, 100))))
    return [{"id": o.id, "to": o.to_email, "subject": o.subject, "body": o.body, "status": o.status,
             "at": o.created_at.isoformat()} for o in rows]


@router.get("/permissions")
def permissions(db: Session = Depends(get_db), _: User = Depends(require_perm("audit.read"))):
    """The access-control table as the server enforces it (read from the same MATRIX the routes use)."""
    counts = dict(db.execute(select(UserRole.role, func.count()).group_by(UserRole.role)).all())
    perms = [{"key": k, "group": PERMISSION_INFO.get(k, ("Other", ""))[0], "description": PERMISSION_INFO.get(k, ("", k))[1],
              "roles": sorted(holders, key=RANK.index)} for k, holders in MATRIX.items()]
    order = ["Everyday use", "Clubs", "Spoiler shield", "Critics", "Moderation", "Administration", "Other"]
    perms.sort(key=lambda p: (order.index(p["group"]) if p["group"] in order else 99, p["key"]))
    return {"roles": [{"name": r, "description": ROLE_INFO[r], "people": counts.get(r, 0)} for r in RANK],
            "permissions": perms,
            "club_roles": ["convener", "co_convener", "member"],
            "club_actions": [{"key": k, "description": CLUB_INFO[k], "roles": [r for r in ("convener", "co_convener", "member") if r in holders]}
                             for k, holders in CLUB_MATRIX.items()],
            "rules": ["A person's rights are the union of their roles' permissions; anything not listed is denied.",
                      "Club roles only apply inside that club and are separate from site roles.",
                      "Nobody can decide their own critic application; nobody can sanction someone of an equal or higher role.",
                      "The last admin cannot be removed. Every role change, decision and sanction is written to the audit log."]}


@router.get("/users/{uid}/standing")
def standing(uid: int, db: Session = Depends(get_db), _: User = Depends(require_perm("role.manage"))):
    u = db.get(User, uid)
    if u is None:
        raise HTTPException(404, "user not found")
    strikes = db.scalar(select(func.count()).select_from(UserStrike).where(UserStrike.user_id == uid)) or 0
    return {"id": u.id, "rank": rank_of(u.role_names), "strikes": strikes, "muted_until": u.muted_until.isoformat() if u.muted_until else None}
