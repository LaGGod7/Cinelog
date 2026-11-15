"""Authentication & traffic control (CN & Security engine)."""
from __future__ import annotations

import hashlib
import ipaddress
import secrets
import threading
import time
from typing import Dict, Optional, Sequence, Tuple

import bcrypt
import jwt

from .config import Settings

SESSION_COOKIE = "cl_session"
CSRF_COOKIE = "cl_csrf"


def hash_password(pw: str, rounds: int = 12) -> str:
    return bcrypt.hashpw(pw.encode()[:72], bcrypt.gensalt(rounds)).decode()


def verify_password(pw: str, hashed: Optional[str]) -> bool:
    if not hashed:
        return False
    try:
        return bcrypt.checkpw(pw.encode()[:72], hashed.encode())
    except ValueError:
        return False


def make_token(user_id: int, settings: Settings) -> str:
    now = int(time.time())
    return jwt.encode({"sub": str(user_id), "iat": now, "exp": now + settings.session_hours * 3600},
                      settings.secret_key, algorithm="HS256")


def read_token_full(token: str, settings: Settings) -> Optional[Tuple[int, int]]:
    """(user id, issued-at seconds) of a valid session token, else None."""
    try:
        data = jwt.decode(token, settings.secret_key, algorithms=["HS256"])  # alg pinned: no "none" attack
        return int(data["sub"]), int(data.get("iat", 0))
    except (jwt.PyJWTError, KeyError, ValueError):
        return None


def read_token(token: str, settings: Settings) -> Optional[int]:
    got = read_token_full(token, settings)
    return got[0] if got else None


def new_reset_token() -> Tuple[str, str]:
    """(token to e-mail, hash to store)."""
    tok = secrets.token_urlsafe(32)
    return tok, hash_reset_token(tok)


def hash_reset_token(tok: str) -> str:
    return hashlib.sha256(tok.encode()).hexdigest()


def client_ip(peer: Optional[str], forwarded_for: Optional[str], trusted: Sequence[str]) -> str:
    """Real client address. X-Forwarded-For is believed only when the direct peer is one of our own proxies,
    and then the right-most entry that is not itself a trusted proxy is taken (the left side can be forged)."""
    if not peer:
        return "?"
    nets = []
    for t in trusted:
        try:
            nets.append(ipaddress.ip_network(t.strip(), strict=False))
        except ValueError:
            continue

    def is_trusted(a: str) -> bool:
        try:
            ip = ipaddress.ip_address(a)
        except ValueError:
            return False
        return any(ip in n for n in nets if n.version == ip.version)

    if not forwarded_for or not is_trusted(peer):
        return peer
    for hop in reversed([h.strip() for h in forwarded_for.split(",") if h.strip()]):
        if not is_trusted(hop):
            try:
                ipaddress.ip_address(hop)
            except ValueError:
                return peer  # garbage header: fall back to the peer
            return hop
    return peer


def new_csrf() -> str:
    return secrets.token_urlsafe(24)


class TokenBucket:
    """Token-bucket limiter keyed by e.g. client IP or user id."""

    def __init__(self, capacity: float, refill_per_sec: float, clock=time.monotonic) -> None:
        self.capacity, self.rate, self.clock = capacity, refill_per_sec, clock
        self._b: Dict[str, Tuple[float, float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str, cost: float = 1.0) -> bool:
        with self._lock:
            now = self.clock()
            tokens, last = self._b.get(key, (self.capacity, now))
            tokens = min(self.capacity, tokens + (now - last) * self.rate)
            ok = tokens >= cost
            if ok:
                tokens -= cost
            self._b[key] = (tokens, now)
            if len(self._b) > 50_000:  # bound memory
                self._b.clear()
            return ok
