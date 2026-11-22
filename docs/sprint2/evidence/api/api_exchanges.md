# Sprint 2 API exchange log

Server: `http://localhost:8000/api` (seeded demo database, real model files). Run on 22-11-2026 11:53. All exchanges are real; none are mocked.

## E4 CN & Web: sign-in, roles and errors

### A01 Health check

*Test / requirement:* E3/E4 run check  
*Time:* 2026-11-22 11:53:52

```http
GET /api/health
```
```http
HTTP 200 OK
{
 "ok": true,
 "queue": 0,
 "jobs": {
  "submitted": 0,
  "done": 0,
  "failed": 0,
  "retried": 0,
  "postponed": 0
 },
 "films_indexed": 11,
 "shield": {
  "ml": true,
  "dl": false,
  "rnn": true,
  "semantic": true,
  "warn_thresholds": {
   "ml": 0.40559497229702357,
   "fused": 0.4016467644123496
  },
  "caches": {
   "automata": {
    "size": 0,
    "capacity": 128,
    "hits": 0,
    "misses": 0,
    "evictions": 0,
    "hit_rate": 0.0
   },
   "plot_tfidf": {
    "size": 0,
    "capacity": 256,
    "hits": 0,
    "misses": 0,
    "evictions": 0,
    "hit_rate": 0.0
   },
   "plot_embeddings": {
    "size": 0,
    "capacity": 64,
    "hits": 0,
    "misses": 0,
    "evictions": 0,
    "hit_rate": 0.0
   }
  },
  "ml_meta": {
   "trained_on": "IMDB_reviews.json",
   "n_reviews": 150000,
   "thr_low": 0.36884825764412366,
   "thr_high": 0.6254006158883544,
   "test": {
    "roc_auc": 0.7721653300960127,
    "pr_auc": 0.5597106842880629,
    "recall_at_10pct_false_blur": 0.4081888972619945,
    "f1_at_thr_high": 0.4894015861571738,
    "caught": 0.42627480532529516,
    "wrongly_blurred": 0.10876525049753397,
    "n": 15538,
    "pos_rate": 0.25621058051229245
   },
   "seconds": 194,
   "thresholds": "tuned"
  },
  "space_fitted": true,
  "rnn_meta": {
   "weight": 0.2,
   "tuned": true,
   "active": true,
   "auc": {
    "ml_only": 0.8249262391650513,
    "rnn_only": 0.7556912128691862,
    "blend": 0.8241962700274672
   },
   "auc_gain_95ci": [
    -0.005060716560467601,
    0.0035548883653741883
   ]
  }
 }
}
```

**Observed:** Server up; queue and job counters and cache counters returned.


### A02 Wrong password

*Test / requirement:* TC-E4-04 failure, FR-01  
*Time:* 2026-11-22 11:53:52

```http
POST /api/auth/login
{"email": "viewer@cinelog.dev", "password": "not-the-password"}
```
```http
HTTP 401 Unauthorized
{
 "detail": "invalid email or password"
}
```

**Observed:** 401, no session cookie set.


### A03 Correct sign-in

*Test / requirement:* TC-E4-01 normal, FR-01  
*Time:* 2026-11-22 11:53:52

```http
POST /api/auth/login
{"email": "viewer@cinelog.dev", "password": "cinelog123"}
```
```http
HTTP 200 OK
set-cookie: cl_session=eyJhbG...; HttpOnly; Max-Age=28800; Path=/; SameSite=lax
set-cookie: cl_csrf=_IiBKQ...; Max-Age=28800; Path=/; SameSite=lax
{
 "user": {
  "id": 5,
  "email": "viewer@cinelog.dev",
  "display_name": "Vic Viewer",
  "roles": [
   "viewer"
  ],
  "permissions": [
   "club.join",
   "critic.apply",
   "diary.write",
   "like.write",
   "list.write",
   "rating.write",
   "review.report",
   "review.write",
   "social.follow",
   "thread.write"
  ],
  "email_opt_out": false,
  "bio": "",
  "avatar": "",
  "has_password": true,
  "spoiler_safe": true,
  "muted_until": null
 },
 "csrf": "_IiBKQKFkbjFOLxBJNYo3hJfuycEayGH"
}
```

**Observed:** 200 with an HttpOnly, SameSite session cookie and a CSRF cookie.


### A04 Moderation queue without a session

*Test / requirement:* TC-E4-04, FR-02  
*Time:* 2026-11-22 11:53:52

