# CineLog — Sprint 2 Evidence Pack (Gate 3 / Review 4)

**Broader engine implementation and mandatory partial testing** · Weeks 10–13 · Status on 22-11-2026

This file follows the numbering of the Sprint 2 Student Handbook (sections 5.1 and 1–15). Every row points to a file,
a commit or a log in this repository. Sprint 2 work is on branch `sprint-2`; the first commit of the sprint is
`d2608f6` and the starting point (end of the Sprint 1 build) is `222c581`.

**Honest status in one paragraph.** A first working version of all four engines is built, runnable and partly tested
(193 automated tests pass, 1 skipped, 93% line coverage). Sprint 2 testing found **7 new product defects (DEF-07 to
DEF-13)**; all seven are fixed and retested. Two quality targets are **not met yet** and move to Sprint 3: spoiler
accuracy (NFR02: 53.7% of spoiler reviews blurred and 12.0% of clean reviews wrongly blurred, against ≥ 85% and ≤ 10%)
and spoiler scan time (49.9 ms mean per review against ≤ 20 ms). Load, soak, security-scan and usability tests
(NFR03, NFR05, NFR06, NFR08), end-to-end integration and PostgreSQL testing are planned for Sprint 3.

---

## 5.1 Team and Engine Register

| Field | Entry |
|---|---|
| Team number | 16 |
| Theme | Role-Based Access Control (Role-Based Workflow Management System) |
| Artefact | CineLog — Movie Review and Recommendation Management System |
| Guide | Mr. V. S. Biradar (Prof. Vijay B) |
| Department | Computer Science and Engineering, KLE Technological University |
| Repository URL | https://github.com/LaGGod7/Cinelog (branch `sprint-2`, tag `gate3-sprint2`) |
| Date | 22-11-2026 |

| Student | SRN / USN | Student name | Engine / responsibility |
|---|---|---|---|
| A | 01FE24BCS022 | Omkar Anantapur (Omkar A) | E4 — CN & Web Tech: sign-in, sessions, RBAC checks, rate limit, REST API, WebSocket, UI |
| B | 01FE24BCS107 | Manish Singri | E2 — Storage & Transaction (DBMS): schema, keys, constraints, state machines, transactions, audit |
| C | 01FE24BCS140 | Goureesh N Doddamani | E1 — Search & Spoiler Matching (DSA): Trie, inverted index, heaps, Aho-Corasick, Spoiler Shield |
| D | 01FE24BCS197 | Ashutosh Kulkarni | E3 — Background Job Scheduler (OS): bounded queue, worker pool, retry, LRU, TMDB/SMTP jobs |

| Engine ID | Approved engine name | Owner A–D | Main function |
|---|---|---|---|
| E1 | Search & Spoiler Matching Engine (DSA) | C | Autocomplete and filtered search; scan every review for spoilers before it is visible; risk-ordered moderator queue |
| E2 | Storage & Transaction Engine (DBMS) | B | All permanent records in 3NF; one vote per member; review and poll state machines with compare-and-swap; append-only audit log |
| E3 | Background Job Scheduler (OS) | D | Bounded priority queue + 4 worker threads; USER jobs before BATCH; retry with back-off; LRU caches; TMDB sync and email jobs |
| E4 | CN & Web Tech Engine | A | Google / email sign-in, JWT in HTTP-only cookie, deny-by-default RBAC, 5-per-minute sign-in limit, REST + WebSocket, responsive UI |

The approved Sprint 1 engine list (4 engines, Gate 1 / Gate 2) is carried forward unchanged.

---

## 1. Sprint 2 Plan and Backlog

