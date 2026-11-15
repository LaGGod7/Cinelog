-- CineLog database schema, SQLite.
-- Generated from app/models.py with SQLAlchemy; schema_version is created by app/migrations.py.
-- Tables are listed so that every table comes after the tables it references.
-- Foreign keys are only checked when this is on, for every connection:
PRAGMA foreign_keys = ON;

CREATE TABLE audit_log (
	id INTEGER NOT NULL,
	at DATETIME NOT NULL,
	actor_id INTEGER,
	action VARCHAR(60) NOT NULL,
	target VARCHAR(120) NOT NULL,
	detail TEXT NOT NULL,
	PRIMARY KEY (id)
);

CREATE INDEX ix_audit_log_action ON audit_log (action);

CREATE INDEX ix_audit_log_at ON audit_log (at);

CREATE TABLE clubs (
	id INTEGER NOT NULL,
	name VARCHAR(100) NOT NULL,
	description TEXT NOT NULL,
	is_public BOOLEAN NOT NULL,
	created_at DATETIME NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (name)
);

CREATE TABLE films (
	id INTEGER NOT NULL,
	tmdb_id INTEGER,
	imdb_id VARCHAR(20),
	title VARCHAR(300) NOT NULL,
	year INTEGER,
	overview TEXT NOT NULL,
	poster_path VARCHAR(200),
	popularity FLOAT NOT NULL,
	runtime INTEGER,
	wordlist_version INTEGER NOT NULL,
	plot_checked BOOLEAN NOT NULL,
	synced_at DATETIME,
	PRIMARY KEY (id),
	UNIQUE (tmdb_id),
	UNIQUE (imdb_id)
);

CREATE INDEX ix_films_title ON films (title);

CREATE INDEX ix_films_year ON films (year);

CREATE TABLE outbox (
	id INTEGER NOT NULL,
	to_email VARCHAR(254) NOT NULL,
	subject VARCHAR(200) NOT NULL,
	body TEXT NOT NULL,
	status VARCHAR(10) NOT NULL,
	created_at DATETIME NOT NULL,
	PRIMARY KEY (id)
);

CREATE TABLE users (
	id INTEGER NOT NULL,
	email VARCHAR(254) NOT NULL,
	password_hash VARCHAR(100),
	display_name VARCHAR(80) NOT NULL,
	google_sub VARCHAR(64),
	email_opt_out BOOLEAN NOT NULL,
	created_at DATETIME NOT NULL,
	bio VARCHAR(300) DEFAULT '' NOT NULL,
	avatar VARCHAR(20) DEFAULT '' NOT NULL,
	password_changed_at DATETIME,
	muted_until DATETIME,
	spoiler_safe BOOLEAN DEFAULT 1 NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (google_sub)
);

CREATE UNIQUE INDEX ix_users_email ON users (email);

CREATE TABLE aspect_ratings (
	user_id INTEGER NOT NULL,
	film_id INTEGER NOT NULL,
	aspect VARCHAR(10) NOT NULL,
	value FLOAT NOT NULL,
	PRIMARY KEY (user_id, film_id, aspect),
	CHECK (value >= 0.5 and value <= 5),
	CHECK (aspect in ('story','acting','visuals','music','pacing')),
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE,
	FOREIGN KEY(film_id) REFERENCES films (id) ON DELETE CASCADE
);

CREATE INDEX ix_aspect_film ON aspect_ratings (film_id, aspect);

CREATE TABLE cast_members (
	id INTEGER NOT NULL,
	film_id INTEGER NOT NULL,
	actor VARCHAR(120) NOT NULL,
	character VARCHAR(160) NOT NULL,
	billing INTEGER NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(film_id) REFERENCES films (id) ON DELETE CASCADE
);

CREATE INDEX ix_cast_members_film_id ON cast_members (film_id);

