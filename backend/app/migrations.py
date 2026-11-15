"""Tiny schema-migration runner.

`create_all` only creates MISSING tables; it never adds a column to a table that already exists. When a release adds
columns, an old database file would then crash on the first query. Each migration here is a numbered, idempotent step
that brings an older database up to date; the applied numbers are recorded in `schema_version`.

To change the schema later: add the column to the model, then append (next number, description, function) below.
A brand-new database already has every column (create_all), so its migrations are recorded without changing anything.
"""
from __future__ import annotations

import datetime as dt
import logging
from typing import Callable, List, Tuple

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection, Engine

log = logging.getLogger("cinelog.migrate")


def add_column(conn: Connection, table: str, column: str, ddl_type: str) -> bool:
    """ALTER TABLE ... ADD COLUMN unless it is already there. Returns True when it added one."""
    if table not in inspect(conn).get_table_names():
        return False  # create_all builds a missing table with every column
    if column in {c["name"] for c in inspect(conn).get_columns(table)}:
        return False
    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl_type}"))
    return True


def _m1_profile_and_sessions(conn: Connection) -> None:
    add_column(conn, "users", "bio", "VARCHAR(300) NOT NULL DEFAULT ''")
    add_column(conn, "users", "avatar", "VARCHAR(20) NOT NULL DEFAULT ''")
    add_column(conn, "users", "password_changed_at", "TIMESTAMP")


def _m2_review_warn(conn: Connection) -> None:
    add_column(conn, "reviews", "warn", "BOOLEAN NOT NULL DEFAULT FALSE")


def _m3_mute_and_spoiler_safe(conn: Connection) -> None:
    add_column(conn, "users", "muted_until", "TIMESTAMP")
    add_column(conn, "users", "spoiler_safe", "BOOLEAN NOT NULL DEFAULT TRUE")


MIGRATIONS: List[Tuple[int, str, Callable[[Connection], None]]] = [
    (1, "users: bio, avatar, password_changed_at", _m1_profile_and_sessions),
    (2, "reviews: warn (possible-spoilers label)", _m2_review_warn),
    (3, "users: muted_until, spoiler_safe", _m3_mute_and_spoiler_safe),
]


def migrate(engine: Engine) -> List[int]:
    """Apply every migration not yet recorded. Returns the numbers applied (empty when up to date)."""
    applied: List[int] = []
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY, "
                          "description VARCHAR(200) NOT NULL, applied_at TIMESTAMP NOT NULL)"))
        done = {v for (v,) in conn.execute(text("SELECT version FROM schema_version"))}
        for version, description, fn in sorted(MIGRATIONS, key=lambda m: m[0]):
            if version in done:
                continue
            fn(conn)
            conn.execute(text("INSERT INTO schema_version (version, description, applied_at) VALUES (:v, :d, :t)"),
                         {"v": version, "d": description, "t": dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)})
            applied.append(version)
            log.info("applied migration %s: %s", version, description)
    return applied
