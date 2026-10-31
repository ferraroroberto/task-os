"""Access control (Step 7): loopback passes, non-loopback needs the token
(bearer header or the /login cookie), token rotation, password hashing, and
what stays public — plus team mode (Step 12): the team password's cookie, the
pick-your-name step and the picked name as author. Hermetic — a temp config
file per test, never the real one; every secret here is synthetic."""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src import config as cfgmod
from src import db as dbmod
from src import team as teammod
from src.auth import COOKIE_NAME, TEAM_COOKIE, hash_password, team_session, verify_password
from src.team import NAME_COOKIE
from tests.conftest import LOOPBACK, write_test_config

PHONE = ("100.101.102.103", 50000)  # a tailnet client
TOKEN = "t0ken-for-tests-only"


def _write_config(
    path: Path, token: str = "", password_hash: str = "", team: dict | None = None,
    auth_people: dict | None = None, people: list | None = None,
) -> Path:
    write_test_config(path)                                  # sample, mirror / backup dirs blanked
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["auth"] = {"token": token, "password_hash": password_hash}
    if team is not None:
        raw["team"] = team
    if auth_people is not None:
        raw["auth"]["people"] = auth_people
    if people is not None:
        raw["people"] = people
    path.write_text(json.dumps(raw), encoding="utf-8")
    return path


@pytest.fixture
def make_app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(dbmod.DB_PATH_ENV, str(tmp_path / "tasks.db"))

    def _make(token: str = TOKEN, password_hash: str = "", team: dict | None = None,
              auth_people: dict | None = None, people: list | None = None):
        cfg = _write_config(tmp_path / "config.json", token, password_hash, team, auth_people, people)
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


def answers(*values: str):
    """A ``read_secret`` that hands back the given entries in order (the prompt text is ignored)."""
    it = iter(values)
    return lambda prompt: next(it)


def test_gen_token_and_set_password_scripts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    from scripts import gen_token, set_password

    target = tmp_path / "config.json"
    monkeypatch.setattr(cfgmod, "CONFIG_PATH", target)
    monkeypatch.setattr(gen_token, "CONFIG_PATH", target)
    monkeypatch.setattr(set_password, "CONFIG_PATH", target)
    assert set_password.main([], read_secret=answers("longenough", "longenough")) == 1   # no token yet
    assert gen_token.main([]) == 0
    first = json.loads(target.read_text(encoding="utf-8"))["auth"]["token"]
    assert len(first) >= 32
    assert gen_token.main([]) == 0                        # already set → no change
    assert json.loads(target.read_text(encoding="utf-8"))["auth"]["token"] == first
    assert gen_token.main(["--force"]) == 0
    second = json.loads(target.read_text(encoding="utf-8"))["auth"]["token"]
    assert second != first
    assert set_password.main([], read_secret=answers("short", "short")) == 1
    assert set_password.main([], read_secret=answers("longenough", "different1")) == 1
    assert set_password.main([], read_secret=answers("longenough", "longenough")) == 0
    stored = json.loads(target.read_text(encoding="utf-8"))["auth"]["password_hash"]
    assert verify_password("longenough", stored)
    assert set_password.main(["--clear"]) == 0
    assert json.loads(target.read_text(encoding="utf-8"))["auth"]["password_hash"] == ""
    assert gen_token.main(["--clear"]) == 0
    assert json.loads(target.read_text(encoding="utf-8"))["auth"]["token"] == ""
    out = capsys.readouterr().out
    assert second in out


# ------------------------------------------------------------ team mode (Step 12)

TEAM_PASSWORD = "team-pass-for-tests"
TEAM_HASH = hash_password(TEAM_PASSWORD)
PEOPLE = ["Alex Chen", "Sam Rivera", "Jordan Lee"]


def _team(enabled: bool = True, password_hash: str = TEAM_HASH, people: list[str] | None = None) -> dict:
    return {"enabled": enabled, "people": PEOPLE if people is None else people, "password_hash": password_hash}


def _task(c: TestClient) -> int:
    return c.post("/api/tasks", json={"title": "Team story task"}).json()["id"]


