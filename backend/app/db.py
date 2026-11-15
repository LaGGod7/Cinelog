from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    pass


def make_engine(url: str) -> Engine:
    if url.startswith("sqlite"):
        # A real connection pool: opening a SQLite connection (and running its PRAGMAs) on every request is slow, most of all on Windows.
        eng = create_engine(url, connect_args={"check_same_thread": False, "timeout": 30},
                            pool_size=16, max_overflow=32, pool_recycle=3600)

        @event.listens_for(eng, "connect")
        def _pragmas(dbapi_conn, _):  # noqa: ANN001
            dbapi_conn.isolation_level = None  # we emit BEGIN ourselves (below)
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA journal_mode=WAL")  # readers never block the writer and the writer never blocks readers
            cur.execute("PRAGMA synchronous=NORMAL")
            cur.execute("PRAGMA temp_store=MEMORY")
            cur.execute("PRAGMA cache_size=-32768")  # 32 MB page cache per connection
            cur.close()

        @event.listens_for(eng, "begin")
        def _begin(conn):  # noqa: ANN001
            if conn.get_execution_options().get("readonly"):
                # page views: a plain (deferred) read transaction. It takes no lock, so it never queues behind a writer
                # and never makes anyone else wait.
                conn.exec_driver_sql("BEGIN")
                conn.exec_driver_sql("PRAGMA query_only=ON")  # a stray write fails loudly instead of failing at random later
            else:
                # anything that may write: take the write lock up front, so concurrent writers queue (timeout=30s)
                # instead of failing on a lock upgrade
                conn.exec_driver_sql("BEGIN IMMEDIATE")

        @event.listens_for(eng, "checkin")
        def _writable_again(dbapi_conn, _):  # noqa: ANN001
            try:
                dbapi_conn.execute("PRAGMA query_only=OFF")  # the connection goes back to the pool in its normal state
            except Exception:  # noqa: BLE001  (closed connection)
                pass

        return eng
    return create_engine(url, pool_size=10, max_overflow=20, pool_pre_ping=True)


class Database:
    def __init__(self, url: str) -> None:
        self.engine = make_engine(url)
        self.Session = sessionmaker(self.engine, expire_on_commit=False)
        # same engine and pool, but its transactions are deferred (read-only use); see make_engine
        self.ReadSession = sessionmaker(self.engine.execution_options(readonly=True), expire_on_commit=False)

    def create_all(self) -> None:
        from . import models  # noqa: F401  (register tables)

        Base.metadata.create_all(self.engine)
        from .migrations import migrate

        migrate(self.engine)

    @contextmanager
    def session(self, readonly: bool = False) -> Iterator[Session]:
        """readonly=True is for code that only SELECTs. It must not write: a deferred transaction cannot upgrade to a write
        safely, so SQLite is told to refuse writes on it (PRAGMA query_only)."""
        s = (self.ReadSession if readonly else self.Session)()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()