```http
GET /api/moderation/queue
```
```http
HTTP 401 Unauthorized
{
 "detail": "authentication required"
}
```

**Observed:** 401 Unauthorized.


### A05 Moderation queue as a Viewer

*Test / requirement:* TC-E4-04, FR-02 deny by default  
*Time:* 2026-11-22 11:53:52

```http
GET /api/moderation/queue
```
```http
HTTP 403 Forbidden
{
 "detail": "missing permission: review.moderate"
}
```

**Observed:** 403 Forbidden: Viewer has no moderation permission.


## E1 Search (Trie and inverted index)

### A06 Autocomplete, 3 letters

*Test / requirement:* TC-E1-01 normal, FR-04  
*Time:* 2026-11-22 11:53:52

```http
GET /api/films/autocomplete?q=inc
```
```http
HTTP 200 OK
[
 {
  "id": 6,
  "title": "Inception",
  "year": 2010
 }
]
```

**Observed:** Matching titles, most popular first.


### A07 Autocomplete, 1 letter

*Test / requirement:* TC-E1-02 boundary, FR-04  
*Time:* 2026-11-22 11:53:52

```http
GET /api/films/autocomplete?q=i
```
```http
HTTP 200 OK
[]
```

**Observed:** Empty list: fewer than 2 letters are not searched.


### A08 Search with a genre filter

*Test / requirement:* TC-E1-10, FR-05  
*Time:* 2026-11-22 11:53:52

```http
GET /api/films/search?q=the&genre=Crime
```
```http
HTTP 200 OK
[
 {
  "id": 1,
  "title": "The Godfather",
  "year": 1972,
  "overview": "The ageing head of a New York crime family hands his empire to a reluctant son.",
  "poster": null,
  "genres": [
   "Crime",
   "Drama"
  ],
  "cast": [
   {
    "actor": "Marlon Brando",
    "character": "Vito Corleone"
   },
   {
    "actor": "Al Pacino",
    "character": "Michael Corleone"
   },
   {
    "actor": "James Caan",
    "character": "Sonny Corleone"
   },
   {
    "actor": "Robert Duvall",
    "character": "Tom Hagen"
   },
   {
    "actor": "Diane Keaton",
    "character": "Kay Adams"
   }
  ],
  "runtime": 175,
  "popularity": 50.0
 },
 {
  "id": 5,
  "title": "The Dark Knight",
  "year": 2008,
  "overview": "Gotham's masked vigilante faces a criminal who only wants to watch the city burn.",
  "poster": null,
  "genres": [
   "Action",
   "Crime"
  ],
  "cast": [
   {
    "actor": "Christian Bale",
    "character": "Bruce Wayne"
   },
   {
    "actor": "Heath Ledger",
    "character": "The Joker"
   },
   {
    "actor": "Aaron Eckhart",
    "character": "Harvey Dent"
   },
   {
    "actor": "Maggie Gyllenhaal",
    "character": "Rachel Dawes"
   }
  ],
  "runtime": 152,
  "popularity": 50.0
 }
]
```

**Observed:** Only Crime films that contain the word.


## E1 + E3 + E2: review submission, background scan, blur

### A09 Submit a review with a spoiler

*Test / requirement:* TC-E1-04, FR-08 (T1 transaction)  
*Time:* 2026-11-22 11:53:52

```http
POST /api/films/5/reviews
{"text": "Heath Ledger is unforgettable and the score is huge. The Joker kills Rachel Dawes in an explosion and Harvey Dent turns into Two-Face."}
```
```http
HTTP 202 Accepted
{
 "id": 6,
 "film_id": 5,
 "author": {
  "id": 5,
  "name": "Vic Viewer",
  "critic": false
 },
 "state": "pending_scan",
 "created_at": "2026-11-22T11:53:52.708778",
 "segments": [],
 "warn": false,
 "risk": 0.0,
 "uncertain": false,
 "reports": 0,
 "text": "Heath Ledger is unforgettable and the score is huge. The Joker kills Rachel Dawes in an explosion and Harvey Dent turns into Two-Face.",
 "message": "Scanning for spoilers - this review will appear shortly."
}
```

**Observed:** 202 Accepted, state pending_scan: the scan runs as a background job in E3.


### A10 Read the review after the scan

*Test / requirement:* TC-E1-04, FR-08/FR-09 (T2 compare-and-swap)  
*Time:* 2026-11-22 11:53:55