def test_team_off_is_the_step_7_model_unchanged(make_app) -> None:
    """A team password in the file and team cookies in the jar change nothing while team.enabled is false."""
    app = make_app(team=_team(enabled=False))
    session = team_session(app.state.config.auth, cfgmod.TeamConfig(enabled=True, people=PEOPLE, password_hash=TEAM_HASH))
    with TestClient(app, client=PHONE, follow_redirects=False) as c:
        assert c.post("/api/login", json={"secret": TEAM_PASSWORD}).status_code == 401
        c.cookies.set(TEAM_COOKIE, session)
        assert c.get("/api/tasks").status_code == 401
        assert c.get("/").headers["location"] == "/login?next=%2F"
        ok = c.post("/api/login", json={"secret": TOKEN})
        assert ok.json() == {"ok": True, "via": "token"}
        assert len(ok.headers.get_list("set-cookie")) == 1                      # the token cookie alone
        c.cookies.set(NAME_COOKIE, "Sam%20Rivera")
        tid = _task(c)
        assert c.post(f"/api/tasks/{tid}/comments", json={"body": "hi"}).json()["author"] == "Alex Chen"  # people[0], never the cookie
        assert c.get("/api/team").json() == {"enabled": False, "people": [], "you": None}
        refused = c.post("/api/team/name", json={"name": "Sam Rivera"})
        assert refused.status_code == 409 and refused.json()["error"]["code"] == "team_disabled"
        assert len(c.post("/api/logout").headers.get_list("set-cookie")) == 1


def test_team_password_signs_in_without_the_token_then_a_name_is_required(make_app) -> None:
    with TestClient(make_app(team=_team()), client=PHONE, follow_redirects=False) as c:
        assert c.post("/api/login", json={"secret": "not-the-team-password"}).status_code == 401
        ok = c.post("/api/login", json={"secret": TEAM_PASSWORD})
        assert ok.status_code == 200 and ok.json() == {"ok": True, "via": "team", "you": None}
        cookie = ok.headers["set-cookie"]
        assert cookie.startswith(f"{TEAM_COOKIE}=") and "HttpOnly" in cookie and "SameSite=lax" in cookie
        assert COOKIE_NAME not in c.cookies                       # a teammate never holds the owner's token
        assert TOKEN not in cookie and TEAM_HASH not in cookie
        # through the gate, but no page until a name is picked
        assert c.get("/api/tasks").status_code == 200
        assert c.get("/api/status").json()["auth"]["client"] == "team"
        r = c.get("/?project=3")
        assert r.status_code == 302 and r.headers["location"] == "/login?step=name&next=%2F%3Fproject%3D3"
        assert c.get("/login").status_code == 200                 # no redirect loop
        assert c.get("/api/team").json() == {
            "enabled": True, "people": [{"name": n, "avatar": None} for n in PEOPLE], "you": None,
        }
        bad = c.post("/api/team/name", json={"name": "Someone Else"})
        assert bad.status_code == 422 and bad.json()["error"]["code"] == "validation_error"
        picked = c.post("/api/team/name", json={"name": "Sam Rivera"})
        assert picked.json() == {"ok": True, "you": "Sam Rivera"}
        name_cookie = picked.headers["set-cookie"]
        assert name_cookie.startswith(f"{NAME_COOKIE}=Sam%20Rivera;") and "HttpOnly" in name_cookie
        assert c.get("/").status_code == 200
        assert c.get("/api/team").json()["you"] == "Sam Rivera"
        # the picked name is the author and the actor
        tid = _task(c)
        comment = c.post(f"/api/tasks/{tid}/comments", json={"body": "quote: https://example.com/q"}).json()
        assert comment["author"] == "Sam Rivera"
        c.patch(f"/api/tasks/{tid}", json={"priority": "high"})
        top = c.get(f"/api/tasks/{tid}").json()["activity"][0]
        assert (top["field"], top["actor"]) == ("priority", "Sam Rivera")
        # an explicit actor still wins (the name is a label, not a credential)
        assert c.post(f"/api/tasks/{tid}/comments", json={"body": "x", "author": "cli"}).json()["author"] == "cli"
        # sign-out clears all three
        out = c.post("/api/logout").headers.get_list("set-cookie")
        assert sorted(h.split("=", 1)[0] for h in out) == sorted([COOKIE_NAME, TEAM_COOKIE, NAME_COOKIE])
        assert c.get("/api/tasks").status_code == 401


