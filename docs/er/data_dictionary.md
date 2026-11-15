# CineLog database: data dictionary

37 tables (36 from the models plus `schema_version`), 195 columns, 56 enforced foreign keys (48 CASCADE, 7 SET NULL, 1 with no delete rule) and 6 logical references without a constraint.

Generated from `backend/app/models.py` and checked against the running SQLite database. `PK` primary key, `FK` foreign key, `UQ` unique. A default marked *app* is set by the application; one marked *db* is a DEFAULT in the database.

## Identity & access

### `users`

Accounts. Signs in with e-mail and password or with Google (google_sub). Holds profile fields and two moderation or reader settings: muted_until and spoiler_safe.

| Key | Column | Type | Null | Default | Notes |
|---|---|---|---|---|---|
| PK | `id` | INTEGER | no |  |  |
| UQ | `email` | VARCHAR(254) | no |  |  |
|  | `password_hash` | VARCHAR(100) | yes |  | Empty for Google-only accounts |
|  | `display_name` | VARCHAR(80) | no |  |  |
| UQ | `google_sub` | VARCHAR(64) | yes |  | Google account id |
|  | `email_opt_out` | BOOLEAN | no | app: `False` |  |
|  | `created_at` | DATETIME | no | app: `now() UTC` |  |
|  | `bio` | VARCHAR(300) | no | server: `''` |  |
|  | `avatar` | VARCHAR(20) | no | server: `''` | A key from the AVATARS list, or empty |
|  | `password_changed_at` | DATETIME | yes |  | Sessions issued before this time are void |
|  | `muted_until` | DATETIME | yes |  | No new reviews or posts until then |
|  | `spoiler_safe` | BOOLEAN | no | server: `TRUE` | Fold 'possible spoiler' reviews on films not yet seen |

- Unique: (google_sub)
- Indexes: `ix_users_email` (email)
- Referenced by: `aspect_ratings.user_id`, `club_members.user_id`, `club_threads.user_id`, `club_watchlist.added_by`, `critic_applications.user_id`, `critic_applications.decided_by`, `critic_picks.user_id`, `diary_entries.user_id`, `film_lists.user_id`, `follows.follower_id`, `follows.followee_id`, `likes.user_id`, `notifications.user_id`, `password_resets.user_id`, `polls.created_by`, `reviews.user_id`, `spoiler_terms.added_by`, `user_badges.user_id`, `user_roles.user_id`, `user_strikes.user_id`, `user_strikes.issued_by`, `watch_goals.user_id`, `watchlist.user_id`, `review_reports.user_id`, `thread_replies.user_id`, `watchalongs.created_by`, `votes.user_id`, `watchalong_rsvps.user_id`, `audit_log.actor_id` (no FK), `outbox.to_email` (no FK)

### `user_roles` (weak)

The site roles a user holds: viewer, critic, convener, moderator, admin. A person's rights are the union of their roles' permissions.

| Key | Column | Type | Null | Default | Notes |
|---|---|---|---|---|---|
| PK,FK | `user_id` | INTEGER | no |  | → `users.id` CASCADE |
| PK | `role` | VARCHAR(20) | no |  |  |

- Check: `role in ('viewer','critic','convener','moderator','admin')`

### `password_resets`

One-time password-reset tokens. Only the SHA-256 of the token is stored.

| Key | Column | Type | Null | Default | Notes |
|---|---|---|---|---|---|
| PK | `id` | INTEGER | no |  |  |
| FK | `user_id` | INTEGER | no |  | → `users.id` CASCADE |
| UQ | `token_hash` | VARCHAR(64) | no |  | SHA-256 of the token |
|  | `expires_at` | DATETIME | no |  |  |
|  | `used_at` | DATETIME | yes |  |  |
|  | `created_at` | DATETIME | no | app: `now() UTC` |  |

- Unique: (token_hash)
- Indexes: `ix_password_resets_user_id` (user_id)

## Film catalogue

### `films`

The film catalogue, filled from TMDB. Carries TMDB and IMDb ids, poster, popularity and runtime, plus the flags the spoiler shield uses per film.

| Key | Column | Type | Null | Default | Notes |
|---|---|---|---|---|---|
| PK | `id` | INTEGER | no |  |  |
| UQ | `tmdb_id` | INTEGER | yes |  | TMDB id |
| UQ | `imdb_id` | VARCHAR(20) | yes |  | tt... id, joins the Kaggle data |
|  | `title` | VARCHAR(300) | no |  |  |
|  | `year` | INTEGER | yes |  |  |
|  | `overview` | TEXT | no | app: `''` |  |
|  | `poster_path` | VARCHAR(200) | yes |  |  |
|  | `popularity` | FLOAT | no | app: `0.0` |  |
|  | `runtime` | INTEGER | yes |  |  |
|  | `wordlist_version` | INTEGER | no | app: `1` | Version of the film's spoiler words |
|  | `plot_checked` | BOOLEAN | no | app: `False` | A Wikipedia plot lookup was attempted |
|  | `synced_at` | DATETIME | yes |  |  |