CREATE TABLE club_members (
	club_id INTEGER NOT NULL,
	user_id INTEGER NOT NULL,
	role VARCHAR(12) NOT NULL,
	PRIMARY KEY (club_id, user_id),
	CHECK (role in ('convener','co_convener','member')),
	FOREIGN KEY(club_id) REFERENCES clubs (id) ON DELETE CASCADE,
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE TABLE club_threads (
	id INTEGER NOT NULL,
	club_id INTEGER NOT NULL,
	user_id INTEGER NOT NULL,
	title VARCHAR(200) NOT NULL,
	body TEXT NOT NULL,
	tag VARCHAR(20) NOT NULL,
	created_at DATETIME NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(club_id) REFERENCES clubs (id) ON DELETE CASCADE,
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE INDEX ix_club_threads_club_id ON club_threads (club_id);

CREATE TABLE club_watchlist (
	club_id INTEGER NOT NULL,
	film_id INTEGER NOT NULL,
	added_by INTEGER,
	PRIMARY KEY (club_id, film_id),
	FOREIGN KEY(club_id) REFERENCES clubs (id) ON DELETE CASCADE,
	FOREIGN KEY(film_id) REFERENCES films (id) ON DELETE CASCADE,
	FOREIGN KEY(added_by) REFERENCES users (id) ON DELETE SET NULL
);

CREATE TABLE critic_applications (
	id INTEGER NOT NULL,
	user_id INTEGER NOT NULL,
	statement TEXT NOT NULL,
	links VARCHAR(300) NOT NULL,
	state VARCHAR(10) NOT NULL,
	decided_by INTEGER,
	decision_note TEXT NOT NULL,
	created_at DATETIME NOT NULL,
	decided_at DATETIME,
	PRIMARY KEY (id),
	CHECK (state in ('pending','approved','rejected','withdrawn')),
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE,
	FOREIGN KEY(decided_by) REFERENCES users (id) ON DELETE SET NULL
);

CREATE INDEX ix_critic_applications_user_id ON critic_applications (user_id);

CREATE TABLE critic_picks (
	user_id INTEGER NOT NULL,
	film_id INTEGER NOT NULL,
	blurb VARCHAR(280) NOT NULL,
	created_at DATETIME NOT NULL,
	PRIMARY KEY (user_id, film_id),
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE,
	FOREIGN KEY(film_id) REFERENCES films (id) ON DELETE CASCADE
);

CREATE INDEX ix_critic_picks_recent ON critic_picks (created_at);

CREATE TABLE diary_entries (
	id INTEGER NOT NULL,
	user_id INTEGER NOT NULL,
	film_id INTEGER NOT NULL,
	watched_on DATE NOT NULL,
	format VARCHAR(10) NOT NULL,
	rewatch BOOLEAN NOT NULL,
	notes TEXT NOT NULL,
	stars FLOAT,
	created_at DATETIME NOT NULL,
	PRIMARY KEY (id),
	CHECK (stars is null or (stars >= 0.5 and stars <= 5)),
	CHECK (format in ('Theatre','OTT','IMAX')),
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE,
	FOREIGN KEY(film_id) REFERENCES films (id) ON DELETE CASCADE
);

CREATE INDEX ix_diary_user_date ON diary_entries (user_id, watched_on);

CREATE TABLE film_genres (
	film_id INTEGER NOT NULL,
	genre VARCHAR(40) NOT NULL,
	PRIMARY KEY (film_id, genre),
	FOREIGN KEY(film_id) REFERENCES films (id) ON DELETE CASCADE
);

CREATE TABLE film_keywords (
	film_id INTEGER NOT NULL,
	keyword VARCHAR(80) NOT NULL,
	PRIMARY KEY (film_id, keyword),
	FOREIGN KEY(film_id) REFERENCES films (id) ON DELETE CASCADE
);

CREATE TABLE film_lists (
	id INTEGER NOT NULL,
	user_id INTEGER NOT NULL,
	title VARCHAR(120) NOT NULL,
	description TEXT NOT NULL,
	created_at DATETIME NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE INDEX ix_film_lists_user_id ON film_lists (user_id);

CREATE TABLE film_plots (
	id INTEGER NOT NULL,
	film_id INTEGER NOT NULL,
	kind VARCHAR(20) NOT NULL,
	text TEXT NOT NULL,
	source VARCHAR(40) NOT NULL,
	PRIMARY KEY (id),
	CHECK (kind in ('plot','confirmed_spoiler')),
	FOREIGN KEY(film_id) REFERENCES films (id) ON DELETE CASCADE
);

CREATE INDEX ix_film_plots_film_id ON film_plots (film_id);

CREATE TABLE follows (
	follower_id INTEGER NOT NULL,
	followee_id INTEGER NOT NULL,
	PRIMARY KEY (follower_id, followee_id),
	CHECK (follower_id != followee_id),
	FOREIGN KEY(follower_id) REFERENCES users (id) ON DELETE CASCADE,
	FOREIGN KEY(followee_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE TABLE likes (
	user_id INTEGER NOT NULL,
	kind VARCHAR(12) NOT NULL,
	target_id INTEGER NOT NULL,
	created_at DATETIME NOT NULL,
	PRIMARY KEY (user_id, kind, target_id),
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE INDEX ix_likes_target ON likes (kind, target_id);

CREATE TABLE notifications (
	id INTEGER NOT NULL,
	user_id INTEGER NOT NULL,
	kind VARCHAR(20) NOT NULL,
	text VARCHAR(300) NOT NULL,
	link VARCHAR(200) NOT NULL,
	created_at DATETIME NOT NULL,
	read_at DATETIME,
	PRIMARY KEY (id),
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE INDEX ix_notifications_user ON notifications (user_id, read_at, id);

CREATE TABLE password_resets (
	id INTEGER NOT NULL,
	user_id INTEGER NOT NULL,
	token_hash VARCHAR(64) NOT NULL,
	expires_at DATETIME NOT NULL,
	used_at DATETIME,
	created_at DATETIME NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE,
	UNIQUE (token_hash)
);

CREATE INDEX ix_password_resets_user_id ON password_resets (user_id);

CREATE TABLE polls (
	id INTEGER NOT NULL,
	club_id INTEGER NOT NULL,
	title VARCHAR(160) NOT NULL,
	state VARCHAR(10) NOT NULL,
	deadline DATETIME,
	screening_date DATETIME,
	winner_film_id INTEGER,
	result_json TEXT,
	created_by INTEGER,
	created_at DATETIME NOT NULL,
	PRIMARY KEY (id),
	CHECK (state in ('draft','open','closed','cancelled')),
	FOREIGN KEY(club_id) REFERENCES clubs (id) ON DELETE CASCADE,
	FOREIGN KEY(winner_film_id) REFERENCES films (id) ON DELETE SET NULL,
	FOREIGN KEY(created_by) REFERENCES users (id) ON DELETE SET NULL
);

CREATE INDEX ix_polls_club_id ON polls (club_id);

CREATE TABLE reviews (
	id INTEGER NOT NULL,
	user_id INTEGER NOT NULL,
	film_id INTEGER NOT NULL,
	text TEXT NOT NULL,
	state VARCHAR(15) NOT NULL,
	risk FLOAT NOT NULL,
	uncertain BOOLEAN NOT NULL,
	warn BOOLEAN NOT NULL,
	segments_json TEXT NOT NULL,
	scan_version INTEGER NOT NULL,
	created_at DATETIME NOT NULL,
	PRIMARY KEY (id),
	CHECK (state in ('pending_scan','published','hidden','removed')),
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE,
	FOREIGN KEY(film_id) REFERENCES films (id) ON DELETE CASCADE
);

CREATE INDEX ix_reviews_film_id ON reviews (film_id);

CREATE INDEX ix_reviews_film_state ON reviews (film_id, state);

CREATE INDEX ix_reviews_user_id ON reviews (user_id);

CREATE TABLE spoiler_terms (
	id INTEGER NOT NULL,
	film_id INTEGER NOT NULL,
	term VARCHAR(120) NOT NULL,
	kind VARCHAR(10) NOT NULL,
	source VARCHAR(20) NOT NULL,
	added_by INTEGER,
	PRIMARY KEY (id),
	UNIQUE (film_id, term),
	CHECK (kind in ('name','plot')),
	FOREIGN KEY(film_id) REFERENCES films (id) ON DELETE CASCADE,
	FOREIGN KEY(added_by) REFERENCES users (id) ON DELETE SET NULL
);

CREATE INDEX ix_spoiler_terms_film_id ON spoiler_terms (film_id);

CREATE TABLE user_badges (
	user_id INTEGER NOT NULL,
	"key" VARCHAR(40) NOT NULL,
	earned_at DATETIME NOT NULL,
	PRIMARY KEY (user_id, "key"),
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE TABLE user_roles (
	user_id INTEGER NOT NULL,
	role VARCHAR(20) NOT NULL,
	PRIMARY KEY (user_id, role),
	CHECK (role in ('viewer','critic','convener','moderator','admin')),
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE TABLE user_strikes (
	id INTEGER NOT NULL,
	user_id INTEGER NOT NULL,
	issued_by INTEGER,
	review_id INTEGER,
	reason VARCHAR(300) NOT NULL,
	created_at DATETIME NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE,
	FOREIGN KEY(issued_by) REFERENCES users (id) ON DELETE SET NULL
);

CREATE INDEX ix_user_strikes_user_id ON user_strikes (user_id);

CREATE TABLE watch_goals (
	user_id INTEGER NOT NULL,
	year INTEGER NOT NULL,
	target INTEGER NOT NULL,
	PRIMARY KEY (user_id, year),
	CHECK (target >= 1 and target <= 1000),
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE TABLE watchlist (
	user_id INTEGER NOT NULL,
	film_id INTEGER NOT NULL,
	added_at DATETIME NOT NULL,
	PRIMARY KEY (user_id, film_id),
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE,
	FOREIGN KEY(film_id) REFERENCES films (id) ON DELETE CASCADE
);

CREATE TABLE film_list_items (
	list_id INTEGER NOT NULL,
	film_id INTEGER NOT NULL,
	position INTEGER NOT NULL,
	PRIMARY KEY (list_id, film_id),
	FOREIGN KEY(list_id) REFERENCES film_lists (id) ON DELETE CASCADE,
	FOREIGN KEY(film_id) REFERENCES films (id) ON DELETE CASCADE
);

CREATE TABLE poll_options (
	id INTEGER NOT NULL,
	poll_id INTEGER NOT NULL,
	film_id INTEGER NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (poll_id, film_id),
	FOREIGN KEY(poll_id) REFERENCES polls (id) ON DELETE CASCADE,
	FOREIGN KEY(film_id) REFERENCES films (id) ON DELETE CASCADE
);

CREATE INDEX ix_poll_options_poll_id ON poll_options (poll_id);

CREATE TABLE review_reports (
	id INTEGER NOT NULL,
	review_id INTEGER NOT NULL,
	user_id INTEGER NOT NULL,
	reason VARCHAR(40) NOT NULL,
	comment TEXT NOT NULL,
	created_at DATETIME NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (review_id, user_id),
	FOREIGN KEY(review_id) REFERENCES reviews (id) ON DELETE CASCADE,
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE INDEX ix_review_reports_review_id ON review_reports (review_id);

CREATE TABLE thread_replies (
	id INTEGER NOT NULL,
	thread_id INTEGER NOT NULL,
	user_id INTEGER NOT NULL,
	body TEXT NOT NULL,
	created_at DATETIME NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(thread_id) REFERENCES club_threads (id) ON DELETE CASCADE,
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE INDEX ix_thread_replies_thread_id ON thread_replies (thread_id);

CREATE TABLE watchalongs (
	id INTEGER NOT NULL,
	club_id INTEGER NOT NULL,
	film_id INTEGER NOT NULL,
	starts_at DATETIME NOT NULL,
	poll_id INTEGER,
	created_by INTEGER NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(club_id) REFERENCES clubs (id) ON DELETE CASCADE,
	FOREIGN KEY(film_id) REFERENCES films (id) ON DELETE CASCADE,
	UNIQUE (poll_id),
	FOREIGN KEY(poll_id) REFERENCES polls (id) ON DELETE SET NULL,
	FOREIGN KEY(created_by) REFERENCES users (id)
);

CREATE INDEX ix_watchalongs_club_id ON watchalongs (club_id);

CREATE TABLE votes (
	id INTEGER NOT NULL,
	poll_id INTEGER NOT NULL,
	user_id INTEGER NOT NULL,
	option_id INTEGER NOT NULL,
	created_at DATETIME NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_one_vote_per_member UNIQUE (poll_id, user_id),
	FOREIGN KEY(poll_id) REFERENCES polls (id) ON DELETE CASCADE,
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE,
	FOREIGN KEY(option_id) REFERENCES poll_options (id) ON DELETE CASCADE
);

CREATE TABLE watchalong_rsvps (
	watchalong_id INTEGER NOT NULL,
	user_id INTEGER NOT NULL,
	PRIMARY KEY (watchalong_id, user_id),
	FOREIGN KEY(watchalong_id) REFERENCES watchalongs (id) ON DELETE CASCADE,
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS schema_version (
	version INTEGER NOT NULL,
	description VARCHAR(200) NOT NULL,
	applied_at TIMESTAMP NOT NULL,
	PRIMARY KEY (version)
);
