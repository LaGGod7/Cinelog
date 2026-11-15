import os
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402
from app.services.catalog import set_plot, upsert_tmdb_film  # noqa: E402


class Api:
    """A browser-like client: keeps cookies and sends the CSRF header like the React app does."""

    def __init__(self, app):
        self.c = TestClient(app)

    def _h(self):
        t = self.c.cookies.get("cl_csrf")
        return {"X-CSRF-Token": t} if t else {}

    def get(self, url, **kw):
        return self.c.get(url, **kw)

    def post(self, url, json=None, **kw):
        return self.c.post(url, json=json, headers=self._h(), **kw)

    def put(self, url, json=None, **kw):
        return self.c.put(url, json=json, headers=self._h(), **kw)

    def patch(self, url, json=None, **kw):
        return self.c.patch(url, json=json, headers=self._h(), **kw)

    def delete(self, url, **kw):
        return self.c.delete(url, headers=self._h(), **kw)

    def register(self, email, name="User", pw="password123"):
        r = self.post("/auth/register", {"email": email, "password": pw, "display_name": name})
        assert r.status_code == 201, r.text
        return r.json()["user"]


def make_settings(tmp, **kw):
    base = dict(database_url=f"sqlite:///{tmp}/t.db", bcrypt_rounds=4, login_per_minute=1000, api_burst=100000,
                api_rate=100000, workers=4, model_dir=os.path.join(tmp, "nomodels"))
    base.update(kw)
    return Settings(**base)


@pytest.fixture()
def app(tmp_path):
    a = create_app(make_settings(str(tmp_path)))
    with TestClient(a):  # runs startup / shutdown (starts the worker pool)
        yield a


@pytest.fixture()
def new_client(app):
    return lambda: Api(app)


@pytest.fixture()
def admin(new_client):
    c = new_client()
    c.register("admin@x.io", "Admin")  # first account becomes admin
    return c


def grant(admin, uid, role):
    r = admin.post(f"/admin/users/{uid}/roles", {"role": role, "action": "grant"})
    assert r.status_code == 200, r.text


@pytest.fixture()
def films(app):
    """Three films with cast and a plot (RAG context)."""
    ids = []
    data = [
        (1, "Rosewood Heist", "2019-05-01", [("Mara Vell", "Mara Quill"), ("Tobin Ash", "Tobin Quill")],
         ["Thriller"], "Mara Quill steals a famous diamond from the palace vault. Her brother Tobin Quill betrays her to the king. "
         "In the final scene Mara dies in the burning tower while Tobin escapes with the diamond."),
        (2, "Quiet Harbour", "2015-03-01", [("Ines Roy", "Ines")], ["Drama"], ""),
        (3, "Dark Orbit", "2021-09-01", [("Lee Cho", "Captain Lee")], ["Sci-Fi"], ""),
    ]
    with app.state.db.session() as s:
        for tid, title, rd, cast, genres, plot in data:
            f = upsert_tmdb_film(s, {"id": tid, "title": title, "release_date": rd, "overview": f"{title} overview",
                                     "popularity": 10.0 * tid, "genres": [{"name": g} for g in genres],
                                     "credits": {"cast": [{"name": a, "character": c} for a, c in cast]},
                                     "keywords": {"keywords": [{"name": "heist"}]} if tid == 1 else {}})
            if plot:
                set_plot(s, f, plot, "seed")
            s.flush()
            ids.append(f.id)
    from app.services import jobs
    jobs.refit_shield_space(app)
    with app.state.db.session() as s:
        app.state.search.rebuild(s)
    return ids