| Task / FR ID | Engine / owner | Work to implement | Done when… | Status |
|---|---|---|---|---|
| S2-01 / FR04, NFR01 | E1 / C | Trie with top-10 per node; 2-letter minimum at the API | 10 most popular titles for any prefix; p95 ≤ 100 ms on 10,000 titles | Done — TC-E1-01/02, benchmark p95 0.004 ms |
| S2-02 / FR04 | E1 / C | Inverted index with genre, cast, year filters | Filtered search returns only matching films | Done — TC-E1-10, A08 |
| S2-03 / FR08 | E1 / C | Aho-Corasick per film + ML / semantic Spoiler Shield, sentence-level blur | Spoiler sentence blurred, clean sentences shown | Done — TC-E1-04/05, A10 |
| S2-04 / FR08 | E1 / C | Unicode normalisation before matching (found in Sprint 2) | Zero-width and no-break-space tricks are caught | Done — DEF-07/08, TC-E1-06/07/09 |
| S2-05 / FR08 | E1 / C | Sentence splitter fix (found in Sprint 2) | 'it.Dr.' style run-ons split correctly | Done — DEF-12, TC-E1-11 |
| S2-06 / NFR02 | E1 / C | Reach ≥ 85% caught, ≤ 10% wrongly blurred, ≤ 20 ms | Measured on the labelled set | **In progress** — 53.7% / 12.0% / 49.9 ms |
| S2-07 / FR14, NFR04 | E2 / B | UNIQUE (poll_id, user_id) + row lock on the poll | 100 simultaneous voters → 0 duplicates | Done — test_100_concurrent_votes_no_duplicates, TC-E2-06 |
| S2-08 / FR09, FR13 | E2 / B | Review and poll state machines with compare-and-swap | Invalid change → 409, state unchanged | Done — TC-E2-02/03, A23 |
| S2-09 / FR03 | E2 / B | Append-only audit log for role and state changes | Update / delete of an audit row is refused | Done — TC-E2-04 |
| S2-10 / FR16 | E2+E4 / B, A | 400 for invalid input with a field message, as designed | Short review → 400 'text: …' | Done — DEF-09, TC-E2-05, TC-E4-06 |
| S2-11 / FR05, FR15 | E3 / D | Bounded priority queue, 4 workers, retry ×3 with back-off | USER before BATCH; failed job retried 3 times then logged | Done — TC-E3-01/02/03 |
| S2-12 / NFR05 | E3 / D | Cache counters for the soak test | Hits, misses, evictions on /health | Done — DEF-10, TC-E3-04/06; 1-hour soak **planned for Sprint 3** |
| S2-13 / FR01, FR02 | E4 / A | Sign-in, JWT cookie, deny-by-default RBAC, CSRF check | 401 without token, 403 for wrong role | Done — TC-E4-01/04/05/07/08 |
| S2-14 / FR01 | E4 / A | Token bucket, 5 sign-in attempts per minute per address | 6th attempt → 429 | Done — TC-E4-02/03, A29 |
| S2-15 / FR17 | E4 / A | Live poll counts over WebSocket | Vote appears for other members without reload | Done — test_websocket_live_poll_results; two-browser timing test **Sprint 3** |
| S2-16 | Team | Remove Python 3.13 `utcnow()` deprecation | Warnings drop, behaviour unchanged | Done — DEF-11 (1,084 → 758 warnings) |

Evidence: this table; commits `d2608f6`…`0215c13`; `backend/tests/test_sprint2_engines.py`.

---

## 2. Sprint 1 Design Handoff

| Engine ID | Approved design reference | Implementation dependency | Any approved change |
|---|---|---|---|
| E1 | S3 architecture (search design, spoiler scan design, risk queue); S4.3 API `GET /films/autocomplete` | E2 film, plot and SPOILER_TERM tables; E3 runs scans as USER jobs | Semantic plot matching added to the Spoiler Shield after the S1 ML plan (recorded in README, November update). Unicode normalisation added in Sprint 2 (DEF-07/08). |
| E2 | S4.1 keys and integrity rules; S4.2 3NF; S4.4 transactions T1–T10; S2 review and poll state diagrams (Figures 4.15, 4.16) | SQLite in WAL mode now; PostgreSQL via Docker for Sprint 3 | Schema grew from 23 core tables to 36 (genres, cast, keywords split out; notifications, outbox, likes, lists, threads). 3rd-report and 3rd-strike rules run as application rules in the same transaction; database triggers planned. Delete currently cascades; "hide instead of delete" planned. All recorded in portfolio S4. |
| E3 | S3 job queue and thread pool design; S4.4 "slow work runs outside the transaction" | E1 scan function; E2 writes; TMDB and SMTP clients | None. Eviction counters added to the LRU caches (DEF-10) to make the NFR05 soak test measurable. |
| E4 | S4.3 API contract and error table; S2 role–permission matrix; S2 login sequence | E2 users and roles; E1 search; E3 job submission | Validation errors now return 400 as S4.3 says (DEF-09); the framework default had been 422. No API path changes. |

Evidence: portfolio S3/S4 (Google Sites), `docs/portfolio/`, `docs/er/`, `docs/algorithms_ds_ml_dl.md`.

---

## 3. Engine-wise Implementation Register

| Engine ID | Module / core operation | Implemented behaviour | Code / commit reference | Pending |
|---|---|---|---|---|
| E1 | Trie autocomplete | Top-10 per node by popularity; word-start indexing for half-typed titles | `backend/app/dsa/trie.py`, `app/services/search.py` (222c581) | Benchmark on the full TMDB-synced catalogue |
| E1 | Inverted index + heap top-k | Sorted posting lists, intersection, genre/cast/year filters | `app/dsa/inverted_index.py` | — |
| E1 | Aho-Corasick | One automaton per film and word-list version; whole-word hits with positions | `app/dsa/aho_corasick.py`, `app/spoiler/wordlist.py` | — |
| E1 | Spoiler Shield | Rules + TF-IDF/logistic regression + GRU + semantic plot match; sentence blur; risk ≥ 0.7 blur, 0.3–0.7 moderators | `app/spoiler/shield.py`, `semantic.py`, `ml.py`, `rnn.py` | NFR02 accuracy and speed |
| E1 | Text normalisation + splitter | NFKC, invisible characters removed, joiners kept for Indic/emoji; split fix | `app/spoiler/text.py` (d9a8ecf, a3601ad) | — |
| E2 | Schema and constraints | 36 tables, UNIQUE/CHECK/PK rules, WAL, BEGIN IMMEDIATE for writes | `app/models.py`, `app/db.py` | PostgreSQL run; hide-instead-of-delete |
| E2 | State machines | Review and poll transitions with compare-and-swap UPDATE | `app/workflow.py` | — |
| E2 | Vote transaction | Row lock on poll + UNIQUE (poll_id, user_id); result frozen on close | `app/routers/clubs.py` | DB-level triggers for report/strike |
| E2 | Audit log | Append-only (update/delete refused) | `app/models.py` (AuditLog), `app/audit.py` | Database permissions to enforce it |
| E3 | Bounded priority queue + pool | Mutex + 2 semaphores; USER before BATCH; 4 workers | `app/scheduler/pool.py` | 1-hour soak test (NFR05) |
| E3 | Retry + back-off | 3 retries at 0.5 s × 2ⁿ, then failed list | `app/scheduler/pool.py` | — |
| E3 | LRU caches | Automata 128, plot TF-IDF 256, embeddings 64; hits/misses/evictions | `app/dsa/lru.py` (18d5554) | — |
| E3 | TMDB / Wikipedia / mail jobs | Rate-limited TMDB client, plot fetch, outbox | `app/clients/`, `app/services/jobs.py` | Real TMDB key and SMTP server (external) |
| E4 | Auth and sessions | bcrypt, JWT (8 h) in HTTP-only SameSite cookie, CSRF header, Google OAuth callback | `app/security.py`, `app/routers/auth.py` | Google client keys (external); HTTPS deployment |
| E4 | RBAC | Permission matrix, deny by default, club roles per club | `app/rbac.py` | Full role × route test matrix |
| E4 | Rate limit + validation | Token bucket 5/min on sign-in; 400 with field message | `app/security.py`, `app/main.py` (c19b0c7) | OWASP ZAP scan (NFR06) |
| E4 | REST API + WebSocket + UI | 100+ endpoints; `/ws/polls/{id}`; React site served on one port | `app/routers/*`, `frontend/src` | Two-browser live-update timing (FR17) |

