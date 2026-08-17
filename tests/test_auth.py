"""Access control (Step 7): loopback passes, non-loopback needs the token
(bearer header or the /login cookie), token rotation, password hashing, and
what stays public. Hermetic — a temp config file per test, never the real one."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src import config as cfgmod
from src import db as dbmod
from src.auth import COOKIE_NAME, hash_password, verify_password
from tests.conftest import write_test_config

LOOPBACK = ("127.0.0.1", 50000)
PHONE = ("100.101.102.103", 50000)  # a tailnet client
TOKEN = "t0ken-for-tests-only"


def _write_config(path: Path, token: str = "", password_hash: str = "") -> Path:
    write_test_config(path)                                  # sample, mirror / backup dirs blanked
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["auth"] = {"token": token, "password_hash": password_hash}
    path.write_text(json.dumps(raw), encoding="utf-8")
    return path


@pytest.fixture
def make_app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(dbmod.DB_PATH_ENV, str(tmp_path / "tasks.db"))

    def _make(token: str = TOKEN, password_hash: str = ""):
        cfg = _write_config(tmp_path / "config.json", token, password_hash)
        monkeypatch.setenv(cfgmod.CONFIG_PATH_ENV, str(cfg))
        from app.webapp.server import create_app

        return create_app()

    return _make


# ------------------------------------------------------------ the gate

def test_loopback_passes_without_credentials(make_app) -> None:
    with TestClient(make_app(), client=LOOPBACK) as c:
        assert c.get("/api/tasks").status_code == 200
        assert c.get("/").status_code == 200
        st = c.get("/api/status").json()
        assert st["auth"] == {"enabled": True, "password": False, "client": "loopback"}
        assert st["https"] is False


def test_non_loopback_api_401_and_page_redirects(make_app) -> None:
    with TestClient(make_app(), client=PHONE, follow_redirects=False) as c:
        r = c.get("/api/tasks")
        assert r.status_code == 401
        assert r.json()["error"]["code"] == "unauthorized"
        assert r.headers["WWW-Authenticate"].startswith("Bearer")
        r = c.get("/?project=3")
        assert r.status_code == 302
        assert r.headers["location"] == "/login?next=%2F%3Fproject%3D3"
        # what stays public
        assert c.get("/healthz").status_code == 200
        assert c.get("/api/version").status_code == 200
        assert c.get("/login").status_code == 200
        assert c.get("/static/manifest.webmanifest").status_code == 200
        assert c.get("/static/icons/icon-192.png").status_code == 200


def test_bearer_header_passes(make_app) -> None:
    with TestClient(make_app(), client=PHONE) as c:
        assert c.get("/api/tasks", headers={"Authorization": f"Bearer {TOKEN}"}).status_code == 200
        assert c.get("/api/tasks", headers={"Authorization": "Bearer nope"}).status_code == 401
        assert c.get("/api/status", headers={"Authorization": f"Bearer {TOKEN}"}).json()["auth"]["client"] == "token"


def test_login_with_token_sets_cookie_that_passes(make_app) -> None:
    with TestClient(make_app(), client=PHONE, follow_redirects=False) as c:
        bad = c.post("/api/login", json={"secret": "wrong"})
        assert bad.status_code == 401
        ok = c.post("/api/login", json={"secret": TOKEN})
        assert ok.status_code == 200 and ok.json()["via"] == "token"
        cookie = ok.headers["set-cookie"]
        assert cookie.startswith(f"{COOKIE_NAME}=") and "HttpOnly" in cookie and "Max-Age=7776000" in cookie
        # the TestClient jar now carries it — every /api/ call passes
        assert c.get("/api/tasks").status_code == 200
        assert c.get("/").status_code == 200
        assert c.get("/api/status").json()["auth"]["client"] == "token"
        # logout clears it
        assert c.post("/api/logout").status_code == 200
        assert c.get("/api/tasks").status_code == 401


def test_login_with_password_hands_back_the_token_cookie(make_app) -> None:
    with TestClient(make_app(password_hash=hash_password("correct horse")), client=PHONE) as c:
        assert c.post("/api/login", json={"secret": "wrong horse"}).status_code == 401
        ok = c.post("/api/login", json={"secret": "correct horse"})
        assert ok.status_code == 200 and ok.json()["via"] == "password"
        assert c.cookies.get(COOKIE_NAME) == TOKEN
        assert c.get("/api/tasks").status_code == 200


def test_no_token_configured_closes_the_gate_for_non_loopback(make_app) -> None:
    with TestClient(make_app(token=""), client=PHONE, follow_redirects=False) as c:
        r = c.get("/api/tasks")
        assert r.status_code == 401
        assert "gen_token" in r.json()["error"]["detail"]
        assert c.post("/api/login", json={"secret": "anything"}).status_code == 503
    with TestClient(make_app(token=""), client=LOOPBACK) as c:
        assert c.get("/api/tasks").status_code == 200
        assert c.get("/api/status").json()["auth"]["enabled"] is False


# ------------------------------------------------------- rotate + hashing

def test_token_rotate_signs_the_cookie_out(make_app, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    app = make_app()
    with TestClient(app, client=PHONE) as c:
        c.post("/api/login", json={"secret": TOKEN})
        assert c.get("/api/tasks").status_code == 200
        # rotate: scripts/gen_token.py --force writes a new auth.token
        cfg_path = tmp_path / "config.json"
        cfgmod.save_auth(token="rotated-token", path=cfg_path)
        assert json.loads(cfg_path.read_text(encoding="utf-8"))["auth"]["token"] == "rotated-token"
        app.state.config = cfgmod.load_config(cfg_path)  # what a restart does
        assert c.get("/api/tasks").status_code == 401
        assert c.get("/api/tasks", headers={"Authorization": "Bearer rotated-token"}).status_code == 200


def test_save_auth_creates_real_config_from_sample_and_keeps_other_keys(tmp_path: Path) -> None:
    target = tmp_path / "config.json"
    cfgmod.save_auth(token="abc", path=target)
    raw = json.loads(target.read_text(encoding="utf-8"))
    assert raw["auth"] == {"token": "abc", "password_hash": ""}
    assert raw["port"] == 8448 and "mirror" in raw          # copied from the sample
    cfgmod.save_auth(password_hash="h", path=target)
    raw = json.loads(target.read_text(encoding="utf-8"))
    assert raw["auth"] == {"token": "abc", "password_hash": "h"}  # token kept
    with pytest.raises(ValueError):
        cfgmod.save_auth(token="x", path=cfgmod.CONFIG_SAMPLE_PATH)


def test_sample_config_ships_with_auth_empty() -> None:
    cfg = cfgmod.load_config(cfgmod.CONFIG_SAMPLE_PATH)
    assert cfg.auth.token == "" and cfg.auth.password_hash == "" and not cfg.auth.enabled


def test_password_hash_roundtrip() -> None:
    h = hash_password("s3cret-phrase")
    assert h.startswith("pbkdf2_sha256$") and "s3cret-phrase" not in h
    assert verify_password("s3cret-phrase", h)
    assert not verify_password("s3cret-phras", h)
    assert not verify_password("s3cret-phrase", "garbage")
    assert hash_password("x") != hash_password("x")  # salted


def test_gen_token_and_set_password_scripts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    from scripts import gen_token, set_password

    target = tmp_path / "config.json"
    monkeypatch.setattr(cfgmod, "CONFIG_PATH", target)
    monkeypatch.setattr(gen_token, "CONFIG_PATH", target)
    monkeypatch.setattr(set_password, "CONFIG_PATH", target)
    assert set_password.main(["longenough"]) == 1        # no token yet
    assert gen_token.main([]) == 0
    first = json.loads(target.read_text(encoding="utf-8"))["auth"]["token"]
    assert len(first) >= 32
    assert gen_token.main([]) == 0                        # already set → no change
    assert json.loads(target.read_text(encoding="utf-8"))["auth"]["token"] == first
    assert gen_token.main(["--force"]) == 0
    second = json.loads(target.read_text(encoding="utf-8"))["auth"]["token"]
    assert second != first
    assert set_password.main(["short"]) == 1
    assert set_password.main(["longenough"]) == 0
    stored = json.loads(target.read_text(encoding="utf-8"))["auth"]["password_hash"]
    assert verify_password("longenough", stored)
    assert set_password.main(["--clear"]) == 0
    assert json.loads(target.read_text(encoding="utf-8"))["auth"]["password_hash"] == ""
    assert gen_token.main(["--clear"]) == 0
    assert json.loads(target.read_text(encoding="utf-8"))["auth"]["token"] == ""
    out = capsys.readouterr().out
    assert second in out