def test_team_cookie_dies_with_a_token_rotation_or_a_new_team_password(make_app, tmp_path: Path) -> None:
    app = make_app(team=_team())
    with TestClient(app, client=PHONE) as c:
        c.post("/api/login", json={"secret": TEAM_PASSWORD})
        assert c.get("/api/tasks").status_code == 200
        cfg_path = tmp_path / "config.json"
        cfgmod.save_team_password_hash(hash_password("a-new-team-password"), path=cfg_path)
        app.state.config = cfgmod.load_config(cfg_path)           # what a restart does
        assert c.get("/api/tasks").status_code == 401
        assert c.post("/api/login", json={"secret": "a-new-team-password"}).status_code == 200
        assert c.get("/api/tasks").status_code == 200
        cfgmod.save_auth(token="rotated-token", path=cfg_path)
        app.state.config = cfgmod.load_config(cfg_path)
        assert c.get("/api/tasks").status_code == 401


def test_team_mode_without_a_token_stays_closed(make_app) -> None:
    app = make_app(token="", team=_team())
    assert team_session(app.state.config.auth, app.state.config.team) is None
    with TestClient(app, client=PHONE) as c:
        assert c.post("/api/login", json={"secret": TEAM_PASSWORD}).status_code == 503
        c.cookies.set(TEAM_COOKIE, "")
        assert c.get("/api/tasks").status_code == 401
    # …and team mode with no team password accepts no team sign-in
    with TestClient(make_app(team=_team(password_hash="")), client=PHONE) as c:
        assert c.post("/api/login", json={"secret": TEAM_PASSWORD}).status_code == 401


def test_loopback_owner_is_never_asked_for_a_name_but_can_pick_one(make_app) -> None:
    with TestClient(make_app(team=_team()), client=LOOPBACK) as c:
        assert c.get("/").status_code == 200
        tid = _task(c)
        assert c.post(f"/api/tasks/{tid}/comments", json={"body": "a"}).json()["author"] == "Alex Chen"  # people[0]
        c.post("/api/team/name", json={"name": "Jordan Lee"})
        assert c.post(f"/api/tasks/{tid}/comments", json={"body": "b"}).json()["author"] == "Jordan Lee"
        # a name dropped from the config is ignored, not trusted; the jar is cleared first because a
        # bare set() beside the server's cookie leaves two same-named cookies whose send order is the client's
        c.cookies.clear()
        c.cookies.set(NAME_COOKIE, "Former%20Member")
        assert c.post(f"/api/tasks/{tid}/comments", json={"body": "c"}).json()["author"] == "Alex Chen"


_BYTES_SOURCES = {"encode", "pbkdf2_hmac", "b64decode", "digest"}


def _bytes_valued(arg: ast.expr, scope: ast.AST) -> bool:
    """A call that returns bytes, or a name this scope binds from one."""
    if isinstance(arg, ast.Call):
        return isinstance(arg.func, ast.Attribute) and arg.func.attr in _BYTES_SOURCES
    if isinstance(arg, ast.Name):
        return any(
            isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == arg.id for t in n.targets)
            and _bytes_valued(n.value, scope)
            for n in ast.walk(scope)
        )
    return False


def test_compare_digest_is_only_ever_handed_bytes() -> None:
    """Structural: ``hmac.compare_digest`` raises ``TypeError`` for a non-ASCII ``str``, so a
    cookie or header value compared as text turns a stray byte into a 500 on every path.
    Every call in ``src/`` and ``app/`` must pass bytes it built (``.encode``, a digest)."""
    root = Path(__file__).resolve().parent.parent
    offenders: list[str] = []
    for path in [*(root / "src").rglob("*.py"), *(root / "app").rglob("*.py")]:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for scope in ast.walk(tree):
            if not isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for call in ast.walk(scope):
                if (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
                        and call.func.attr == "compare_digest"
                        and not all(_bytes_valued(arg, scope) for arg in call.args)):
                    offenders.append(f"{path.relative_to(root).as_posix()}:{call.lineno}")
    assert not offenders, f"compare_digest on a value not provably bytes: {offenders}"


def test_a_non_ascii_team_cookie_is_no_one_never_a_server_error(make_app) -> None:
    """``compare_digest`` refuses a non-ASCII ``str``; a stray cookie must be refused, not crash the gate."""
    with TestClient(make_app(team=_team()), client=PHONE, raise_server_exceptions=False) as c:
        for path, refused in (("/login", 200), ("/api/tasks", 401)):
            res = c.get(path, headers={"cookie": (TEAM_COOKIE + "=café").encode("utf-8")}, follow_redirects=False)
            assert res.status_code == refused, (path, res.status_code)