- Unique: (imdb_id), (tmdb_id)
- Indexes: `ix_films_title` (title), `ix_films_year` (year)
- Referenced by: `aspect_ratings.film_id`, `cast_members.film_id`, `club_watchlist.film_id`, `critic_picks.film_id`, `diary_entries.film_id`, `film_genres.film_id`, `film_keywords.film_id`, `film_plots.film_id`, `polls.winner_film_id`, `reviews.film_id`, `spoiler_terms.film_id`, `watchlist.film_id`, `film_list_items.film_id`, `poll_options.film_id`, `watchalongs.film_id`

### `film_genres` (weak)

Film and genre. A genre is a text value, not its own table.

| Key | Column | Type | Null | Default | Notes |
|---|---|---|---|---|---|
| PK,FK | `film_id` | INTEGER | no |  | → `films.id` CASCADE |
| PK | `genre` | VARCHAR(40) | no |  |  |

### `film_keywords` (weak)

Film and keyword, same shape as genres.

| Key | Column | Type | Null | Default | Notes |
|---|---|---|---|---|---|
| PK,FK | `film_id` | INTEGER | no |  | → `films.id` CASCADE |
| PK | `keyword` | VARCHAR(80) | no |  |  |

### `cast_members`

Billed cast of a film, in billing order.

| Key | Column | Type | Null | Default | Notes |
|---|---|---|---|---|---|
| PK | `id` | INTEGER | no |  |  |
| FK | `film_id` | INTEGER | no |  | → `films.id` CASCADE |
|  | `actor` | VARCHAR(120) | no |  |  |
|  | `character` | VARCHAR(160) | no | app: `''` |  |
|  | `billing` | INTEGER | no | app: `0` |  |

- Indexes: `ix_cast_members_film_id` (film_id)

## Spoiler-shield context

### `film_plots`

Context passages the spoiler shield retrieves: plot text and moderator-confirmed spoiler sentences.

| Key | Column | Type | Null | Default | Notes |
|---|---|---|---|---|---|
| PK | `id` | INTEGER | no |  |  |
| FK | `film_id` | INTEGER | no |  | → `films.id` CASCADE |
|  | `kind` | VARCHAR(20) | no | app: `'plot'` | plot or confirmed_spoiler |
|  | `text` | TEXT | no |  |  |
|  | `source` | VARCHAR(40) | no | app: `''` | kaggle, wikipedia, moderator or seed |

- Check: `kind in ('plot','confirmed_spoiler')`
- Indexes: `ix_film_plots_film_id` (film_id)

### `spoiler_terms`

Words that give away a given film. 'plot' terms are strong signals, 'name' terms are weak ones.

| Key | Column | Type | Null | Default | Notes |
|---|---|---|---|---|---|
| PK | `id` | INTEGER | no |  |  |
| FK | `film_id` | INTEGER | no |  | → `films.id` CASCADE |
|  | `term` | VARCHAR(120) | no |  |  |
|  | `kind` | VARCHAR(10) | no | app: `'plot'` | name (weak) or plot (strong) |
|  | `source` | VARCHAR(20) | no | app: `'tmdb'` | tmdb, moderator or convener |
| FK | `added_by` | INTEGER | yes |  | → `users.id` SET NULL · Who added it; cleared if that user goes |

- Unique: (film_id, term)
- Check: `kind in ('name','plot')`
- Indexes: `ix_spoiler_terms_film_id` (film_id)

## Logging & ratings

### `diary_entries`

One row per viewing: date, format, rewatch flag, notes and a star rating. A film can be logged more than once.

| Key | Column | Type | Null | Default | Notes |
|---|---|---|---|---|---|
| PK | `id` | INTEGER | no |  |  |
| FK | `user_id` | INTEGER | no |  | → `users.id` CASCADE |
| FK | `film_id` | INTEGER | no |  | → `films.id` CASCADE |
|  | `watched_on` | DATE | no |  |  |
|  | `format` | VARCHAR(10) | no | app: `'OTT'` | Theatre, OTT or IMAX |
|  | `rewatch` | BOOLEAN | no | app: `False` |  |
|  | `notes` | TEXT | no | app: `''` |  |
|  | `stars` | FLOAT | yes |  | 0.5 to 5 |
|  | `created_at` | DATETIME | no | app: `now() UTC` |  |

- Check: `stars is null or (stars >= 0.5 and stars <= 5)`; `format in ('Theatre','OTT','IMAX')`
- Indexes: `ix_diary_user_date` (user_id, watched_on)