---

## 4. Algorithm and Data Structure Implementation

| Engine | Algorithm / structure | Input → observed output | Edge case handled |
|---|---|---|---|
| E1 | Trie, top-10 per node | `search('dar')` → The Dark Knight, Darkest Hour, Dark Orbit (by popularity) | `'xyz'` → `[]`; 1 letter refused at the API (A07 returns `[]`) |
| E1 | Aho-Corasick | review "Tyler Durden is his own split personality. Towering…" → hits `tyler durden`, `durden`, `split personality` with positions | "Towering" does not match "tower" (whole words) |
| E1 | Normalisation | `'Tyler Dur​den'` → `'Tyler Durden'` → 2 hits | Devanagari joiner `क्‍ष` kept unchanged |
| E1 | Inverted index + heap | `search('dark', genre='Crime')` → `[1]`; `top_k(…, 2)` → `[(0.9,2),(0.7,4)]` | Unknown genre → `[]`, no error |
| E2 | State machine + CAS | `open → cancelled` → not allowed → 409 (A23) | Concurrent change: `UPDATE … WHERE state=<old>` changes 0 rows |
| E3 | Bounded priority queue | submitted B,B,B,U,U → ran U,U,B,B,B | Capacity 2: third put → QueueFull after 0.1 s |
| E3 | Exponential back-off | failing job → 4 attempts, gaps 0.010 / 0.021 / 0.041 s, then failed | Job lands in `failed_jobs`, pool keeps running |
| E3 | LRU | put 1,2,3, get 1, put 4 → film-2 evicted, `evictions=1` | Capacity reached exactly |
| E4 | Token bucket | 6 attempts at t=0 → T,T,T,T,T,F; at t=12 s → T | 20 threads for the last token → exactly 1 allowed |

Algorithm trace: `docs/sprint2/evidence/algorithm_traces.txt` (run `python -m scripts.sprint2_algorithm_trace`),
screenshot `evidence/screenshots/12_algorithm_trace.png`.

---

## 5. API / Interface and Data Exchange

All rows are **real** exchanges with a running server (`evidence/api/api_exchanges.md`, 29 exchanges). External
services used only inside automated tests are marked **mock**.

| From → to engine | API / function | Input sample | Actual response | Real / mock |
|---|---|---|---|---|
| Browser → E4 → E2 | `POST /auth/login` | viewer@cinelog.dev / correct password | 200, `cl_session` HttpOnly SameSite=Lax, `cl_csrf` | Real (A03) |
| Browser → E4 → E1 | `GET /films/autocomplete?q=inc` | 3 letters | 200 `[{"id":6,"title":"Inception","year":2010}]` | Real (A06) |
| E4 → E2 → E3 → E1 | `POST /films/5/reviews` | review with a spoiler sentence | 202 `state: pending_scan`; later `GET /reviews/6` → sentence 2 blurred, risk 0.99 with reasons | Real (A09, A10) |
| E4 → E2 | `POST /polls/1/vote` twice | same member, same poll | 200, then 409 `already voted` | Real (A19, A20) |
| E4 → E2 | `POST /polls/1/cancel` | poll already closed | 409, state unchanged | Real (A23) |
| E4 (RBAC) | `GET /moderation/queue` | no cookie / Viewer | 401 / 403 | Real (A04, A05) |
| E4 (rate limit) | `POST /auth/login` ×6 | wrong password | 6th → 429 | Real (A29) |
| E3 → E1/E4 | `GET /admin/stats` | Admin | jobs `submitted 9, done 9, failed 0`; cache counters | Real (A28) |
| E2 → E4 → browser | `ws /ws/polls/{id}` | a vote | new tally pushed | Real in `test_websocket_live_poll_results` |
| E3 → TMDB | `TMDBClient.movie()` | film id | canned JSON / 429 | **Mock** (`httpx.MockTransport`, `test_clients_jobs.py`); no TMDB key in the demo |
| E3 → Wikipedia | plot fetch | film title | canned page | **Mock** in tests |
| E3 → SMTP | outbox job | poll-open email | status `logged` (written to the dev mailbox, not sent) | **Stub**: no SMTP server configured |
| Google → E4 | `/auth/google/callback` | OAuth code | creates a Viewer | **Mock** token exchange in `test_google_callback_creates_viewer` |

