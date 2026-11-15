"""Check that this machine can reach TMDB with the key in .env, and that search + import work end to end.

    python -m scripts.check_tmdb            (or double-click check_tmdb.bat)
"""
from __future__ import annotations

import sys
import time

import httpx

from app.config import Settings
from app.clients.tmdb import BASE, TMDBClient, TMDBError


def main() -> int:
    key = Settings().tmdb_api_key
    if not key:
        print("FAIL  TMDB_API_KEY is empty. Put it in backend\\.env as TMDB_API_KEY=... and restart.")
        return 1
    print(f"key: {key[:4]}...{key[-4:]} ({len(key)} chars)")
    try:
        t0 = time.time()
        r = httpx.get(f"{BASE}/configuration", params={"api_key": key}, timeout=15)
        print(f"GET /configuration -> HTTP {r.status_code} in {time.time() - t0:.1f}s")
        if r.status_code == 401:
            print("FAIL  TMDB rejected the key (401). Check it at themoviedb.org > Settings > API; use the 'API Key (v3 auth)' value,"
                  " not the long 'Read Access Token'.")
            return 1
    except httpx.HTTPError as exc:
        print(f"FAIL  could not reach api.themoviedb.org: {exc!r}\n"
              "      Check the internet connection, a VPN/proxy/firewall, or the college network blocking TMDB.")
        return 1
    c = TMDBClient(key)
    ok = True
    for q in ("dune", "oppenheimer", "a title that surely does not exist 12345"):
        try:
            res = c.search(q)
            top = ", ".join(f"{m.get('title')} ({(m.get('release_date') or '?')[:4]})" for m in res[:3]) or "no results"
            print(f"search {q!r}: {len(res)} results; top: {top}")
        except TMDBError as exc:
            ok = False
            print(f"FAIL  search {q!r}: {exc}")
    try:
        first = c.search("dune")[0]
        d = c.details(first["id"])
        print(f"details {first['id']}: {d.get('title')} - {len(d.get('credits', {}).get('cast', []))} cast, "
              f"{len((d.get('keywords') or {}).get('keywords', []))} keywords, poster={'yes' if d.get('poster_path') else 'no'}")
        for name, feed in (("now_playing", c.now_playing), ("upcoming", c.upcoming)):
            print(f"{name}: {len(feed(1))} films")
    except (TMDBError, IndexError) as exc:
        ok = False
        print(f"FAIL  details/feeds: {exc!r}")
    print("RESULT:", "TMDB works - search for any film in the site's search box and it will be imported." if ok else "something failed, see above")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