### `watchlist` (junction)

Films a user wants to watch.

| Key | Column | Type | Null | Default | Notes |
|---|---|---|---|---|---|
| PK,FK | `user_id` | INTEGER | no |  | → `users.id` CASCADE |
| PK,FK | `film_id` | INTEGER | no |  | → `films.id` CASCADE |
|  | `added_at` | DATETIME | no | app: `now() UTC` |  |

### `aspect_ratings` (junction)

Scores for story, acting, visuals, music and pacing, one row per user, film and aspect.

| Key | Column | Type | Null | Default | Notes |
|---|---|---|---|---|---|
| PK,FK | `user_id` | INTEGER | no |  | → `users.id` CASCADE |
| PK,FK | `film_id` | INTEGER | no |  | → `films.id` CASCADE |
| PK | `aspect` | VARCHAR(10) | no |  | story, acting, visuals, music or pacing |
|  | `value` | FLOAT | no |  | 0.5 to 5 |

- Check: `value >= 0.5 and value <= 5`; `aspect in ('story','acting','visuals','music','pacing')`
- Indexes: `ix_aspect_film` (film_id, aspect)

### `watch_goals` (weak)

A yearly target such as 'watch 52 films in 2026'. One per user per year.

| Key | Column | Type | Null | Default | Notes |
|---|---|---|---|---|---|
| PK,FK | `user_id` | INTEGER | no |  | → `users.id` CASCADE |
| PK | `year` | INTEGER | no |  |  |
|  | `target` | INTEGER | no |  | 1 to 1000 |

- Check: `target >= 1 and target <= 1000`

## Reviews & reactions

### `reviews`

Written reviews. State moves from pending_scan to published, hidden or removed. The shield's result is cached on the row.

| Key | Column | Type | Null | Default | Notes |
|---|---|---|---|---|---|
| PK | `id` | INTEGER | no |  |  |
| FK | `user_id` | INTEGER | no |  | → `users.id` CASCADE |
| FK | `film_id` | INTEGER | no |  | → `films.id` CASCADE |
|  | `text` | TEXT | no |  |  |
|  | `state` | VARCHAR(15) | no | app: `'pending_scan'` | pending_scan, published, hidden or removed |
|  | `risk` | FLOAT | no | app: `0.0` | Spoiler score from the shield, 0 to 1 |
|  | `uncertain` | BOOLEAN | no | app: `False` | In the model's uncertain band |
|  | `warn` | BOOLEAN | no | app: `False` | Readers see 'possible spoilers' |
|  | `segments_json` | TEXT | no | app: `'[]'` | Per-sentence scan result |
|  | `scan_version` | INTEGER | no | app: `0` | Which shield version produced it |
|  | `created_at` | DATETIME | no | app: `now() UTC` |  |

- Check: `state in ('pending_scan','published','hidden','removed')`
- Indexes: `ix_reviews_film_state` (film_id, state), `ix_reviews_user_id` (user_id), `ix_reviews_film_id` (film_id)
- Referenced by: `review_reports.review_id`, `user_strikes.review_id` (no FK), `likes.target_id` (no FK)

### `review_reports`

A reader's report on a review. One per reader per review.

| Key | Column | Type | Null | Default | Notes |
|---|---|---|---|---|---|
| PK | `id` | INTEGER | no |  |  |
| FK | `review_id` | INTEGER | no |  | → `reviews.id` CASCADE |
| FK | `user_id` | INTEGER | no |  | → `users.id` CASCADE |
|  | `reason` | VARCHAR(40) | no | app: `'spoiler'` |  |
|  | `comment` | TEXT | no | app: `''` |  |
|  | `created_at` | DATETIME | no | app: `now() UTC` |  |

- Unique: (review_id, user_id)
- Indexes: `ix_review_reports_review_id` (review_id)

### `likes` (weak)

One table for likes on reviews, lists and club threads. kind and target_id point at the liked row without a foreign key.

| Key | Column | Type | Null | Default | Notes |
|---|---|---|---|---|---|
| PK,FK | `user_id` | INTEGER | no |  | → `users.id` CASCADE |
| PK | `kind` | VARCHAR(12) | no |  | review, list or thread |
| PK | `target_id` | INTEGER | no |  | Id in the table named by kind (no foreign key) |
|  | `created_at` | DATETIME | no | app: `now() UTC` |  |

- Indexes: `ix_likes_target` (kind, target_id)

## Clubs & discussion

### `clubs`

Film clubs. Names are unique.