---

## 6. Database, State and Transaction Implementation

| Engine | Operation / state | Expected change | Actual observed change | Proof |
|---|---|---|---|---|
| E2 | T3 vote | 1 row in `votes` per member per poll | poll 1: one row (user 5); duplicate query returns no rows | `evidence/db_state_after_api_run.txt` |
| E2 | T4 close poll | `state=closed`, `result_json` frozen | `closed`, `{"counts": {"1": 1}, "total": 1, …}` | same file; A22 |
| E2 | Poll `closed → cancelled` | rejected, state unchanged | 409; still `closed` | A23; TC-E2-03 |
| E2 | T1/T2 review | `pending_scan → published` by the worker | reviews 6 and 7 `published` with blurred segments | db file; A10, A15 |
| E2 | Audit log | `poll.open` and `poll.close` rows; edits refused | rows 1–2 present; edit/delete raise "append-only" | db file; TC-E2-04 |
| E2 | Constraints | UNIQUE vote, CHECK on roles, CHECK follower ≠ followee | shown in the `CREATE TABLE` output | db file |
| E2 | Rollback | failed vote leaves no row | 409 responses add no `votes` rows | TC-E2-06 (20 threads → 1 row) |
| E2 | Journal mode | WAL | `wal` | db file |

---

## 7. Concurrency, Security and Data Movement

| Check | Engine | Implementation / decision | Test or proof |
|---|---|---|---|
| Simultaneous updates | E2 | Row lock on POLL + UNIQUE (poll_id, user_id); SQLite writers start with BEGIN IMMEDIATE | `test_100_concurrent_votes_no_duplicates` (100 voters, 0 duplicates); TC-E2-06 (20 threads, 1 row) |
| Simultaneous jobs | E3 | Mutex + 2 semaphores around the heap | TC-E3-05 (8 producer threads, 100 jobs, each run once) |
| Transaction rollback | E2 | One user action = one transaction; errors roll back | TC-E2-04, TC-E2-06; A23 |
| Role-based access | E4 | Deny by default; club role checked for that club | TC-E4-04, TC-E4-08, `test_rbac_matrix_deny_by_default`; A04, A05, A21 |
| Malformed input | E4 | 400 with field message, never a stack trace | TC-E4-06, TC-E2-05; A12 |
| Hostile text | E1 | Unicode normalisation before matching | TC-E1-06/07/08/09; A14–A15 |
| Safe error handling | E4/E3 | 401/403/409/429 with short messages; jobs retried then logged | A02, A29; TC-E3-03 |
| Session security | E4 | JWT signature checked; HttpOnly + SameSite cookie; CSRF header | TC-E4-01, TC-E4-05, TC-E4-07 |
| Zero-copy / copying | E1/E3 | Normal copying is justified: reviews are ≤ 5,000 characters and sentences are slices of one string; the large shared objects (models, automata, matrices) are loaded once and shared read-only by all workers, not copied per job | `SpoilerShield` caches; `/health` cache sizes |

---

## 8. Build, Run and Git Evidence

| Engine | Run steps / command | Observed output | Commit / branch / tag |
|---|---|---|---|
| All | `cd backend && pip install -r requirements-dev.txt && python -m pytest -v` | 188 passed, 1 skipped (`evidence/test_logs/07_full_suite_AFTER_sprint2.txt`) | `sprint-2` @ `gate3-sprint2` |
| All | `python -m scripts.seed_demo`, build the site once (`cd frontend && npm ci && npm run build`), then `SERVE_FRONTEND=1 uvicorn app.main:create_app --factory --port 8000` | Site on http://localhost:8000, API under `/api`; logins `*@cinelog.dev` / `cinelog123` | same |
| E1 | `python -m pytest -k tc_e1 -v`; `python -m scripts.sprint2_algorithm_trace` | 11 passed; trace output | d9a8ecf, a3601ad |
| E2 | `python -m pytest -k "tc_e2 or concurrent_votes" -v` | 7 passed | c19b0c7 |
| E3 | `python -m pytest -k tc_e3 -v`; `GET /health` | 6 passed; cache counters | 18d5554 |
| E4 | `python -m pytest -k tc_e4 -v`; `python -m scripts.sprint2_api_evidence` | 8 passed; 29 exchanges | c19b0c7 |
| Perf | `python -m scripts.sprint2_benchmarks` | Trie p95 0.004 ms; scan mean 49.9 ms | 0215c13 |

Git history of the sprint (`git log --oneline 222c581..gate3-sprint2`):

