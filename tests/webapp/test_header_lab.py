"""The temporary header variant lab: served same-origin, gated, page-local.

Only an installed iOS app shows the header softness, so the lab is how the
owner compares treatments on the device. These checks pin what makes it
usable there: the route answers inside the app's scope (so standalone mode
holds), a non-loopback client without a credential is refused like any page,
the twelve variants are the ones the page's buttons name, and no variant rule
leaks into a sheet the app itself loads.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src import db as dbmod

STATIC = Path(__file__).resolve().parents[2] / "app" / "webapp" / "static"
LAB_CSS = STATIC / "lab" / "header-lab.css"
LAB_JS = STATIC / "lab" / "header-lab.js"


@pytest.fixture(autouse=True)
def _temp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(dbmod.DB_PATH_ENV, str(tmp_path / "tasks.db"))


def _app():  # noqa: ANN202 - the FastAPI app factory's own type
    from app.webapp.server import create_app

    return create_app()


def test_lab_is_served_stamped_and_revalidated() -> None:
    with TestClient(_app(), client=("127.0.0.1", 50000)) as client:
        resp = client.get("/lab/header")
        assert resp.status_code == 200
        assert resp.headers["cache-control"].startswith("no-cache")
        assert re.search(r'/static/lab/header-lab\.js\?v=\w+', resp.text)
        assert re.search(r'/static/_vendored/nav/nav-tabs\.css\?v=\w+', resp.text)
        repeat = client.get("/lab/header", headers={"If-None-Match": resp.headers["etag"]})
        assert repeat.status_code == 304


def test_lab_is_gated_like_any_page() -> None:
    with TestClient(_app(), client=("100.64.0.9", 50000)) as client:
        resp = client.get("/lab/header", follow_redirects=False)
        assert resp.status_code in (302, 303, 307, 401)


def test_twelve_variants_each_named_and_applied() -> None:
    js = LAB_JS.read_text(encoding="utf-8")
    labels = re.search(r"const VARIANTS = \[(.*?)\];", js, flags=re.S).group(1)
    assert len(re.findall(r"^\s*'", labels, flags=re.M)) == 12
    css = LAB_CSS.read_text(encoding="utf-8")
    # Variant 1 is the control and 12 is applied in JS; every other one has a
    # CSS block keyed on html[data-v].
    for n in range(2, 12):
        assert f'html[data-v="{n}"]' in css, n
    assert 'html[data-v="1"]' not in css
    assert "variant !== 12" in js


def test_no_app_page_loads_the_lab_sheet() -> None:
    for page in ("index.html", "login.html"):
        text = (STATIC / page).read_text(encoding="utf-8")
        assert "header-lab." not in text, page