| Key | Column | Type | Null | Default | Notes |
|---|---|---|---|---|---|
| PK | `id` | INTEGER | no |  |  |
| UQ | `name` | VARCHAR(100) | no |  |  |
|  | `description` | TEXT | no | app: `''` |  |
|  | `is_public` | BOOLEAN | no | app: `True` |  |
|  | `created_at` | DATETIME | no | app: `now() UTC` |  |

- Unique: (name)
- Referenced by: `club_members.club_id`, `club_threads.club_id`, `club_watchlist.club_id`, `polls.club_id`, `watchalongs.club_id`

### `club_members` (junction)

Who is in a club and with which club role. Club roles are separate from site roles.

| Key | Column | Type | Null | Default | Notes |
|---|---|---|---|---|---|
| PK,FK | `club_id` | INTEGER | no |  | → `clubs.id` CASCADE |
| PK,FK | `user_id` | INTEGER | no |  | → `users.id` CASCADE |
|  | `role` | VARCHAR(12) | no | app: `'member'` | convener, co_convener or member |

- Check: `role in ('convener','co_convener','member')`

### `club_watchlist` (junction)

Films a club plans to watch, with who added them.

| Key | Column | Type | Null | Default | Notes |
|---|---|---|---|---|---|
| PK,FK | `club_id` | INTEGER | no |  | → `clubs.id` CASCADE |
| PK,FK | `film_id` | INTEGER | no |  | → `films.id` CASCADE |
| FK | `added_by` | INTEGER | yes |  | → `users.id` SET NULL · Cleared if that user goes |

### `club_threads`

Discussion threads inside a club.

| Key | Column | Type | Null | Default | Notes |
|---|---|---|---|---|---|
| PK | `id` | INTEGER | no |  |  |
| FK | `club_id` | INTEGER | no |  | → `clubs.id` CASCADE |
| FK | `user_id` | INTEGER | no |  | → `users.id` CASCADE |
|  | `title` | VARCHAR(200) | no |  |  |
|  | `body` | TEXT | no | app: `''` |  |
|  | `tag` | VARCHAR(20) | no | app: `'Discussion'` |  |
|  | `created_at` | DATETIME | no | app: `now() UTC` |  |

- Indexes: `ix_club_threads_club_id` (club_id)
- Referenced by: `thread_replies.thread_id`, `likes.target_id` (no FK)

### `thread_replies`

Replies inside a club thread.

| Key | Column | Type | Null | Default | Notes |
|---|---|---|---|---|---|
| PK | `id` | INTEGER | no |  |  |
| FK | `thread_id` | INTEGER | no |  | → `club_threads.id` CASCADE |
| FK | `user_id` | INTEGER | no |  | → `users.id` CASCADE |
|  | `body` | TEXT | no |  |  |
|  | `created_at` | DATETIME | no | app: `now() UTC` |  |

- Indexes: `ix_thread_replies_thread_id` (thread_id)

## Polls & watch-alongs

### `polls`

A club's film poll. Draft, open, closed or cancelled. The result is frozen as JSON when the poll closes.

| Key | Column | Type | Null | Default | Notes |
|---|---|---|---|---|---|
| PK | `id` | INTEGER | no |  |  |
| FK | `club_id` | INTEGER | no |  | → `clubs.id` CASCADE |
|  | `title` | VARCHAR(160) | no |  |  |
|  | `state` | VARCHAR(10) | no | app: `'draft'` | draft, open, closed or cancelled |
|  | `deadline` | DATETIME | yes |  |  |
|  | `screening_date` | DATETIME | yes |  |  |
| FK | `winner_film_id` | INTEGER | yes |  | → `films.id` SET NULL · Cleared if that film goes |
|  | `result_json` | TEXT | yes |  | Tally frozen at close |
| FK | `created_by` | INTEGER | yes |  | → `users.id` SET NULL · Cleared if that user goes |
|  | `created_at` | DATETIME | no | app: `now() UTC` |  |

- Check: `state in ('draft','open','closed','cancelled')`
- Indexes: `ix_polls_club_id` (club_id)
- Referenced by: `poll_options.poll_id`, `watchalongs.poll_id`, `votes.poll_id`

### `poll_options`

The candidate films in a poll.

| Key | Column | Type | Null | Default | Notes |
|---|---|---|---|---|---|
| PK | `id` | INTEGER | no |  |  |
| FK | `poll_id` | INTEGER | no |  | → `polls.id` CASCADE |
| FK | `film_id` | INTEGER | no |  | → `films.id` CASCADE |

- Unique: (poll_id, film_id)
- Indexes: `ix_poll_options_poll_id` (poll_id)
- Referenced by: `votes.option_id`

### `votes`

A member's vote. One vote per member per poll.