```http
GET /api/reviews/6
```
```http
HTTP 200 OK
{
 "id": 6,
 "film_id": 5,
 "author": {
  "id": 5,
  "name": "Vic Viewer",
  "critic": false
 },
 "state": "published",
 "created_at": "2026-11-22T11:53:52.708778",
 "segments": [
  {
   "idx": 0,
   "blurred": false,
   "length": 52,
   "text": "Heath Ledger is unforgettable and the score is huge."
  },
  {
   "idx": 1,
   "blurred": true,
   "length": 81,
   "text": "The Joker kills Rachel Dawes in an explosion and Harvey Dent turns into Two-Face.",
   "reasons": [
    "mentions character name(s): dawes, dent, harvey",
    "closely matches the film's plot (similarity 0.84)",
    "shares 6 rare plot terms",
    "spoiler cue 'kills' next to plot details",
    "'kills' in a sentence that restates the film's plot"
   ],
   "risk": 0.998
  }
 ],
 "warn": false,
 "risk": 0.998,
 "uncertain": false,
 "reports": 0,
 "text": "Heath Ledger is unforgettable and the score is huge. The Joker kills Rachel Dawes in an explosion and Harvey Dent turns into Two-Face."
}
```

**Observed:** Published; the spoiler sentence is blurred and the first sentence is not.


### A11 Second review of the same film

*Test / requirement:* TC-E2 409 rule, FR-08  
*Time:* 2026-11-22 11:53:55

```http
POST /api/films/5/reviews
{"text": "Trying to post a second review here."}
```
```http
HTTP 409 Conflict
{
 "detail": "you already reviewed this film"
}
```

**Observed:** 409 Conflict: one review per film per user.


### A12 Review shorter than 10 characters

*Test / requirement:* TC-E2-05 boundary, DEF-09 retest  
*Time:* 2026-11-22 11:53:55

```http
POST /api/films/5/reviews
{"text": "too short"}
```
```http
HTTP 400 Bad Request
{
 "detail": "text: String should have at least 10 characters",
 "errors": [
  {
   "field": "body.text",
   "msg": "String should have at least 10 characters"
  }
 ]
}
```

**Observed:** 400 Bad Request; the message names the field. Nothing saved.


### A13 Critic signs in

*Test / requirement:* setup  
*Time:* 2026-11-22 11:53:55

```http
POST /api/auth/login
{"email": "critic@cinelog.dev", "password": "cinelog123"}
```
```http
HTTP 200 OK
set-cookie: cl_session=eyJhbG...; HttpOnly; Max-Age=28800; Path=/; SameSite=lax
set-cookie: cl_csrf=5YjX_a...; Max-Age=28800; Path=/; SameSite=lax
{
 "user": {
  "id": 4,
  "email": "critic@cinelog.dev",
  "display_name": "Cam Critic",
  "roles": [
   "critic",
   "viewer"
  ],
  "permissions": [
   "club.join",
   "critic.apply",
   "critic.pick",
   "diary.write",
   "like.write",
   "list.write",
   "rating.write",
   "review.report",
   "review.write",
   "social.follow",
   "thread.write"
  ],
  "email_opt_out": false,
  "bio": "",
  "avatar": "",
  "has_password": true,
  "spoiler_safe": true,
  "muted_until": null
 },
 "csrf": "5YjX_aR2EAB6kDDHhhAf1HBYBM3-pTq7"
}
```

### A14 Spoiler hidden with a zero-width space

*Test / requirement:* TC-E1-06, DEF-07 retest  
*Time:* 2026-11-22 11:53:56

```http
POST /api/films/3/reviews
{"text": "Great twist. The narrator finds out that Tyler Dur​den is his own split personality."}
```
```http
HTTP 202 Accepted
{
 "id": 7,
 "film_id": 3,
 "author": {
  "id": 4,
  "name": "Cam Critic",
  "critic": true
 },
 "state": "pending_scan",
 "created_at": "2026-11-22T11:53:55.997991",
 "segments": [],
 "warn": false,
 "risk": 0.0,
 "uncertain": false,
 "reports": 0,
 "text": "Great twist. The narrator finds out that Tyler Dur​den is his own split personality.",
 "message": "Scanning for spoilers - this review will appear shortly."
}
```

**Observed:** 202 Accepted; scanned next.


### A15 Read it after the scan

*Test / requirement:* TC-E1-06, DEF-07 retest  
*Time:* 2026-11-22 11:53:59