```
0215c13 docs(sprint2): runnable evidence scripts and their outputs
a3601ad fix(E1): split sentences after two-letter words with no space (DEF-12)
6258a5f test(E1): sentence split after a two-letter word with no space (DEF-12, failing)
d49df7b fix: replace deprecated datetime.utcnow() (DEF-11)
18d5554 feat(E3,E1): count LRU evictions and report cache stats on /health (DEF-10)
c19b0c7 fix(E4,E2): return 400 for invalid input, as the S4.3 design says (DEF-09)
d9a8ecf fix(E1): normalise Unicode before the spoiler scan (DEF-07, DEF-08)
d2608f6 test(sprint2): add Gate 3 engine partial-test register TC-E1..TC-E4
```

(The evidence-pack commit and the tag follow these.) Tests were committed **before** their fixes, so the history
itself shows each failure, the correction and the retest.

---

## 9. Testing — Mandatory Test Case Register

All IDs are test names in `backend/tests/test_sprint2_engines.py` (run one with `pytest -k tc_e1_06`), plus four
existing tests named in full. "Actual" is what the final run printed.

| Test ID / Engine | FR ID / test type | Input / precondition | Expected result | Actual result | Pass / Fail |
|---|---|---|---|---|---|
| TC-E1-01 / E1 | FR04 / normal | 26 titles, prefix "dark" | 10 ids, most popular first | ids 24…15 in order | Pass |
| TC-E1-02 / E1 | FR04 / boundary | prefix "zz", "DRI" | `[]`; case-insensitive hit | `[]`; `[1]` | Pass |
| TC-E1-03 / E1 | FR08 / boundary | "tower" vs "Towering", "mara" vs "Marathon" | whole words only | only `tower`, `mara` at word starts | Pass |
| TC-E1-04 / E1 | FR08 / normal | "Mara dies in the burning tower…" | middle sentence blurred, risk ≥ 0.7 | `[False, True, False]`, risk 0.95 | Pass |
| TC-E1-05 / E1 | FR08 / normal | clean 3-sentence review | nothing blurred | nothing blurred | Pass |
| TC-E1-06 / E1 | FR08 / failure (hostile) | "burn​ing tower" | blurred, risk ≥ 0.7 | before fix: risk 0.15, shown; after: 0.95, blurred | Pass (after DEF-07) |
| TC-E1-07 / E1 | FR08 / failure (hostile) | "burning tower" | blurred | before: 0.54, not blurred; after: 0.95 | Pass (after DEF-08) |
| TC-E1-08 / E1 | FR08 / boundary | "", spaces, only zero-width, symbols, emoji | no crash, nothing blurred | no crash, nothing blurred | Pass |
| TC-E1-09 / E1 | FR08 / boundary | Devanagari and emoji joiners; "d​ies­" | joiners kept; hidden chars removed | as expected | Pass (after DEF-07) |
| TC-E1-10 / E1 | FR04 / normal + boundary | "dark" with genre, year, unknown genre | `[1]`, `[2]`, `[]` | `[1]`, `[2]`, `[]` | Pass |
| TC-E1-11 / E1 | FR08 / boundary | "Loved it.Dr. Crowe is great!…" | 4 correct sentences | before: "Loved it.Dr."; after: correct | Pass (after DEF-12) |
| TC-E2-01 / E2 | FR14 / normal + failure | member votes twice | 200 then 409 "already voted" | 200, 409 | Pass |
| TC-E2-02 / E2 | FR13 / failure | vote on draft, then on closed poll | 409 both | 409, 409 | Pass |
| TC-E2-03 / E2 | FR13 / state | open → cancel | 409, state stays open | 409, `open` | Pass |
| TC-E2-04 / E2 | FR03 / transaction | edit and delete an audit row | refused, row unchanged | RuntimeError "append-only", detail unchanged | Pass |
| TC-E2-05 / E2 | FR16 / boundary | 9-character review | 400 naming `text` | before: 422; after: 400 "text: …" | Pass (after DEF-09) |
| TC-E2-06 / E2 | FR14, NFR04 / concurrency | 20 threads, same member, same moment | one 200, nineteen 409, one row | 1 × 200, 19 × 409, total 1 | Pass |
| TC-E2-07 / E2 | FR14, NFR04 / concurrency | `test_100_concurrent_votes_no_duplicates`: 100 members at once | count = distinct voters | 100 = 100 | Pass |
| TC-E3-01 / E3 | FR05 / normal | 3 BATCH then 1 USER, 1 worker | USER first, then FIFO | `user-0, batch-0, batch-1, batch-2` | Pass |
| TC-E3-02 / E3 | NFR05 / boundary | capacity 2, third put, timeout 0.2 s | QueueFull within 1 s, 2 items kept | QueueFull, len 2 | Pass |
| TC-E3-03 / E3 | FR15 / failure | job always raises, max_retries 3 | 4 calls, retried 3, failed 1 | 4, 3, 1, `['sync-film-7']` | Pass |
| TC-E3-04 / E3 | NFR05 / normal | LRU(2): put, get, put | LRU entry evicted; counters | evicted film-2; hits 2, misses 1, evictions 1 | Pass (after DEF-10) |
| TC-E3-05 / E3 | NFR05 / concurrency | 8 producer threads, 100 jobs, 4 workers | 100 run, each once, 0 failed | 100 unique, 0 failed | Pass |
| TC-E3-06 / E3 | NFR05 / API | `GET /health` after a review | 3 caches with counters, capacities 128/256 | as expected | Pass (after DEF-10) |
| TC-E4-01 / E4 | FR01 / normal | correct sign-in | 200, HttpOnly + SameSite cookie | as expected | Pass |
| TC-E4-02 / E4 | FR01 / security | sign-up + 5 wrong sign-ins, limit 5/min | 4 × 401 then 429 | `[401, 401, 401, 401, 429]` | Pass |
| TC-E4-03 / E4 | FR01 / boundary | bucket 5, fake clock | 5 allowed, 6th refused, refill after 12 s, other IP free | as expected | Pass |
| TC-E4-04 / E4 | FR02 / security | no cookie; Viewer on moderation/admin | 401; 403; 403 | 401, 403, 403 | Pass |
| TC-E4-05 / E4 | FR01 / security | real, altered and garbage token | 200, 401, 401 | 200, 401, 401 | Pass |
| TC-E4-06 / E4 | FR16 / failure | body `{not json` | 400 with `detail`, no traceback | before: 422; after: 400 | Pass (after DEF-09) |
| TC-E4-07 / E4 | FR02 / security | POST without CSRF header | 403 "CSRF" | 403 | Pass |
| TC-E4-08 / E4 | FR02, FR12 / security | convener of another club | 403 on open poll and add member | 403, 403 | Pass |
| TC-E4-09 / E4 | FR17 / API | `test_websocket_live_poll_results` | vote pushes new tally | received | Pass |
| PT-01 / E1 | NFR01 / performance | 10,000 titles, 1,000 prefixes | p95 ≤ 100 ms | p95 0.0044 ms | Pass |
| PT-02 / E1 | NFR02 (time) / performance | 200 reviews, all layers | ≤ 20 ms per review | mean 49.9 ms, p95 81.9 ms | **Fail — open, Sprint 3** |
| AT-02 / E1 | NFR02 (accuracy) | 1,254 real test reviews (15-11-2026) | ≥ 85% caught, ≤ 10% wrongly blurred | 53.7% blurred (+14.4% to moderators), 12.0% wrongly blurred | **Fail — open, Sprint 3** |