| Key | Column | Type | Null | Default | Notes |
|---|---|---|---|---|---|
| PK | `id` | INTEGER | no |  |  |
| FK | `poll_id` | INTEGER | no |  | → `polls.id` CASCADE |
| FK | `user_id` | INTEGER | no |  | → `users.id` CASCADE |
| FK | `option_id` | INTEGER | no |  | → `poll_options.id` CASCADE |
|  | `created_at` | DATETIME | no | app: `now() UTC` |  |

- Unique: (poll_id, user_id)

### `watchalongs`

A scheduled screening for a club. It can come from a poll; each poll has at most one.

| Key | Column | Type | Null | Default | Notes |
|---|---|---|---|---|---|
| PK | `id` | INTEGER | no |  |  |
| FK | `club_id` | INTEGER | no |  | → `clubs.id` CASCADE |
| FK | `film_id` | INTEGER | no |  | → `films.id` CASCADE |
|  | `starts_at` | DATETIME | no |  |  |
| FK,UQ | `poll_id` | INTEGER | yes |  | → `polls.id` SET NULL · At most one watch-along per poll |
| FK | `created_by` | INTEGER | no |  | → `users.id` NO ACTION · No ON DELETE rule: blocks deleting that user |

- Unique: (poll_id)
- Indexes: `ix_watchalongs_club_id` (club_id)
- Referenced by: `watchalong_rsvps.watchalong_id`

### `watchalong_rsvps` (junction)

Who is going to a watch-along.

| Key | Column | Type | Null | Default | Notes |
|---|---|---|---|---|---|
| PK,FK | `watchalong_id` | INTEGER | no |  | → `watchalongs.id` CASCADE |
| PK,FK | `user_id` | INTEGER | no |  | → `users.id` CASCADE |

## Social & lists

### `follows` (junction)

A user following another user. Nobody can follow themselves.

| Key | Column | Type | Null | Default | Notes |
|---|---|---|---|---|---|
| PK,FK | `follower_id` | INTEGER | no |  | → `users.id` CASCADE |
| PK,FK | `followee_id` | INTEGER | no |  | → `users.id` CASCADE |

- Check: `follower_id != followee_id`

### `film_lists`

Lists of films curated by a user.

| Key | Column | Type | Null | Default | Notes |
|---|---|---|---|---|---|
| PK | `id` | INTEGER | no |  |  |
| FK | `user_id` | INTEGER | no |  | → `users.id` CASCADE |
|  | `title` | VARCHAR(120) | no |  |  |
|  | `description` | TEXT | no | app: `''` |  |
|  | `created_at` | DATETIME | no | app: `now() UTC` |  |

- Indexes: `ix_film_lists_user_id` (user_id)
- Referenced by: `film_list_items.list_id`, `likes.target_id` (no FK)

### `film_list_items` (junction)

Films in a list, with their position.

| Key | Column | Type | Null | Default | Notes |
|---|---|---|---|---|---|
| PK,FK | `list_id` | INTEGER | no |  | → `film_lists.id` CASCADE |
| PK,FK | `film_id` | INTEGER | no |  | → `films.id` CASCADE |
|  | `position` | INTEGER | no | app: `0` |  |

### `user_badges` (weak)

Badges a user has earned. Badge definitions live in app/gamification.py.

| Key | Column | Type | Null | Default | Notes |
|---|---|---|---|---|---|
| PK,FK | `user_id` | INTEGER | no |  | → `users.id` CASCADE |
| PK | `key` | VARCHAR(40) | no |  |  |
|  | `earned_at` | DATETIME | no | app: `now() UTC` |  |

### `notifications`

In-app notifications under the bell, with a front-end link and a read time.

| Key | Column | Type | Null | Default | Notes |
|---|---|---|---|---|---|
| PK | `id` | INTEGER | no |  |  |
| FK | `user_id` | INTEGER | no |  | → `users.id` CASCADE |
|  | `kind` | VARCHAR(20) | no |  |  |
|  | `text` | VARCHAR(300) | no |  |  |
|  | `link` | VARCHAR(200) | no | app: `''` | Front-end path such as /films/12 |
|  | `created_at` | DATETIME | no | app: `now() UTC` |  |
|  | `read_at` | DATETIME | yes |  |  |

- Indexes: `ix_notifications_user` (user_id, read_at, id)

## Critics & moderation

### `critic_applications`

A viewer's request to become a critic. A moderator or admin decides it; approval grants the critic role.

| Key | Column | Type | Null | Default | Notes |
|---|---|---|---|---|---|
| PK | `id` | INTEGER | no |  |  |
| FK | `user_id` | INTEGER | no |  | → `users.id` CASCADE |
|  | `statement` | TEXT | no |  |  |
|  | `links` | VARCHAR(300) | no | app: `''` |  |
|  | `state` | VARCHAR(10) | no | app: `'pending'` | pending, approved, rejected or withdrawn |
| FK | `decided_by` | INTEGER | yes |  | → `users.id` SET NULL · Moderator or admin; cleared if that user goes |
|  | `decision_note` | TEXT | no | app: `''` |  |
|  | `created_at` | DATETIME | no | app: `now() UTC` |  |
|  | `decided_at` | DATETIME | yes |  |  |