```http
GET /api/reviews/7
```
```http
HTTP 200 OK
{
 "id": 7,
 "film_id": 3,
 "author": {
  "id": 4,
  "name": "Cam Critic",
  "critic": true
 },
 "state": "published",
 "created_at": "2026-11-22T11:53:55.997991",
 "segments": [
  {
   "idx": 0,
   "blurred": false,
   "length": 12,
   "text": "Great twist."
  },
  {
   "idx": 1,
   "blurred": true,
   "length": 70,
   "text": "The narrator finds out that Tyler Durden is his own split personality.",
   "reasons": [
    "mentions character name(s): durden, narrator, the narrator",
    "closely matches the film's plot (similarity 0.68)",
    "shares 5 rare plot terms",
    "means the same as something that happens late in the film's plot (semantic match 0.78)"
   ],
   "risk": 0.99
  }
 ],
 "warn": false,
 "risk": 0.99,
 "uncertain": false,
 "reports": 0,
 "text": "Great twist. The narrator finds out that Tyler Dur​den is his own split personality."
}
```

**Observed:** The hidden-character trick no longer works: the spoiler sentence is blurred.


## E2 Storage & Transaction: poll states and one vote per member

### A16 Convener signs in

*Test / requirement:* setup  
*Time:* 2026-11-22 11:53:59

```http
POST /api/auth/login
{"email": "convener@cinelog.dev", "password": "cinelog123"}
```
```http
HTTP 200 OK
set-cookie: cl_session=eyJhbG...; HttpOnly; Max-Age=28800; Path=/; SameSite=lax
set-cookie: cl_csrf=k_8xg4...; Max-Age=28800; Path=/; SameSite=lax
{
 "user": {
  "id": 3,
  "email": "convener@cinelog.dev",
  "display_name": "Cleo Convener",
  "roles": [
   "convener",
   "viewer"
  ],
  "permissions": [
   "club.create",
   "club.join",
   "critic.apply",
   "diary.write",
   "like.write",
   "list.write",
   "rating.write",
   "review.report",
   "review.write",
   "social.follow",
   "thread.write",
   "wordlist.edit"
  ],
  "email_opt_out": false,
  "bio": "",
  "avatar": "",
  "has_password": true,
  "spoiler_safe": true,
  "muted_until": null
 },
 "csrf": "k_8xg49ufYBV0pLGCg28pM4u74ESLQvP"
}
```

### A17 Vote on a draft poll

*Test / requirement:* TC-E2-02 failure, FR-13  
*Time:* 2026-11-22 11:53:59

```http
POST /api/polls/1/vote
{"option_id": 1}
```
```http
HTTP 409 Conflict
{
 "detail": "poll is draft: voting is closed"
}
```

**Observed:** 409: voting is closed until the convener opens the poll.


### A18 Convener opens the poll

*Test / requirement:* FR-13 draft -> open  
*Time:* 2026-11-22 11:53:59

```http
POST /api/polls/1/open
```
```http
HTTP 200 OK
{
 "id": 1,
 "club_id": 1,
 "title": "Friday's screening",
 "state": "open",
 "deadline": null,
 "screening_date": null,
 "winner_film_id": null,
 "total_votes": 0,
 "my_vote": null,
 "options": [
  {
   "id": 1,
   "film_id": 6,
   "votes": 0,
   "title": "Inception",
   "year": 2010,
   "poster": null
  },
  {
   "id": 2,
   "film_id": 8,
   "votes": 0,
   "title": "Interstellar",
   "year": 2014,
   "poster": null
  },
  {
   "id": 3,
   "film_id": 7,
   "votes": 0,
   "title": "Parasite",
   "year": 2019,
   "poster": null
  }
 ]
}
```

**Observed:** 200, state open.


### A19 Member votes

*Test / requirement:* TC-E2-01 normal, FR-14  
*Time:* 2026-11-22 11:53:59

```http
POST /api/polls/1/vote
{"option_id": 1}
```
```http
HTTP 200 OK
{
 "id": 1,
 "club_id": 1,
 "title": "Friday's screening",
 "state": "open",
 "deadline": null,
 "screening_date": null,
 "winner_film_id": null,
 "total_votes": 1,
 "my_vote": 1,
 "options": [
  {
   "id": 1,
   "film_id": 6,
   "votes": 1,
   "title": "Inception",
   "year": 2010,
   "poster": null
  },
  {
   "id": 2,
   "film_id": 8,
   "votes": 0,
   "title": "Interstellar",
   "year": 2014,
   "poster": null
  },
  {
   "id": 3,
   "film_id": 7,
   "votes": 0,
   "title": "Parasite",
   "year": 2019,
   "poster": null
  }
 ]
}
```

