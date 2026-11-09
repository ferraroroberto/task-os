"""The temporary header offset lab: served same-origin, gated, page-local.

Only an installed iOS app shows the header softness, so the lab is how the
owner compares content offsets on the device. These checks pin what makes it
usable there: the route answers inside the app's scope (so standalone mode
holds), a non-loopback client without a credential is refused like any page,
the thirteen variants are the ones the page's buttons name, the offsets move
the content by padding alone, and no variant rule leaks into a sheet the app
itself loads.
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


def test_thirteen_variants_each_named_and_applied() -> None:
    js = LAB_JS.read_text(encoding="utf-8")
    labels = re.search(r"const VARIANTS = \[(.*?)\];", js, flags=re.S).group(1)
    captions = re.findall(r"^\s*\['([^']+)'", labels, flags=re.M)
    assert len(captions) == 13
    css = LAB_CSS.read_text(encoding="utf-8")
    # Variant 1 is the control; 2-11 each set the offset their button names,
    # applied as plain padding on the page container; 12 and 13 show the
    # status-bar spacer, and 13 alone starts scrolled past it.
    for n, caption in zip(range(2, 12), captions[1:11], strict=True):
        assert f'html[data-v="{n}"] {{ --lab-offset: {caption}; }}' in css, n
    assert "padding-top: calc(env(safe-area-inset-top, 0px) + var(--lab-offset, 0px))" in css
    for n in (12, 13):
        assert f'html[data-v="{n}"] .lab-spacer' in css, n
    assert 'html[data-v="1"]' not in css
    assert "FIRST_FRAME_PAST_SPACER = 13" in js
    page = (STATIC / "lab" / "header.html").read_text(encoding="utf-8")
    assert "v >= 1 && v <= 13" in page


def test_offset_variants_add_no_layer_or_filter() -> None:
    css = LAB_CSS.read_text(encoding="utf-8")
    for prop in ("transform", "will-change", "filter"):
        assert not re.search(rf"^\s*[\w-]*{prop}\s*:", css, flags=re.M), prop


def test_no_app_page_loads_the_lab_sheet() -> None:
    for page in ("index.html", "login.html"):
        text = (STATIC / page).read_text(encoding="utf-8")
        assert "header-lab." not in text, page