- Check: `state in ('pending','approved','rejected','withdrawn')`
- Indexes: `ix_critic_applications_user_id` (user_id)

### `critic_picks` (junction)

A critic's one-line recommendation for a film.

| Key | Column | Type | Null | Default | Notes |
|---|---|---|---|---|---|
| PK,FK | `user_id` | INTEGER | no |  | → `users.id` CASCADE |
| PK,FK | `film_id` | INTEGER | no |  | → `films.id` CASCADE |
|  | `blurb` | VARCHAR(280) | no |  |  |
|  | `created_at` | DATETIME | no | app: `now() UTC` |  |

- Indexes: `ix_critic_picks_recent` (created_at)

### `user_strikes`

A moderator's formal warning. Three within 30 days mute the account for three days.

| Key | Column | Type | Null | Default | Notes |
|---|---|---|---|---|---|
| PK | `id` | INTEGER | no |  |  |
| FK | `user_id` | INTEGER | no |  | → `users.id` CASCADE |
| FK | `issued_by` | INTEGER | yes |  | → `users.id` SET NULL · Moderator; cleared if that user goes |
|  | `review_id` | INTEGER | yes |  | Review concerned; plain integer, no foreign key |
|  | `reason` | VARCHAR(300) | no |  |  |
|  | `created_at` | DATETIME | no | app: `now() UTC` |  |

- Indexes: `ix_user_strikes_user_id` (user_id)

## System

### `audit_log` (system)

Append-only record of role changes, moderation decisions and sanctions. The app refuses updates and deletes.

| Key | Column | Type | Null | Default | Notes |
|---|---|---|---|---|---|
| PK | `id` | INTEGER | no |  |  |
|  | `at` | DATETIME | no | app: `now() UTC` |  |
|  | `actor_id` | INTEGER | yes |  | User id; plain integer, no foreign key |
|  | `action` | VARCHAR(60) | no |  |  |
|  | `target` | VARCHAR(120) | no | app: `''` | Free text such as user:12 |
|  | `detail` | TEXT | no | app: `''` |  |

- Indexes: `ix_audit_log_action` (action), `ix_audit_log_at` (at)

### `outbox` (system)

E-mail queue. With no SMTP server it doubles as the development mailbox.

| Key | Column | Type | Null | Default | Notes |
|---|---|---|---|---|---|
| PK | `id` | INTEGER | no |  |  |
|  | `to_email` | VARCHAR(254) | no |  | Address as text, no foreign key |
|  | `subject` | VARCHAR(200) | no |  |  |
|  | `body` | TEXT | no |  |  |
|  | `status` | VARCHAR(10) | no | app: `'queued'` | queued, sent, logged or failed |
|  | `created_at` | DATETIME | no | app: `now() UTC` |  |

### `schema_version` (system)

Migration bookkeeping. Created by app/migrations.py, not by a model.

| Key | Column | Type | Null | Default | Notes |
|---|---|---|---|---|---|
| PK | `version` | INTEGER | no |  |  |
|  | `description` | VARCHAR(200) | no |  |  |
|  | `applied_at` | TIMESTAMP | no |  |  |

## Relationships