Evidence: `evidence/test_logs/07_full_suite_AFTER_sprint2.txt`, `junit_full_suite.xml`, `evidence/benchmarks.txt`,
`backend/logs/eval_real_reviews.txt`.

---

## 10. Testing — Test Execution Evidence

| Test ID | How test was run | Evidence file / link | Date / commit |
|---|---|---|---|
| TC-E1-01…TC-E4-08 (before fixes) | `pytest tests/test_sprint2_engines.py -v` on the commit that added the tests | `evidence/test_logs/01_sprint2_tests_BEFORE_fixes.txt`, `screenshots/10_tests_before_fixes_6_failed.png` | 22-11-2026 / d2608f6 |
| TC-E1-06/07/09 retest | `pytest -k tc_e1 -v` | `test_logs/02_retest_DEF07_DEF08_E1.txt` | 22-11-2026 / d9a8ecf |
| TC-E2-05, TC-E4-06 retest | `pytest -k "tc_e2_05 or tc_e4_06" -v` | `test_logs/03_retest_DEF09_400.txt` | 22-11-2026 / c19b0c7 |
| TC-E3-04/06 retest | `pytest -k tc_e3 -v` | `test_logs/04_retest_DEF10_lru.txt` | 22-11-2026 / 18d5554 |
| TC-E1-11 before / after | `pytest -k tc_e1_11 -v` | `test_logs/05_DEF12_…_BEFORE.txt`, `06_DEF12_…_AFTER.txt` | 22-11-2026 / 6258a5f, a3601ad |
| Full suite + coverage | `pytest -v --cov=app --junitxml=…` | `test_logs/07_full_suite_AFTER_sprint2.txt`, `junit_full_suite.xml`, `screenshots/11_tests_after_fixes_all_pass_coverage.png` | 22-11-2026 / a3601ad |
| A01–A29 API | `python -m scripts.sprint2_api_evidence` against the seeded server | `evidence/api/api_exchanges.md` | 22-11-2026 / a3601ad |
| UI checks | Playwright screenshots of the running site | `evidence/screenshots/01–09_*.png` (06 removed: it did not show the refusal; see API A05) | 22-11-2026 / a3601ad |
| PT-01, PT-02 | `python -m scripts.sprint2_benchmarks` | `evidence/benchmarks.txt` | 22-11-2026 / 0215c13 |

---

## 11. Defect, Correction and Retest Register

Failed tests are kept: the "before" logs stay in the repository next to the retests.

