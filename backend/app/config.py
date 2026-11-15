from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field


def _load_dotenv(path: str = ".env") -> None:
    """Tiny .env reader (KEY=VALUE lines); real environment variables win."""
    try:
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.split(" #")[0].strip().strip('"').strip("'"))
    except OSError:
        pass


_load_dotenv()


def _b(name: str, default: bool) -> bool:
    v = os.getenv(name)
    return default if v is None else v.lower() in ("1", "true", "yes", "on")


def _secret_key(path: str | None = None) -> str:
    """SECRET_KEY from the environment, else a random key generated once and kept in a file (never a public default)."""
    env = os.getenv("SECRET_KEY", "").strip()
    if env and not env.startswith("change-me"):
        return env
    path = path or os.getenv("SECRET_KEY_FILE", ".secret_key")
    try:
        with open(path, encoding="utf-8") as fh:
            saved = fh.read().strip()
        if len(saved) >= 32:
            return saved
    except OSError:
        pass
    key = secrets.token_urlsafe(48)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(key)
    except OSError:
        pass  # read-only disk: the key lasts for this run only (sessions end on restart)
    return key


@dataclass
class Settings:
    database_url: str = field(default_factory=lambda: os.getenv("DATABASE_URL", "sqlite:///./cinelog.db"))
    secret_key: str = field(default_factory=lambda: _secret_key())
    session_hours: int = field(default_factory=lambda: int(os.getenv("SESSION_HOURS", "8")))
    cookie_secure: bool = field(default_factory=lambda: _b("COOKIE_SECURE", False))
    force_https: bool = field(default_factory=lambda: _b("FORCE_HTTPS", False))
    bcrypt_rounds: int = field(default_factory=lambda: int(os.getenv("BCRYPT_ROUNDS", "12")))
    cors_origins: list = field(default_factory=lambda: os.getenv("CORS_ORIGINS", "http://localhost:5173").split(","))
    # rate limits (token bucket)
    login_per_minute: int = field(default_factory=lambda: int(os.getenv("LOGIN_PER_MINUTE", "5")))
    api_burst: int = field(default_factory=lambda: int(os.getenv("API_BURST", "120")))
    api_rate: float = field(default_factory=lambda: float(os.getenv("API_RATE", "30")))
    # external services
    tmdb_api_key: str = field(default_factory=lambda: os.getenv("TMDB_API_KEY", ""))
    tmdb_rate: float = field(default_factory=lambda: float(os.getenv("TMDB_RATE", "30")))
    google_client_id: str = field(default_factory=lambda: os.getenv("GOOGLE_CLIENT_ID", ""))
    google_client_secret: str = field(default_factory=lambda: os.getenv("GOOGLE_CLIENT_SECRET", ""))
    google_redirect_uri: str = field(default_factory=lambda: os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:8000/api/auth/google/callback"
                                                                       if os.getenv("SERVE_FRONTEND", "0") == "1" else
                                                                       "http://localhost:8000/auth/google/callback"))
    serve_frontend: bool = field(default_factory=lambda: os.getenv("SERVE_FRONTEND", "0") == "1")
    frontend_dist: str = field(default_factory=lambda: os.getenv("FRONTEND_DIST", os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "frontend", "dist")))
    frontend_url: str = field(default_factory=lambda: os.getenv("FRONTEND_URL", "http://localhost:5173"))
    smtp_host: str = field(default_factory=lambda: os.getenv("SMTP_HOST", ""))
    smtp_port: int = field(default_factory=lambda: int(os.getenv("SMTP_PORT", "587")))
    smtp_user: str = field(default_factory=lambda: os.getenv("SMTP_USER", ""))
    smtp_password: str = field(default_factory=lambda: os.getenv("SMTP_PASSWORD", ""))
    smtp_from: str = field(default_factory=lambda: os.getenv("SMTP_FROM", "cinelog@localhost"))
    # engine knobs
    workers: int = field(default_factory=lambda: int(os.getenv("WORKERS", "4")))
    queue_capacity: int = field(default_factory=lambda: int(os.getenv("QUEUE_CAPACITY", "256")))
    model_dir: str = field(default_factory=lambda: os.getenv("MODEL_DIR", "models"))
    use_dl: bool = field(default_factory=lambda: _b("USE_DL", False))  # the ONNX cross-encoder; off until it beats the ML model
    # who may tell us the real client address (X-Forwarded-For): loopback + private networks (dev proxy, docker, nginx)
    trusted_proxies: list = field(default_factory=lambda: os.getenv(
        "TRUSTED_PROXIES", "127.0.0.0/8,::1/128,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16").split(","))
    report_threshold: int = 3
    start_workers: bool = True
    bootstrap_admin_email: str = field(default_factory=lambda: os.getenv("ADMIN_EMAIL", ""))
    bootstrap_admin_password: str = field(default_factory=lambda: os.getenv("ADMIN_PASSWORD", ""))