| Parent | Child | Foreign key | Cardinality | Type | On delete |
|---|---|---|---|---|---|
| `users.id` | `aspect_ratings` | `user_id` | 1 : 0..* | identifying | CASCADE |
| `films.id` | `aspect_ratings` | `film_id` | 1 : 0..* | identifying | CASCADE |
| `films.id` | `cast_members` | `film_id` | 1 : 0..* | non-identifying | CASCADE |
| `clubs.id` | `club_members` | `club_id` | 1 : 0..* | identifying | CASCADE |
| `users.id` | `club_members` | `user_id` | 1 : 0..* | identifying | CASCADE |
| `clubs.id` | `club_threads` | `club_id` | 1 : 0..* | non-identifying | CASCADE |
| `users.id` | `club_threads` | `user_id` | 1 : 0..* | non-identifying | CASCADE |
| `clubs.id` | `club_watchlist` | `club_id` | 1 : 0..* | identifying | CASCADE |
| `films.id` | `club_watchlist` | `film_id` | 1 : 0..* | identifying | CASCADE |
| `users.id` | `club_watchlist` | `added_by` | 0..1 : 0..* | non-identifying | SET NULL |
| `users.id` | `critic_applications` | `user_id` | 1 : 0..* | non-identifying | CASCADE |
| `users.id` | `critic_applications` | `decided_by` | 0..1 : 0..* | non-identifying | SET NULL |
| `users.id` | `critic_picks` | `user_id` | 1 : 0..* | identifying | CASCADE |
| `films.id` | `critic_picks` | `film_id` | 1 : 0..* | identifying | CASCADE |
| `users.id` | `diary_entries` | `user_id` | 1 : 0..* | non-identifying | CASCADE |
| `films.id` | `diary_entries` | `film_id` | 1 : 0..* | non-identifying | CASCADE |
| `films.id` | `film_genres` | `film_id` | 1 : 0..* | identifying | CASCADE |
| `films.id` | `film_keywords` | `film_id` | 1 : 0..* | identifying | CASCADE |
| `users.id` | `film_lists` | `user_id` | 1 : 0..* | non-identifying | CASCADE |
| `films.id` | `film_plots` | `film_id` | 1 : 0..* | non-identifying | CASCADE |
| `users.id` | `follows` | `follower_id` | 1 : 0..* | identifying | CASCADE |
| `users.id` | `follows` | `followee_id` | 1 : 0..* | identifying | CASCADE |
| `users.id` | `likes` | `user_id` | 1 : 0..* | identifying | CASCADE |
| `users.id` | `notifications` | `user_id` | 1 : 0..* | non-identifying | CASCADE |
| `users.id` | `password_resets` | `user_id` | 1 : 0..* | non-identifying | CASCADE |
| `clubs.id` | `polls` | `club_id` | 1 : 0..* | non-identifying | CASCADE |
| `films.id` | `polls` | `winner_film_id` | 0..1 : 0..* | non-identifying | SET NULL |
| `users.id` | `polls` | `created_by` | 0..1 : 0..* | non-identifying | SET NULL |
| `users.id` | `reviews` | `user_id` | 1 : 0..* | non-identifying | CASCADE |
| `films.id` | `reviews` | `film_id` | 1 : 0..* | non-identifying | CASCADE |
| `films.id` | `spoiler_terms` | `film_id` | 1 : 0..* | non-identifying | CASCADE |
| `users.id` | `spoiler_terms` | `added_by` | 0..1 : 0..* | non-identifying | SET NULL |
| `users.id` | `user_badges` | `user_id` | 1 : 0..* | identifying | CASCADE |
| `users.id` | `user_roles` | `user_id` | 1 : 0..* | identifying | CASCADE |
| `users.id` | `user_strikes` | `user_id` | 1 : 0..* | non-identifying | CASCADE |
| `users.id` | `user_strikes` | `issued_by` | 0..1 : 0..* | non-identifying | SET NULL |
| `users.id` | `watch_goals` | `user_id` | 1 : 0..* | identifying | CASCADE |
| `users.id` | `watchlist` | `user_id` | 1 : 0..* | identifying | CASCADE |
| `films.id` | `watchlist` | `film_id` | 1 : 0..* | identifying | CASCADE |
| `film_lists.id` | `film_list_items` | `list_id` | 1 : 0..* | identifying | CASCADE |
| `films.id` | `film_list_items` | `film_id` | 1 : 0..* | identifying | CASCADE |
| `polls.id` | `poll_options` | `poll_id` | 1 : 0..* | non-identifying | CASCADE |
| `films.id` | `poll_options` | `film_id` | 1 : 0..* | non-identifying | CASCADE |
| `reviews.id` | `review_reports` | `review_id` | 1 : 0..* | non-identifying | CASCADE |
| `users.id` | `review_reports` | `user_id` | 1 : 0..* | non-identifying | CASCADE |
| `club_threads.id` | `thread_replies` | `thread_id` | 1 : 0..* | non-identifying | CASCADE |
| `users.id` | `thread_replies` | `user_id` | 1 : 0..* | non-identifying | CASCADE |
| `clubs.id` | `watchalongs` | `club_id` | 1 : 0..* | non-identifying | CASCADE |
| `films.id` | `watchalongs` | `film_id` | 1 : 0..* | non-identifying | CASCADE |
| `polls.id` | `watchalongs` | `poll_id` | 0..1 : 0..1 | non-identifying | SET NULL |
| `users.id` | `watchalongs` | `created_by` | 1 : 0..* | non-identifying | NO ACTION |
| `polls.id` | `votes` | `poll_id` | 1 : 0..* | non-identifying | CASCADE |
| `users.id` | `votes` | `user_id` | 1 : 0..* | non-identifying | CASCADE |
| `poll_options.id` | `votes` | `option_id` | 1 : 0..* | non-identifying | CASCADE |
| `watchalongs.id` | `watchalong_rsvps` | `watchalong_id` | 1 : 0..* | identifying | CASCADE |
| `users.id` | `watchalong_rsvps` | `user_id` | 1 : 0..* | identifying | CASCADE |
| `users.id` | `audit_log` | `actor_id` | 1 : 0..* | logical | none |
| `reviews.id` | `user_strikes` | `review_id` | 1 : 0..* | logical | none |
| `reviews.id` | `likes` | `target_id` [kind = 'review'] | 1 : 0..* | logical | none |
| `film_lists.id` | `likes` | `target_id` [kind = 'list'] | 1 : 0..* | logical | none |
| `club_threads.id` | `likes` | `target_id` [kind = 'thread'] | 1 : 0..* | logical | none |
| `users.email` | `outbox` | `to_email` | 1 : 0..* | logical | none |

