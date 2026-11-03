"""The sign-in lock-out and its guessing alert, through the real ``/api/login``
route. Hermetic: a fake clock (nothing sleeps), a fake notifier (nothing
reaches Telegram) and a temp config; every secret here is synthetic."""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src import config as cfgmod
from src import db as dbmod
from src.login_guard import build_lockout
from src.notify import NotifierError
from tests.conftest import LOOPBACK, write_test_config

PHONE = ("100.101.102.103", 50000)  # a tailnet client
OTHER_PHONE = ("100.101.102.104", 50000)
TOKEN = "t0ken-for-tests-only"
WRONG = "guess-that-must-never-be-echoed"


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class FakeNotifier:
    def __init__(self, *, fail: bool = False) -> None:
        self.sent: list[str] = []
        self.fail = fail

    def send_text(self, text: str) -> None:
        self.sent.append(text)
        if self.fail:
            raise NotifierError("telegram down")


def _drain_alert_threads() -> None:
    for t in threading.enumerate():
        if t.name == "login-alert":
            t.join(timeout=5)


@pytest.fixture
def rig(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """``(app, clock, notifier)`` — the app's lock-out rebuilt on the fakes."""
    monkeypatch.setenv(dbmod.DB_PATH_ENV, str(tmp_path / "tasks.db"))
    path = write_test_config(tmp_path / "config.json")
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["auth"] = {"token": TOKEN, "password_hash": ""}
    path.write_text(json.dumps(raw), encoding="utf-8")
    monkeypatch.setenv(cfgmod.CONFIG_PATH_ENV, str(path))
    from app.webapp.server import create_app

    app = create_app()
    clock, notifier = FakeClock(), FakeNotifier()
    app.state.login_lockout = build_lockout(notifier, clock=clock)
    return app, clock, notifier


def _wrong(c: TestClient):
    return c.post("/api/login", json={"secret": WRONG})


def test_six_wrong_passwords_401_then_429_with_retry_after_then_the_normal_reply(rig) -> None:
    app, clock, _ = rig
    with TestClient(app, client=PHONE) as c:
        assert [_wrong(c).status_code for _ in range(6)] == [401] * 6
        locked = _wrong(c)
        assert locked.status_code == 429
        assert int(locked.headers["Retry-After"]) >= 1
        # a locked client is refused before its secret is read, even a right one
        assert c.post("/api/login", json={"secret": TOKEN}).status_code == 429
        clock.now += float(locked.headers["Retry-After"])
        ok = c.post("/api/login", json={"secret": TOKEN})
        assert ok.status_code == 200 and ok.json() == {"ok": True, "via": "token"}
        assert _wrong(c).status_code == 401  # a correct sign-in cleared the streak


def test_a_correct_sign_in_resets_the_count(rig) -> None:
    app, _, _ = rig
    with TestClient(app, client=PHONE) as c:
        for _ in range(5):
            assert _wrong(c).status_code == 401
        assert c.post("/api/login", json={"secret": TOKEN}).status_code == 200
        assert [_wrong(c).status_code for _ in range(6)] == [401] * 6


def test_one_client_locked_does_not_lock_another(rig) -> None:
    app, _, _ = rig
    with TestClient(app, client=PHONE) as c:
        for _ in range(7):
            _wrong(c)
        assert _wrong(c).status_code == 429
    with TestClient(app, client=OTHER_PHONE) as other:
        assert other.post("/api/login", json={"secret": TOKEN}).status_code == 200


def test_the_pc_itself_is_never_locked_out(rig) -> None:
    app, _, notifier = rig
    with TestClient(app, client=LOOPBACK) as c:
        assert [_wrong(c).status_code for _ in range(12)] == [401] * 12
        assert c.post("/api/login", json={"secret": TOKEN}).status_code == 200
    _drain_alert_threads()
    assert notifier.sent == []


def test_three_wrong_passwords_raise_exactly_one_alert_without_the_secret(rig) -> None:
    app, _, notifier = rig
    with TestClient(app, client=PHONE) as c:
        _wrong(c)
        _wrong(c)
        _drain_alert_threads()
        assert notifier.sent == []
        _wrong(c)
        _drain_alert_threads()
        assert len(notifier.sent) == 1
        text = notifier.sent[0]
        assert "task-os" in text and PHONE[0] in text and "3" in text
        assert WRONG not in text and TOKEN not in text
        for _ in range(3):  # the same streak never raises a second one
            _wrong(c)
        _drain_alert_threads()
        assert len(notifier.sent) == 1


def test_a_failing_notifier_does_not_break_the_login(rig) -> None:
    app, _, _ = rig
    notifier = FakeNotifier(fail=True)
    app.state.login_lockout = build_lockout(notifier)
    with TestClient(app, client=PHONE) as c:
        assert [_wrong(c).status_code for _ in range(3)] == [401] * 3
        _drain_alert_threads()
        assert len(notifier.sent) == 1
        assert c.post("/api/login", json={"secret": TOKEN}).status_code == 200


def test_alerts_config_falls_back_to_none_when_telegram_is_half_filled() -> None:
    assert cfgmod._alerts_config({}).notifier == "none"
    assert cfgmod._alerts_config({"notifier": "telegram", "telegram_bot_token": "x"}).notifier == "none"
    assert cfgmod._alerts_config({"notifier": "carrier-pigeon"}).notifier == "none"
    full = {"notifier": "Telegram", "telegram_bot_token": "x", "telegram_chat_id": "1"}
    assert cfgmod._alerts_config(full).notifier == "telegram"