**Observed:** 200; live count pushed over the WebSocket.


### A20 Same member votes again

*Test / requirement:* TC-E2-01, FR-14, NFR-04  
*Time:* 2026-11-22 11:53:59

```http
POST /api/polls/1/vote
{"option_id": 1}
```
```http
HTTP 409 Conflict
{
 "detail": "already voted"
}
```

**Observed:** 409 already voted: UNIQUE (poll_id, user_id).


### A21 Viewer tries to close the poll

*Test / requirement:* TC-E4-08, FR-02/FR-13  
*Time:* 2026-11-22 11:53:59

```http
POST /api/polls/1/close
```
```http
HTTP 403 Forbidden
{
 "detail": "club role does not allow this action"
}
```

**Observed:** 403: only the convener of this club may close it.


### A22 Convener closes the poll

*Test / requirement:* FR-13 open -> closed, FR-15  
*Time:* 2026-11-22 11:53:59

```http
POST /api/polls/1/close
```
```http
HTTP 200 OK
{
 "id": 1,
 "club_id": 1,
 "title": "Friday's screening",
 "state": "closed",
 "deadline": null,
 "screening_date": null,
 "winner_film_id": 6,
 "total_votes": 1,
 "my_vote": null,
 "options": [
  {
   "id": 1,
   "film_id": 6,
   "votes": 1,
   "title": "Inception",
   "year": 2010,
   "poster": null
  },
  {
   "id": 2,
   "film_id": 8,
   "votes": 0,
   "title": "Interstellar",
   "year": 2014,
   "poster": null
  },
  {
   "id": 3,
   "film_id": 7,
   "votes": 0,
   "title": "Parasite",
   "year": 2019,
   "poster": null
  }
 ]
}
```

**Observed:** 200; result frozen with the winner.


### A23 Cancel a closed poll

*Test / requirement:* TC-E2-03 failure, FR-13  
*Time:* 2026-11-22 11:53:59

```http
POST /api/polls/1/cancel
```
```http
HTTP 409 Conflict
{
 "detail": "invalid transition closed -> cancelled"
}
```

**Observed:** 409: closed -> cancelled is not an allowed transition. State unchanged.


### A24 Vote after the close

*Test / requirement:* TC-E2-02 failure, FR-13/FR-15  
*Time:* 2026-11-22 11:53:59

```http
POST /api/polls/1/vote
{"option_id": 1}
```
```http
HTTP 409 Conflict
{
 "detail": "poll is closed: voting is closed"
}
```

**Observed:** 409: poll closed.


## E2/E3 moderation and admin views

*(The script waits 61 s here: all sign-ins come from one address and share the real 5-per-minute limit.)*

### A25 Moderator signs in

*Test / requirement:* setup  
*Time:* 2026-11-22 11:55:00

```http
POST /api/auth/login
{"email": "mod@cinelog.dev", "password": "cinelog123"}
```
```http
HTTP 200 OK
set-cookie: cl_session=eyJhbG...; HttpOnly; Max-Age=28800; Path=/; SameSite=lax
set-cookie: cl_csrf=XnHfzL...; Max-Age=28800; Path=/; SameSite=lax
{
 "user": {
  "id": 2,
  "email": "mod@cinelog.dev",
  "display_name": "Mo Moderator",
  "roles": [
   "moderator",
   "viewer"
  ],
  "permissions": [
   "audit.read",
   "club.join",
   "critic.apply",
   "critic.review",
   "diary.write",
   "like.write",
   "list.write",
   "rating.write",
   "review.moderate",
   "review.report",
   "review.write",
   "social.follow",
   "thread.write",
   "user.sanction",
   "wordlist.edit"
  ],
  "email_opt_out": false,
  "bio": "",
  "avatar": "",
  "has_password": true,
  "spoiler_safe": true,
  "muted_until": null
 },
 "csrf": "XnHfzLiT4tnWa0Vf29X8Sl9R3v_y2iKI"
}
```

### A26 Moderation queue as a Moderator

*Test / requirement:* FR-11  
*Time:* 2026-11-22 11:55:00

```http
GET /api/moderation/queue
```
```http
HTTP 200 OK
[]
```

**Observed:** 200, riskiest reviews first.


### A27 Admin signs in

*Test / requirement:* setup  
*Time:* 2026-11-22 11:55:00