### Many-to-many and one-to-one

- **users ↔ films** via `diary_entries`, `watchlist`, `aspect_ratings`, `reviews`, `critic_picks`. A user can log, queue, rate, review or recommend many films, and a film has many of each. diary_entries has its own key so a film can be logged twice; reviews are limited to one per user and film by the app, not by the database.
- **users ↔ users** via `follows`. Self-referencing many-to-many. Two foreign keys to users, and a check that stops self-follows.
- **users ↔ clubs** via `club_members`. Membership with a club role (convener, co_convener, member).
- **clubs ↔ films** via `club_watchlist`. Films on a club's watchlist.
- **film_lists ↔ films** via `film_list_items`. Lists hold films in a chosen position.
- **polls ↔ films** via `poll_options`. Candidate films in a poll.
- **users ↔ poll_options** via `votes`. One vote per member per poll.
- **watchalongs ↔ users** via `watchalong_rsvps`. Who has said they are going.
- **users ↔ reviews** via `review_reports`. One report per reader per review.
- **users ↔ roles** via `user_roles`. Roles are a CHECK-constrained value, not a table, so this is a weak table rather than a true junction.
- **polls ↔ watchalongs** via `watchalongs.poll_id`. One-to-one at most: poll_id is UNIQUE and nullable.

## Creation order

Create level 0 first. Drop in the opposite order.

- Level 0: `audit_log`, `clubs`, `films`, `outbox`, `schema_version`, `users`
- Level 1: `aspect_ratings`, `cast_members`, `club_members`, `club_threads`, `club_watchlist`, `critic_applications`, `critic_picks`, `diary_entries`, `film_genres`, `film_keywords`, `film_lists`, `film_plots`, `follows`, `likes`, `notifications`, `password_resets`, `polls`, `reviews`, `spoiler_terms`, `user_badges`, `user_roles`, `user_strikes`, `watch_goals`, `watchlist`
- Level 2: `film_list_items`, `poll_options`, `review_reports`, `thread_replies`, `watchalongs`
- Level 3: `votes`, `watchalong_rsvps`

## Design notes

**Foreign keys are enforced.** The app opens every SQLite connection with PRAGMA foreign_keys=ON (app/db.py), so each rule on this page is active. SQLite ignores foreign keys by default; a script that opens the file without that pragma would not be checked.

**One foreign key has no delete rule.** watchalongs.created_by is NOT NULL and has no ON DELETE clause, so deleting a user who created a watch-along would be refused. There is no account-deletion feature today, so nothing triggers it yet. If you add one, decide whether those watch-alongs go with the user or pass to the club's convener.

**Rules that only the code enforces.** A user can review a film once: the reviews router answers 409, but there is no UNIQUE (user_id, film_id). A vote's option must belong to its poll: the clubs router checks it, while votes has separate foreign keys to the poll and to the option and nothing ties them together. Both would need a constraint (or a composite key) to be database guarantees.

**References the database does not check.** audit_log.actor_id is a plain integer on purpose, because the log is append-only and cannot be updated when a user goes. user_strikes.review_id, likes.target_id (polymorphic across reviews, lists and threads) and outbox.to_email are also unchecked, so they can point at rows that no longer exist.

**Value sets live in CHECK constraints.** Role, review state, poll state, diary format, aspect, club role, plot kind, spoiler-term kind and application state are limited by CHECKs, not by lookup tables. Not limited: likes.kind, user_badges.key, notifications.kind, review_reports.reason and club_threads.tag.

**What is stored twice on purpose.** reviews.risk, uncertain, warn, segments_json and scan_version cache the shield's output and are rewritten on a rescan. polls.result_json is the tally frozen when the poll closes. Everything else is stored once.

**Genres and keywords are text.** film_genres and film_keywords hold the value in the key. That keeps the schema small, but a misspelt genre becomes a new genre.

**Timestamps are UTC without a zone.** Every DateTime is written as UTC with the zone stripped (models.now). The PostgreSQL DDL therefore uses TIMESTAMP WITHOUT TIME ZONE.