| Defect ID / failed test | Observed problem | Cause / correction | Fix commit | Retest ID / result |
|---|---|---|---|---|
| DEF-01 / semantic tests | Semantic layer crashed on a film whose plot has only one sentence | No "late plot" part to compare; now returns zero scores | 222c581 | `test_a_one_sentence_plot_has_no_late_part_and_does_not_crash` — Pass |
| DEF-02 / AT-02 | 17.0% of clean real reviews wrongly blurred, mostly long reviews | Fixed cut-off ignored review length; length-adjusted thresholds q = 1 − (1 − f)^(1/n) | 222c581 | eval_real_reviews: 12.0% — **partial**, NFR02 still open |
| DEF-03 / search tests | Half-typed titles ("dark k") not found | Search only matched whole words; Trie prefix fallback added | 222c581 | `test_search_endpoints` — Pass |
| DEF-04 / spoiler tests | Plot passages loaded in random order, so "late plot" was unstable | Passages ordered by FilmPlot.id | 222c581 | spoiler suites — Pass |
| DEF-05 / adversarial set | Short reviews stating a fate ("X dies") were shown | REVEAL rule sends short name+cue reviews to moderators | 222c581 | `test_an_outright_fate_statement_…` — Pass |
| DEF-06 / adversarial eval | Evaluation missed actor-name mentions | Actor names added to film terms in the eval | 222c581 | `backend/logs/adversarial.txt` regenerated |
| DEF-07 / TC-E1-06, TC-E1-09 | Zero-width space in "burn​ing tower" → risk 0.15, spoiler shown | No Unicode clean-up; `normalize_text()` (NFKC, remove invisible chars, keep joiners for Indic/emoji) | d9a8ecf | TC-E1-06, TC-E1-09 — Pass |
| DEF-08 / TC-E1-07 | No-break space → risk 0.54, not blurred | Same fix (NFKC turns it into a space) | d9a8ecf | TC-E1-07 — Pass |
| DEF-09 / TC-E2-05, TC-E4-06 | Invalid input returned 422 with a nested list; design says 400 | Validation handler → 400 with field message; 15 hand-written 422s → 400 | c19b0c7 | TC-E2-05, TC-E4-06 — Pass; 185 passed |
| DEF-10 / TC-E3-04 | Caches could not show thrashing: no eviction counter | `evictions` + `stats()` in LRUCache; shown on /health | 18d5554 | TC-E3-04, TC-E3-06 — Pass |
| DEF-11 / full-suite log | 1,084 warnings: `datetime.utcnow()` deprecated in Python 3.12+ | 31 calls → `datetime.now(timezone.utc)` (naive UTC kept) | d49df7b | full suite 187 passed; 758 warnings left (framework, Sprint 3) |
| DEF-12 / TC-E1-11 | "Loved it.Dr. Crowe…" split as "Loved it.Dr." | Rule needed 3 lowercase letters before the stop; now 2. Gold labels re-aligned (118 → 120 spoiler sentences) | 6258a5f (fail), a3601ad (fix) | TC-E1-11, gold alignment test — Pass |
| DEF-13 / TC-E1-12, TC-E1-13, TC-E3-07, TC-E3-08 | Reported by the team (23-11-2026): new TMDB releases did not show up. Search asked TMDB only when the catalogue had < 3 matches (autocomplete: 0), so 3 older films with the same words hid a new release; and the catalogue never synced on its own (FR05 asks for a schedule) | Search and autocomplete now ask TMDB for every 3+ letter query (cached 10 min) and keep up to 3 of 10 places for new films; the 30-second timer queues a sync 2 min after start-up and then every `SYNC_EVERY_HOURS` (default 6); sync records `last_finished` | see `git log` | TC-E1-12/13/14, TC-E3-07/08 — Pass; full suite 193 passed |

Mistakes in the tests themselves (not product defects), kept in `test_logs/00_first_run_with_3_test_mistakes.txt`:

| ID | Test | What was wrong | Correction |
|---|---|---|---|
| T-01 | TC-E2-04 | Reused a session after the expected error, so the cleanup failed | Separate session per step; product behaviour was already correct |
| T-02 | TC-E4-02 | Assumed sign-up does not count towards the 5-per-minute limit | Sign-up and sign-in share the budget (correct by design); test now expects 429 on the 5th attempt after sign-up |
| T-03 | TC-E4-05 | Test client kept the old cookie, so the altered token was never sent | Fresh client per token; altered token → 401 |

---

## 12. Engine Readiness and Remaining Work

| Engine ID | Works now | Mocked / incomplete | Not yet tested | Sprint 3 dependency |
|---|---|---|---|---|
| E1 | Autocomplete, filtered search, Aho-Corasick, Spoiler Shield with sentence blur, Unicode clean-up, risk ordering | NFR02 not met (53.7% / 12.0%; 49.9 ms per review) | Re-measure the 268-review gold set after DEF-12; full-catalogue HTTP benchmark | Retrain / tune thresholds; faster semantic layer (batching, int8 model); needs E3 soak data |
| E2 | 3NF schema (36 tables), constraints, state machines with CAS, one vote per member, frozen poll results, append-only audit | Report / strike rules as application code (DB triggers planned); deletes cascade (hide-instead planned) | PostgreSQL run of the concurrency tests; NFR03 100-user load test | E4 load-test client; Docker PostgreSQL |
| E3 | Bounded priority queue, 4 workers, retry/back-off, LRU caches with counters, job counters on /health | TMDB and Wikipedia are **mocked** in tests (no key in the demo); email is a **stub** (dev mailbox, no SMTP) | NFR05 1-hour soak (≥ 50 jobs/min, 0 lost); sweep that re-queues stuck `pending_scan` reviews | Real TMDB key and SMTP account; E1 scan cost |
| E4 | Email + password sign-in, JWT cookie, CSRF, deny-by-default RBAC, 5/min limit, 400/401/403/409/429, REST + WebSocket, React UI | Google OAuth token exchange **mocked** (no client keys); HTTPS only in deployment | NFR06 OWASP ZAP scan; NFR08 usability test; two-browser FR17 timing; full role × route matrix | Deployment with TLS; FastAPI `on_event` → lifespan clean-up |

