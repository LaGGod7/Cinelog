"""Serve the built website (frontend/dist) from the API process, so the whole site runs on ONE port and the browser
loads a few small pre-built files instead of the development server's hundreds of separate modules.

Only active when SERVE_FRONTEND=1 (start_site.bat sets it). Then:
  /api/...   -> the API (the prefix is removed before routing; the front end already calls /api/...)
  anything else -> a file from dist, or index.html (so a browser refresh on /films/12 still works)
"""
from __future__ import annotations

from pathlib import Path

from starlette.responses import FileResponse, PlainTextResponse

CSP = "default-src 'self'; img-src 'self' https://image.tmdb.org data:; style-src 'self' 'unsafe-inline'"
HEADERS = {"X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY", "Referrer-Policy": "same-origin"}


class SPAMiddleware:
    def __init__(self, app, dist: Path) -> None:
        self.app = app
        self.dist = Path(dist).resolve()
        self.index = self.dist / "index.html"

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            return await self.app(scope, receive, send)
        path = scope["path"]
        if path == "/api" or path.startswith("/api/"):
            scope = dict(scope)
            scope["path"] = path[4:] or "/"
            raw = scope.get("raw_path")
            if raw and raw.startswith(b"/api"):
                scope["raw_path"] = raw[4:] or b"/"
            return await self.app(scope, receive, send)
        if scope["type"] == "websocket":
            return await self.app(scope, receive, send)
        if scope["method"] not in ("GET", "HEAD"):
            return await PlainTextResponse("not found", status_code=404)(scope, receive, send)
        return await self._static(path)(scope, receive, send)

    def _static(self, path: str):
        rel = path.lstrip("/")
        target = (self.dist / rel).resolve() if rel else self.index
        inside = target == self.dist or self.dist in target.parents  # no ../ escapes
        if inside and target.is_file():
            if target == self.index:
                return FileResponse(self.index, headers={"Cache-Control": "no-cache", "Content-Security-Policy": CSP, **HEADERS})
            if rel.startswith(("assets/", "fonts/")):  # file names carry a content hash: cache for a year
                cache = "public, max-age=31536000, immutable"
            else:
                cache = "no-cache"
            return FileResponse(target, headers={"Cache-Control": cache, **HEADERS})
        if "." in rel.rsplit("/", 1)[-1]:  # a missing file (favicon, map...), not an app page
            return PlainTextResponse("not found", status_code=404)
        return FileResponse(self.index, headers={"Cache-Control": "no-cache", "Content-Security-Policy": CSP, **HEADERS})
