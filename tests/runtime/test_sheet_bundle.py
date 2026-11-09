"""The index stylesheets are served as one bundle: same cascade, one request.

Deterministic on purpose (no timings): a phone's cold load queues one request per
sheet behind the browser's six connections, so the guard is on what the shell
asks for and on the bundle being exactly the sheets it replaces, in order.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src import db as dbmod
from src.static_versioning import (
    SHEET_BUNDLE_NAME,
    BuildInfo,
    index_sheets,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
STATIC = REPO_ROOT / "app" / "webapp" / "static"
SHEET_LINK = re.compile(r'<link rel="stylesheet" href="([^"]+)"')


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv(dbmod.DB_PATH_ENV, str(tmp_path / "tasks.db"))
    from app.webapp.server import create_app

    with TestClient(create_app(), client=("127.0.0.1", 50000)) as c:
        yield c


def _site(root: Path, sheets: dict[str, str]) -> Path:
    """A tiny static tree: an index linking ``sheets`` in order, plus the sheets."""
    static = root / "static"
    for rel, css in sheets.items():
        (static / rel).parent.mkdir(parents=True, exist_ok=True)
        (static / rel).write_text(css, encoding="utf-8")
    links = "".join(f'  <link rel="stylesheet" href="/static/{rel}">\n' for rel in sheets)
    (static / "index.html").write_text(
        f"<head>\n{links}</head>\n<body></body>\n", encoding="utf-8"
    )
    return static


def test_the_shell_links_its_sheets_one_by_one_during_the_bisect(client: TestClient) -> None:
    """The #616 bisect build serves the bundle but the shell does not ask for it."""
    r = client.get("/")
    links = SHEET_LINK.findall(r.text)
    sheets = index_sheets((STATIC / "index.html").read_text(encoding="utf-8"))
    hashes = client.app.state.build_info.asset_hashes
    assert links == [f"/static/{rel}?v={hashes[rel]}" for rel in sheets]


def test_the_bundle_is_the_index_sheets_in_cascade_order(client: TestClient) -> None:
    sheets = index_sheets((STATIC / "index.html").read_text(encoding="utf-8"))
    assert len(sheets) > 10
    body = client.get(f"/static/{SHEET_BUNDLE_NAME}").text
    positions = [body.index(f"/* {rel} */") for rel in sheets]
    assert positions == sorted(positions)
    for rel in sheets:
        assert (STATIC / rel).read_text(encoding="utf-8") in body


def test_the_bundle_is_cached_for_a_year_and_typed_as_css(client: TestClient) -> None:
    r = client.get(f"/static/{SHEET_BUNDLE_NAME}")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/css")
    assert "immutable" in r.headers["cache-control"]


def test_the_bundle_needs_no_credential(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A phone fetches it before sign-in, like every other ``/static/`` asset."""
    monkeypatch.setenv(dbmod.DB_PATH_ENV, str(tmp_path / "tasks.db"))
    from app.webapp.server import create_app

    with TestClient(create_app(), client=("100.64.0.9", 50000)) as remote:
        assert remote.get(f"/static/{SHEET_BUNDLE_NAME}").status_code == 200


def test_the_sign_in_card_keeps_its_own_links(client: TestClient) -> None:
    """Its sheet set differs from the index, so it must not receive the bundle."""
    page = (STATIC / "login.html").read_text(encoding="utf-8")
    if index_sheets(page) == client.app.state.build_info.bundled_sheets:
        pytest.skip("login.html links the same sheets as index.html")
    links = SHEET_LINK.findall(client.get("/login").text)
    assert links
    assert not any(SHEET_BUNDLE_NAME in href for href in links)


def test_an_edited_sheet_rotates_the_stamp_and_the_bundle(tmp_path: Path) -> None:
    static = _site(tmp_path, {"a.css": "a{color:red}", "b/c.css": "c{color:blue}"})
    before = BuildInfo(static, tmp_path)
    html = (static / "index.html").read_text(encoding="utf-8")
    first = before.stamp_html(html)
    assert before.sheet_bundle.index("a{color:red}") < before.sheet_bundle.index("c{color:blue}")

    (static / "b" / "c.css").write_text("c{color:green}", encoding="utf-8")
    after = BuildInfo(static, tmp_path)
    second = after.stamp_html(html)
    assert "c{color:green}" in after.sheet_bundle
    assert first != second, "a 304 or a year-cached bundle would otherwise outlive the edit"


def test_the_bundle_takes_the_first_links_place(tmp_path: Path) -> None:
    static = _site(tmp_path, {"a.css": "a{}", "b.css": "b{}"})
    html = (static / "index.html").read_text(encoding="utf-8")
    out = BuildInfo(static, tmp_path).stamp_html(html)
    assert out.count("<link") == 1
    assert out.index("<link") < out.index("</head>")


def test_a_page_with_other_sheets_is_left_alone(tmp_path: Path) -> None:
    static = _site(tmp_path, {"a.css": "a{}", "b.css": "b{}"})
    info = BuildInfo(static, tmp_path)
    other = '<link rel="stylesheet" href="/static/a.css">\n'
    out = info.stamp_html(other)
    assert SHEET_BUNDLE_NAME not in out
    assert "/static/a.css?v=" in out


def test_an_unhashed_sheet_disables_the_bundle(tmp_path: Path) -> None:
    """A sheet outside the hash map would sit stale behind an immutable bundle."""
    static = _site(tmp_path, {"a.css": "a{}", "vendor/lib.css": "v{}"})
    info = BuildInfo(static, tmp_path)
    assert info.sheet_bundle == ""
    html = (static / "index.html").read_text(encoding="utf-8")
    assert SHEET_BUNDLE_NAME not in info.stamp_html(html)