def test_team_cookies_are_secure_over_https(make_app) -> None:
    with TestClient(make_app(team=_team()), client=PHONE, base_url="https://testserver") as c:
        assert "Secure" in c.post("/api/login", json={"secret": TEAM_PASSWORD}).headers["set-cookie"]
        assert "Secure" in c.post("/api/team/name", json={"name": "Alex Chen"}).headers["set-cookie"]


def test_team_avatars_come_from_the_avatars_dir_by_slug(make_app, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    avatars = tmp_path / "avatars"
    avatars.mkdir()
    (avatars / "sam-rivera.png").write_bytes(b"\x89PNG\r\n\x1a\nfake")
    monkeypatch.setattr(teammod, "AVATARS_DIR", avatars)
    assert teammod.slug("  Sam  Rivera! ") == "sam-rivera"
    with TestClient(make_app(team=_team()), client=LOOPBACK) as c:
        assert c.get("/api/team").json()["people"] == [
            {"name": "Alex Chen", "avatar": None},
            {"name": "Sam Rivera", "avatar": "/api/team/avatars/1"},
            {"name": "Jordan Lee", "avatar": None},
        ]
        img = c.get("/api/team/avatars/1")
        assert img.status_code == 200 and img.content.endswith(b"fake")
        assert c.get("/api/team/avatars/0").status_code == 404   # no file
        assert c.get("/api/team/avatars/9").status_code == 404   # no such person
    with TestClient(make_app(team=_team()), client=PHONE) as c:
        assert c.get("/api/team/avatars/1").status_code == 401   # gated like every /api/ path


def test_sample_config_ships_team_mode_off_with_no_password() -> None:
    cfg = cfgmod.load_config(cfgmod.CONFIG_SAMPLE_PATH)
    assert cfg.team.enabled is False and cfg.team.password_hash == ""


def test_set_team_password_script(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    from scripts import gen_token, set_team_password

    target = tmp_path / "config.json"
    monkeypatch.setattr(cfgmod, "CONFIG_PATH", target)
    monkeypatch.setattr(gen_token, "CONFIG_PATH", target)
    monkeypatch.setattr(set_team_password, "CONFIG_PATH", target)

    assert set_team_password.main([], read_secret=answers("longenough", "longenough")) == 1   # no token yet
    assert gen_token.main([]) == 0
    raw = json.loads(target.read_text(encoding="utf-8"))
    raw["team"] = {"enabled": True, "people": PEOPLE}
    target.write_text(json.dumps(raw), encoding="utf-8")
    assert set_team_password.main([], read_secret=answers("short", "short")) == 1
    assert set_team_password.main([], read_secret=answers("longenough", "different1")) == 1
    assert set_team_password.main([], read_secret=answers("longenough", "longenough")) == 0
    team = json.loads(target.read_text(encoding="utf-8"))["team"]
    assert team["enabled"] is True and team["people"] == PEOPLE      # the rest of the block is kept
    assert verify_password("longenough", team["password_hash"])
    assert set_team_password.main(["--clear"]) == 0
    assert json.loads(target.read_text(encoding="utf-8"))["team"]["password_hash"] == ""
    assert "longenough" not in capsys.readouterr().out
    with pytest.raises(ValueError):
        cfgmod.save_team_password_hash("h", path=cfgmod.CONFIG_SAMPLE_PATH)


# ------------------------------------------------- one token per person (#474)
# The sample's members are time.people's p1 ("Person 1", the owner) and p2.

P2_TOKEN = "p2-token-for-tests-only"
P2_PASSWORD = "p2-password-for-tests"


def _two_members(make_app, p2_hash: str = "", **kwargs):
    return make_app(auth_people={"p2": {"token": P2_TOKEN, "password_hash": p2_hash}}, **kwargs)


def test_members_fall_back_from_people_to_time_people_to_the_implicit_owner(tmp_path: Path) -> None:
    sample = cfgmod.load_config(cfgmod.CONFIG_SAMPLE_PATH)
    assert [p.id for p in sample.people] == ["p1", "p2"] and sample.owner.id == "p1"
    assert sample.auth.owner == "p1"
    cfg = _write_config(tmp_path / "c.json", team=_team(enabled=False))
    assert cfgmod.load_config(cfg).team.people == PEOPLE        # no people block: team.people as is
    cfg = _write_config(tmp_path / "c.json", people=[{"id": "a", "name": "Ada"}, {"id": "b", "name": "Bo"}])
    loaded = cfgmod.load_config(cfg)
    assert [p.id for p in loaded.people] == ["a", "b"]
    assert loaded.team.people == ["Ada", "Bo"]                 # the name step lists the members
    assert [p.id for p in loaded.time.people] == ["p1", "p2"]  # time.people still wins for Time
    raw = json.loads(cfg.read_text(encoding="utf-8"))
    del raw["time"]["people"]
    cfg.write_text(json.dumps(raw), encoding="utf-8")
    assert [p.id for p in cfgmod.load_config(cfg).time.people] == ["a", "b"]  # …and falls back on people
    del raw["people"]
    cfg.write_text(json.dumps(raw), encoding="utf-8")
    assert cfgmod.load_config(cfg).people == (cfgmod.IMPLICIT_PERSON,)


def test_a_members_token_passes_the_gate_and_names_them(make_app) -> None:
    with TestClient(_two_members(make_app), client=PHONE) as c:
        assert c.get("/api/me").status_code == 401                               # gated like every /api/ route
        me = c.get("/api/me", headers={"Authorization": f"Bearer {P2_TOKEN}"}).json()
        assert (me["id"], me["name"], me["via"]) == ("p2", "Person 2", "token")
        assert me["people"] == [{"id": "p1", "name": "Person 1"}, {"id": "p2", "name": "Person 2"}]
        owner = c.get("/api/me", headers={"Authorization": f"Bearer {TOKEN}"}).json()
        assert (owner["id"], owner["name"], owner["via"]) == ("p1", "Person 1", "token")
        st = c.get("/api/status", headers={"Authorization": f"Bearer {P2_TOKEN}"}).json()
        assert st["auth"] == {"enabled": True, "password": False, "client": "token"}  # the status shape is unchanged
        # the cookie: a member's token at /login comes back as their own cookie
        ok = c.post("/api/login", json={"secret": P2_TOKEN})
        assert ok.json() == {"ok": True, "via": "token"} and c.cookies.get(COOKIE_NAME) == P2_TOKEN
        assert c.get("/api/me").json()["id"] == "p2"


def test_a_members_password_hands_back_their_own_token(make_app) -> None:
    app = _two_members(make_app, password_hash=hash_password("owner horse"), p2_hash=hash_password(P2_PASSWORD))
    with TestClient(app, client=PHONE) as c:
        assert c.post("/api/login", json={"secret": "wrong horse"}).status_code == 401
        ok = c.post("/api/login", json={"secret": P2_PASSWORD})
        assert ok.status_code == 200 and ok.json()["via"] == "password"
        assert c.cookies.get(COOKIE_NAME) == P2_TOKEN
        assert c.get("/api/me").json()["name"] == "Person 2"
        c.cookies.clear()
        c.post("/api/login", json={"secret": "owner horse"})
        assert c.cookies.get(COOKIE_NAME) == TOKEN                                # the owner's is unchanged


def test_a_members_password_without_their_token_unlocks_nothing(make_app) -> None:
    app = make_app(auth_people={"p2": {"token": "", "password_hash": hash_password(P2_PASSWORD)}})
    with TestClient(app, client=PHONE) as c:
        assert c.post("/api/login", json={"secret": P2_PASSWORD}).status_code == 401


def test_a_members_token_alone_keeps_the_gate_closed_to_everyone_else(make_app) -> None:
    app = make_app(token="", auth_people={"p2": {"token": P2_TOKEN}})
    with TestClient(app, client=PHONE) as c:
        assert c.get("/api/tasks").status_code == 401
        assert c.post("/api/login", json={"secret": "anything"}).status_code == 401
        assert c.get("/api/tasks", headers={"Authorization": f"Bearer {P2_TOKEN}"}).status_code == 200


def test_removing_a_member_signs_them_out(make_app, tmp_path: Path) -> None:
    app = _two_members(make_app)
    with TestClient(app, client=PHONE) as c:
        c.post("/api/login", json={"secret": P2_TOKEN})
        assert c.get("/api/tasks").status_code == 200
        cfg_path = tmp_path / "config.json"
        raw = json.loads(cfg_path.read_text(encoding="utf-8"))
        raw["time"]["people"] = [{"id": "p1", "name": "Person 1"}]          # p2 leaves; their secret stays in the file
        cfg_path.write_text(json.dumps(raw), encoding="utf-8")
        app.state.config = cfgmod.load_config(cfg_path)                       # what a restart does
        assert c.get("/api/tasks").status_code == 401
        assert c.get("/api/tasks", headers={"Authorization": f"Bearer {P2_TOKEN}"}).status_code == 401
        assert c.get("/api/tasks", headers={"Authorization": f"Bearer {TOKEN}"}).status_code == 200


def test_the_team_cookie_is_still_keyed_on_the_owners_token_alone(make_app) -> None:
    plain = make_app(team=_team())
    before = team_session(plain.state.config.auth, plain.state.config.team)
    withp2 = _two_members(make_app, team=_team())
    assert team_session(withp2.state.config.auth, withp2.state.config.team) == before
    with TestClient(withp2, client=PHONE) as c:
        assert c.post("/api/login", json={"secret": TEAM_PASSWORD}).json()["via"] == "team"
        me = c.get("/api/me").json()
        assert (me["id"], me["name"], me["via"]) == (None, None, "team")     # no name picked yet
        c.post("/api/team/name", json={"name": "Sam Rivera"})
        assert c.get("/api/me").json() == {**me, "name": "Sam Rivera"}       # a team name, not a member


def test_loopback_is_the_owner_unless_it_presents_a_members_cookie(make_app) -> None:
    with TestClient(_two_members(make_app), client=LOOPBACK) as c:
        me = c.get("/api/me").json()
        assert (me["id"], me["name"], me["via"]) == ("p1", "Person 1", "loopback")
        c.cookies.set(COOKIE_NAME, P2_TOKEN)
        me = c.get("/api/me").json()
        assert (me["id"], me["via"]) == ("p2", "token")
        assert c.get("/api/status").json()["auth"]["client"] == "loopback"   # the gate's verdict is unchanged
        c.cookies.set(COOKIE_NAME, "not-a-token")
        assert c.get("/api/me").json()["id"] == "p1"                         # a bad cookie is no one: the owner
        me = c.get("/api/me", headers={"Cookie": f"{COOKIE_NAME}=caf\xe9".encode("latin-1")}).json()
        assert me["id"] == "p1"                                              # …a non-ASCII one too, never a 500


def test_time_logs_as_the_viewer_unless_the_body_names_someone(make_app) -> None:
    """#475: a write that leaves ``person`` out is the viewer's; an explicit one wins."""
    app = _two_members(make_app)
    as_p2 = {"Authorization": f"Bearer {P2_TOKEN}"}
    with TestClient(app, client=PHONE) as c:
        assert c.get("/api/time/meta", headers=as_p2).json()["you"] == "p2"
        assert c.get("/api/time/meta", headers={"Authorization": f"Bearer {TOKEN}"}).json()["you"] == "p1"
        cat = c.get("/api/time/meta", headers=as_p2).json()["areas"][0]["categories"][0]["id"]
        started = c.post("/api/time/timers", json={"category_id": cat}, headers=as_p2)
        assert started.status_code == 201 and started.json()["timer"]["person"] == "p2"
        assert [t["person"] for t in c.get("/api/time/timers", headers=as_p2).json()["items"]] == ["p2"]
        assert c.post("/api/time/timers/p2/stop", headers=as_p2).json()["person"] == "p2"
        body = {"category_id": cat, "day": "2026-10-14", "minutes": 5}
        assert c.post("/api/time/entries", json=body, headers=as_p2).json()["person"] == "p2"
        explicit = c.post("/api/time/entries", json={**body, "person": "p1"}, headers=as_p2)
        assert explicit.json()["person"] == "p1"                                  # an explicit person still works
        put = c.put("/api/time/entries/by-source/usage:test:2026-10-14", json=body, headers=as_p2)
        assert put.status_code == 201 and put.json()["person"] == "p2"
        assert c.get("/api/time/recent", headers=as_p2).json() == {"person": "p2", "category_ids": [cat]}
        assert c.get("/api/time/recent?person=p1", headers=as_p2).json()["person"] == "p1"


def test_time_on_loopback_logs_as_the_owner_and_a_non_member_must_say_who(make_app) -> None:
    with TestClient(_two_members(make_app), client=LOOPBACK) as c:
        meta = c.get("/api/time/meta").json()
        assert meta["you"] == "p1"
        cat = meta["areas"][0]["categories"][0]["id"]
        made = c.post("/api/time/entries", json={"category_id": cat, "day": "2026-10-14", "minutes": 5})
        assert made.json()["person"] == "p1"
        # …and the owner at the PC can still log for the other person
        other = c.post("/api/time/entries", json={"category_id": cat, "day": "2026-10-14", "minutes": 5, "person": "p2"})
        assert other.json()["person"] == "p2"
    team = _team()
    with TestClient(make_app(team=team), client=PHONE) as c:
        c.post("/api/login", json={"secret": TEAM_PASSWORD})
        c.post("/api/team/name", json={"name": "Sam Rivera"})                     # a team name, no member
        meta = c.get("/api/time/meta").json()
        assert meta["you"] is None
        cat = meta["areas"][0]["categories"][0]["id"]
        refused = c.post("/api/time/timers", json={"category_id": cat})
        assert refused.status_code == 422 and "person is required" in refused.json()["error"]["message"]
        assert c.post("/api/time/timers", json={"category_id": cat, "person": "p2"}).status_code == 201


def test_a_member_signs_what_they_write_and_the_owner_is_unchanged(make_app) -> None:
    app = _two_members(make_app, team=_team(enabled=False))
    with TestClient(app, client=PHONE) as c:
        c.post("/api/login", json={"secret": P2_TOKEN})
        tid = _task(c)
        assert c.post(f"/api/tasks/{tid}/comments", json={"body": "mine"}).json()["author"] == "Person 2"
        c.patch(f"/api/tasks/{tid}", json={"priority": "high"})
        top = c.get(f"/api/tasks/{tid}").json()["activity"][0]
        assert (top["field"], top["actor"]) == ("priority", "Person 2")
        assert c.post(f"/api/tasks/{tid}/comments", json={"body": "x", "author": "cli"}).json()["author"] == "cli"
        hdr = {"X-Actor": "bot"}
        assert c.post(f"/api/tasks/{tid}/comments", json={"body": "y"}, headers=hdr).json()["author"] == "bot"
    with TestClient(app, client=LOOPBACK) as c:
        # the owner keeps the name they sign with now (team.people[0]) until a people block names them
        assert c.post(f"/api/tasks/{tid}/comments", json={"body": "owner"}).json()["author"] == "Alex Chen"


def test_gen_token_and_set_password_for_a_person(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    from scripts import gen_token, set_password

    target = tmp_path / "config.json"
    write_test_config(target)
    monkeypatch.setattr(cfgmod, "CONFIG_PATH", target)
    monkeypatch.setattr(gen_token, "CONFIG_PATH", target)
    monkeypatch.setattr(set_password, "CONFIG_PATH", target)
    assert gen_token.main(["--person", "nobody"]) == 1                    # not a member
    assert gen_token.main(["--person", "p1"]) == 1                        # the owner: no --person
    both = answers("longenough", "longenough")
    assert set_password.main(["--person", "nobody"], read_secret=both) == 1
    assert set_password.main(["--person", "p2"], read_secret=both) == 1       # no token of theirs yet
    assert gen_token.main([]) == 0
    owner = json.loads(target.read_text(encoding="utf-8"))["auth"]["token"]
    assert gen_token.main(["--person", "p2"]) == 0
    auth = json.loads(target.read_text(encoding="utf-8"))["auth"]
    p2 = auth["people"]["p2"]["token"]
    assert auth["token"] == owner and len(p2) >= 32 and p2 != owner
    capsys.readouterr()
    assert gen_token.main(["--person", "p2"]) == 0                        # already set → no change, not printed
    assert gen_token.main([]) == 0
    out = capsys.readouterr().out
    assert p2 not in out and owner not in out
    assert json.loads(target.read_text(encoding="utf-8"))["auth"]["people"]["p2"]["token"] == p2
    assert set_password.main(["--person", "p2"], read_secret=answers("longenough", "longenough")) == 0
    auth = json.loads(target.read_text(encoding="utf-8"))["auth"]
    assert verify_password("longenough", auth["people"]["p2"]["password_hash"]) and auth["password_hash"] == ""
    assert "longenough" not in capsys.readouterr().out
    cfg = cfgmod.load_config(target)
    assert cfg.auth.token_of("p2") == p2 and cfg.auth.token_of("p1") == owner
    assert gen_token.main(["--person", "p2", "--clear"]) == 0
    auth = json.loads(target.read_text(encoding="utf-8"))["auth"]
    assert auth["people"]["p2"]["token"] == "" and auth["token"] == owner  # only p2 is signed out