```http
POST /api/auth/login
{"email": "admin@cinelog.dev", "password": "cinelog123"}
```
```http
HTTP 200 OK
set-cookie: cl_session=eyJhbG...; HttpOnly; Max-Age=28800; Path=/; SameSite=lax
set-cookie: cl_csrf=g3E_9X...; Max-Age=28800; Path=/; SameSite=lax
{
 "user": {
  "id": 1,
  "email": "admin@cinelog.dev",
  "display_name": "Alex Admin",
  "roles": [
   "admin",
   "viewer"
  ],
  "permissions": [
   "audit.read",
   "catalog.sync",
   "club.create",
   "club.join",
   "critic.apply",
   "critic.pick",
   "critic.review",
   "diary.write",
   "like.write",
   "list.write",
   "model.manage",
   "rating.write",
   "review.moderate",
   "review.report",
   "review.write",
   "role.manage",
   "social.follow",
   "thread.write",
   "user.sanction",
   "wordlist.edit"
  ],
  "email_opt_out": false,
  "bio": "",
  "avatar": "",
  "has_password": true,
  "spoiler_safe": true,
  "muted_until": null
 },
 "csrf": "g3E_9X5nrSy3M5IC5s9aS-EhEfFAsswz"
}
```

### A28 Admin stats: job pool and cache counters

*Test / requirement:* TC-E3-06, DEF-10 retest  
*Time:* 2026-11-22 11:55:00

```http
GET /api/admin/stats
```
```http
HTTP 200 OK
{
 "queue_depth": 0,
 "jobs": {
  "submitted": 9,
  "done": 9,
  "failed": 0,
  "retried": 0,
  "postponed": 0
 },
 "failed_jobs": [],
 "sync": {
  "running": false,
  "synced": 0,
  "errors": 0
 },
 "tmdb": {
  "configured": false,
  "ok": null,
  "error": ""
 },
 "films_indexed": 11,
 "shield": {
  "ml": true,
  "dl": false,
  "rnn": true,
  "semantic": true,
  "warn_thresholds": {
   "ml": 0.40559497229702357,
   "fused": 0.4016467644123496
  },
  "caches": {
   "automata": {
    "size": 2,
    "capacity": 128,
    "hits": 0,
    "misses": 2,
    "evictions": 0,
    "hit_rate": 0.0
   },
   "plot_tfidf": {
    "size": 2,
    "capacity": 256,
    "hits": 0,
    "misses": 2,
    "evictions": 0,
    "hit_rate": 0.0
   },
   "plot_embeddings": {
    "size": 2,
    "capacity": 64,
    "hits": 0,
    "misses": 2,
    "evictions": 0,
    "hit_rate": 0.0
   }
  },
  "ml_meta": {
   "trained_on": "IMDB_reviews.json",
   "n_reviews": 150000,
   "thr_low": 0.36884825764412366,
   "thr_high": 0.6254006158883544,
   "test": {
    "roc_auc": 0.7721653300960127,
    "pr_auc": 0.5597106842880629,
    "recall_at_10pct_false_blur": 0.4081888972619945,
    "f1_at_thr_high": 0.4894015861571738,
    "caught": 0.42627480532529516,
    "wrongly_blurred": 0.10876525049753397,
    "n": 15538,
    "pos_rate": 0.25621058051229245
   },
   "seconds": 194,
   "thresholds": "tuned"
  },
  "space_fitted": true,
  "rnn_meta": {
   "weight": 0.2,
   "tuned": true,
   "active": true,
   "auc": {
    "ml_only": 0.8249262391650513,
    "rnn_only": 0.7556912128691862,
    "blend": 0.8241962700274672
   },
   "auc_gain_95ci": [
    -0.005060716560467601,
    0.0035548883653741883
   ]
  }
 },
 "outbox": {
  "logged": 3
 }
}
```

**Observed:** Job counters (submitted/done/failed/retried) and LRU cache counters including evictions.


## E4 rate limit

*(The script waits 61 s here so the bucket is full again, then makes 6 wrong attempts in a row.)*

### A29 Sixth sign-in attempt within a minute

*Test / requirement:* TC-E4-02, FR-01  
*Time:* 2026-11-22 11:56:03

```http
POST /api/auth/login
{"email": "admin@cinelog.dev", "password": "guess-5"}
```
```http
HTTP 429 Too Many Requests
{
 "detail": "too many attempts, slow down"
}
```

**Observed:** 429 Too Many Requests after 5 attempts in a minute.