---

## 13. Requirements → Code → Partial Test Mapping

Full matrix: `docs/sprint2/traceability.csv`. Summary:

| FR ID | Engine / code reference | Test ID | Result | Gap / action |
|---|---|---|---|---|
| FR01 | E4 `security.py`, `routers/auth.py` | TC-E4-01/02/03/05 | Pass | Google OAuth with real keys (Sprint 3) |
| FR02 | E4 `rbac.py` | TC-E4-04/07/08, `test_rbac_matrix_deny_by_default` | Pass | Generated role × route matrix |
| FR03 | E2 `routers/admin.py`, AuditLog | TC-E2-04 | Pass | DB-level permissions |
| FR04 | E1 `dsa/trie.py`, `inverted_index.py` | TC-E1-01/02/10, PT-01 | Pass | HTTP benchmark on full catalogue |
| FR05 | E3 `services/jobs.py`, `clients/tmdb.py` | `test_clients_jobs.py` (mock TMDB) | Pass (mock) | Real TMDB sync |
| FR06 | E2 `routers/diary.py` | `test_diary_watchlist_aspects_and_taste`, `test_diary_rejects_future_and_pre_cinema_dates` | Pass | — |
| FR07 | E2 `routers/diary.py` (aspects) | `test_diary_watchlist_aspects_and_taste` | Pass | Stored average if slow |
| FR08 | E1 `spoiler/shield.py`, `text.py` | TC-E1-03…09, 11; AT-02; PT-02 | Pass / **AT-02, PT-02 fail** | NFR02 accuracy and speed |
| FR09 | E2 `workflow.py` | TC-E2-03, `test_api.py` | Pass | — |
| FR10 | E2 `routers/reviews.py` | `test_three_reports_hide_and_moderator_flow` | Pass | DB trigger version |
| FR11 | E1 `routers/moderation.py` | same test; A26 | Pass | — |
| FR12 | E4 `routers/clubs.py` | TC-E4-08, `test_club_permissions_private_and_roles` | Pass | — |
| FR13 | E2 `workflow.py`, `routers/clubs.py` | TC-E2-02/03 | Pass | — |
| FR14 | E2 votes UNIQUE + row lock | TC-E2-01/06/07 | Pass | PostgreSQL run |
| FR15 | E3 outbox jobs | TC-E3-03, `test_phase5.py` mailbox | Pass (stub) | Real SMTP, 5-minute delivery check |
| FR16 | E4 `main.py` validation, `frontend/` | TC-E2-05, TC-E4-06 | Pass | 360 px layout check, usability test |
| FR17 | E4 `/ws/polls/{id}` | TC-E4-09 | Pass | Two-browser ≤ 2 s timing |
| FR18–FR20 (added in S4) | follow/feed, recommendations, strikes | `test_follow_feed_and_similarity`, `test_three_strikes_mute_and_a_mute_blocks_posting_but_not_watching` | Pass | To be added to the S1 baseline at Gate 3 |

---

## 14. Weekly Progress Record — Weeks 10–13

| Academic week | Expected output | Student completed evidence / status |
|---|---|---|
| Week 10 | Sprint 1 handoff, Sprint 2 backlog, first engine code | Handoff table (section 2); backlog (section 1); engine code base committed (222c581). **Done** |
| Week 11 | Core engine increments and first partial tests | November audit: DEF-01…06 fixed, real-review evaluation (`backend/logs/`). **Done** |
| Week 12 | Expanded modules, applicable checks, defects and retests | 31-test register; DEF-07…12 found, fixed, retested; concurrency, security, API checks; commits d2608f6…0215c13 (22-11-2026). **Done** |
| Week 13 | Gate 3 evidence pack and individual engine demonstration | This pack, Sprint 2 Review deck, tag `gate3-sprint2`. Individual demos: **in preparation** (run steps in section 8) |

---

## 15. Gate 3 / Review 4 Checklist

| Review check | Yes / No / N/A |
|---|---|
| Approved Sprint 1 design is referenced and changes documented | Yes — section 2, portfolio S4 |
| Working core engine increment covering the mandatory approved responsibility is runnable and tested for each assigned student | Yes — E1–E4 sections 3, 8, 9 (NFR02 target not yet met) |
| Engine run steps and actual outputs provided | Yes — section 8 |
| Normal, boundary and failure partial tests executed | Yes — section 9 |
| Additional state / concurrency / security / API tests completed where applicable | Yes — TC-E2-06/07, TC-E3-05, TC-E4-02…08, A01–A29 |
| Actual results, failures, corrections and retests recorded | Yes — sections 10–11 |
| Git history and requirement-to-test mapping available | Yes — section 8, `traceability.csv` |
| Mocks, deferred work and Sprint 3 dependencies clearly listed | Yes — sections 5 and 12 |
| Each student can explain and demonstrate their own engine | In preparation — demo script per engine in section 8 |

Gate 3 team outcome: decided by the reviewer.
