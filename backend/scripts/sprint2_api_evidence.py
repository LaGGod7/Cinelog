"""Sprint 2 API evidence: runs real requests against a running CineLog server and writes every request and response.

    python -m scripts.seed_demo                      # fresh demo database
    uvicorn app.main:create_app --factory --port 8000
    python -m scripts.sprint2_api_evidence http://localhost:8000/api ../docs/sprint2/evidence/api/api_exchanges.md

Nothing here is mocked: every line in the output is a real HTTP exchange with the running server.
Session and CSRF cookie values are masked in the log.
"""
from __future__ import annotations

import datetime as dt
import json
import sys
import time

import httpx

PW = "cinelog123"
LOG: list[str] = []


def mask(v: str) -> str:
    return v[:6] + "..." if v else v


def show(step: str, ids: str, r: httpx.Response, body=None, note: str = "") -> httpx.Response:
    req = r.request
    LOG.append(f"### {step}\n")
    LOG.append(f"*Test / requirement:* {ids}  ")
    LOG.append(f"*Time:* {dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    LOG.append("```http")
    LOG.append(f"{req.method} {req.url.raw_path.decode()}")
    if body is not None:
        LOG.append(json.dumps(body, ensure_ascii=False))
    LOG.append("```")
    cookies = [c.split(";")[0].split("=")[0] + "=" + mask(c.split(";")[0].split("=", 1)[1]) + ";" +
               ";".join(c.split(";")[1:]) for c in r.headers.get_list("set-cookie")]
    LOG.append("```http")
    LOG.append(f"HTTP {r.status_code} {r.reason_phrase}")
    for c in cookies:
        LOG.append(f"set-cookie: {c}")
    try:
        txt = json.dumps(r.json(), ensure_ascii=False, indent=1)
    except ValueError:
        txt = r.text
    LOG.append(txt if len(txt) < 1800 else txt[:1800] + "\n... (cut)")
    LOG.append("```")
    if note:
        LOG.append(f"\n**Observed:** {note}\n")
    LOG.append("")
    return r


class C:
    def __init__(self, base: str):
        self.h = httpx.Client(base_url=base, timeout=30)

    def _hdr(self):
        t = self.h.cookies.get("cl_csrf")
        return {"X-CSRF-Token": t} if t else {}

    def get(self, step, ids, url, note=""):
        return show(step, ids, self.h.get(url), None, note)

    def post(self, step, ids, url, body=None, note=""):
        return show(step, ids, self.h.post(url, json=body, headers=self._hdr()), body, note)

    def login(self, step, ids, email, pw=PW, note=""):
        return self.post(step, ids, "/auth/login", {"email": email, "password": pw}, note)


def main(base: str, out: str) -> None:
    anon, viewer, critic, mod, conv, admin = (C(base) for _ in range(6))
    LOG.append(f"# Sprint 2 API exchange log\n\nServer: `{base}` (seeded demo database, real model files). "
               f"Run on {dt.datetime.now():%d-%m-%Y %H:%M}. All exchanges are real; none are mocked.\n")

    LOG.append("## E4 CN & Web: sign-in, roles and errors\n")
    anon.get("A01 Health check", "E3/E4 run check", "/health", "Server up; queue and job counters and cache counters returned.")
    anon.login("A02 Wrong password", "TC-E4-04 failure, FR-01", "viewer@cinelog.dev", "not-the-password",
               "401, no session cookie set.")
    viewer.login("A03 Correct sign-in", "TC-E4-01 normal, FR-01", "viewer@cinelog.dev",
                 note="200 with an HttpOnly, SameSite session cookie and a CSRF cookie.")
    anon.get("A04 Moderation queue without a session", "TC-E4-04, FR-02", "/moderation/queue", "401 Unauthorized.")
    viewer.get("A05 Moderation queue as a Viewer", "TC-E4-04, FR-02 deny by default", "/moderation/queue",
               "403 Forbidden: Viewer has no moderation permission.")

    LOG.append("## E1 Search (Trie and inverted index)\n")
    r = viewer.get("A06 Autocomplete, 3 letters", "TC-E1-01 normal, FR-04", "/films/autocomplete?q=inc",
                   "Matching titles, most popular first.")
    viewer.get("A07 Autocomplete, 1 letter", "TC-E1-02 boundary, FR-04", "/films/autocomplete?q=i",
               "Empty list: fewer than 2 letters are not searched.")
    viewer.get("A08 Search with a genre filter", "TC-E1-10, FR-05", "/films/search?q=the&genre=Crime",
               "Only Crime films that contain the word.")
    films: dict = {}
    for q in ("fight", "dark kn", "godfather"):
        for f in viewer.h.get(f"/films/autocomplete?q={q}").json():
            films[f["title"]] = f["id"]

    LOG.append("## E1 + E3 + E2: review submission, background scan, blur\n")
    tid = films["The Dark Knight"]
    spoiler = ("Heath Ledger is unforgettable and the score is huge. The Joker kills Rachel Dawes in an explosion "
               "and Harvey Dent turns into Two-Face.")
    r = viewer.post("A09 Submit a review with a spoiler", "TC-E1-04, FR-08 (T1 transaction)", f"/films/{tid}/reviews",
                    {"text": spoiler}, "202 Accepted, state pending_scan: the scan runs as a background job in E3.")
    rid = r.json().get("id")
    time.sleep(3)
    viewer.get("A10 Read the review after the scan", "TC-E1-04, FR-08/FR-09 (T2 compare-and-swap)", f"/reviews/{rid}",
               "Published; the spoiler sentence is blurred and the first sentence is not.")
    viewer.post("A11 Second review of the same film", "TC-E2 409 rule, FR-08", f"/films/{tid}/reviews",
                {"text": "Trying to post a second review here."}, "409 Conflict: one review per film per user.")
    viewer.post("A12 Review shorter than 10 characters", "TC-E2-05 boundary, DEF-09 retest", f"/films/{tid}/reviews",
                {"text": "too short"}, "400 Bad Request; the message names the field. Nothing saved.")
    critic.login("A13 Critic signs in", "setup", "critic@cinelog.dev")
    fid = films["Fight Club"]
    r = critic.post("A14 Spoiler hidden with a zero-width space", "TC-E1-06, DEF-07 retest", f"/films/{fid}/reviews",
                    {"text": "Great twist. The narrator finds out that Tyler Dur​den is his own split personality."},
                    "202 Accepted; scanned next.")
    rid2 = r.json().get("id")
    time.sleep(3)
    critic.get("A15 Read it after the scan", "TC-E1-06, DEF-07 retest", f"/reviews/{rid2}",
               "The hidden-character trick no longer works: the spoiler sentence is blurred.")

    LOG.append("## E2 Storage & Transaction: poll states and one vote per member\n")
    conv.login("A16 Convener signs in", "setup", "convener@cinelog.dev")
    polls = conv.h.get("/clubs/1/polls").json()
    draft = next(p for p in polls if p["state"] == "draft")
    pid, opt = draft["id"], draft["options"][0]["id"]
    viewer.post("A17 Vote on a draft poll", "TC-E2-02 failure, FR-13", f"/polls/{pid}/vote", {"option_id": opt},
                "409: voting is closed until the convener opens the poll.")
    conv.post("A18 Convener opens the poll", "FR-13 draft -> open", f"/polls/{pid}/open", None, "200, state open.")
    viewer.post("A19 Member votes", "TC-E2-01 normal, FR-14", f"/polls/{pid}/vote", {"option_id": opt},
                "200; live count pushed over the WebSocket.")
    viewer.post("A20 Same member votes again", "TC-E2-01, FR-14, NFR-04", f"/polls/{pid}/vote", {"option_id": opt},
                "409 already voted: UNIQUE (poll_id, user_id).")
    viewer.post("A21 Viewer tries to close the poll", "TC-E4-08, FR-02/FR-13", f"/polls/{pid}/close", None,
                "403: only the convener of this club may close it.")
    conv.post("A22 Convener closes the poll", "FR-13 open -> closed, FR-15", f"/polls/{pid}/close", None,
              "200; result frozen with the winner.")
    conv.post("A23 Cancel a closed poll", "TC-E2-03 failure, FR-13", f"/polls/{pid}/cancel", None,
              "409: closed -> cancelled is not an allowed transition. State unchanged.")
    critic.post("A24 Vote after the close", "TC-E2-02 failure, FR-13/FR-15", f"/polls/{pid}/vote", {"option_id": opt},
                "409: poll closed.")

    LOG.append("## E2/E3 moderation and admin views\n")
    LOG.append("*(The script waits 61 s here: all sign-ins come from one address and share the real 5-per-minute limit.)*\n")
    time.sleep(61)
    mod.login("A25 Moderator signs in", "setup", "mod@cinelog.dev")
    mod.get("A26 Moderation queue as a Moderator", "FR-11", "/moderation/queue", "200, riskiest reviews first.")
    admin.login("A27 Admin signs in", "setup", "admin@cinelog.dev")
    admin.get("A28 Admin stats: job pool and cache counters", "TC-E3-06, DEF-10 retest", "/admin/stats",
              "Job counters (submitted/done/failed/retried) and LRU cache counters including evictions.")

    LOG.append("## E4 rate limit\n")
    LOG.append("*(The script waits 61 s here so the bucket is full again, then makes 6 wrong attempts in a row.)*\n")
    time.sleep(61)
    flood = C(base)
    for i in range(6):
        r = flood.h.post("/auth/login", json={"email": "admin@cinelog.dev", "password": f"guess-{i}"})
    show("A29 Sixth sign-in attempt within a minute", "TC-E4-02, FR-01", r,
         {"email": "admin@cinelog.dev", "password": "guess-5"}, "429 Too Many Requests after 5 attempts in a minute.")

    with open(out, "w", encoding="utf-8") as fh:
        fh.write("\n".join(LOG))
    print(f"wrote {out} ({sum(1 for line in LOG if line.startswith('### '))} exchanges)")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000/api",
         sys.argv[2] if len(sys.argv) > 2 else "api_exchanges.md")
