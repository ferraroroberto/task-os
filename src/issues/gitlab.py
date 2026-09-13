"""GitLab issue provider — ``glab api``, JSON in and out (Step 11).

The second :class:`~src.issues.base.IssueProvider`, the same shape as
``github.py``: ``glab`` is a subprocess per call (``CREATE_NO_WINDOW``, 20 s
timeout, UTF-8), never a library dependency, never invoked on a poll — only
by the sync job and on explicit user demand (↻, create). Everything goes
through ``glab api`` against the REST v4 endpoints, so one JSON parser covers
list, read and create, and the create answers with the full issue (no
read-back call).

    list_open_assigned  glab api --hostname <host> --paginate groups/<group>/issues?state=opened&scope=assigned_to_me…
    get                 glab api --hostname <host> projects/<path>/issues/<iid>
    create              glab api --hostname <host> user                         (the assignee's id; cached)
                        glab api --hostname <host> -X POST -f title=… -f description=… -F assignee_id=<id> projects/<path>/issues

Config mapping (``config.json → issues``): ``owner`` is the **group path**
(``my-group`` or ``my-group/sub-group`` — a group's issue list includes its
sub-groups' projects), ``assignee`` is ``@me`` or a GitLab username, ``host``
is the GitLab hostname (blank = ``gitlab.com``). ``--hostname`` is always
passed: without it ``glab`` picks the host from the *current directory's* git
remote, which for a process started inside this repo is not the forge.

GitLab vocabulary is normalised into :class:`IssueInfo`: ``iid`` → ``number``
(the per-project number the UI shows, not the global ``id``), ``opened`` →
``open``, ``web_url`` → ``url``, ``description`` → ``body``, and ``repo`` is
the project's full path (``references.full`` minus ``#iid``, else parsed from
``web_url``) — nested groups make it more than two segments, which
``short_repo`` already handles.

Failures are classified the way ``github.py`` classifies ``gh``'s:
``glab`` missing → ``not_installed`` (``is_configured`` reports it first),
``TimeoutExpired`` → ``timeout``, and from ``glab``'s stderr: a 401 / auth hint →
``not_authenticated``, a 429 / rate-limit line → ``rate_limited``, a 404 →
``not_found``; anything else → ``error`` with the first stderr line.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
from collections.abc import Sequence
from typing import Any
from urllib.parse import quote, urlencode

from src.issues.base import IssueInfo, IssueProviderError
from src.no_window import NO_WINDOW

logger = logging.getLogger(__name__)

GLAB_TIMEOUT_S = 20.0
DEFAULT_HOST = "gitlab.com"
PER_PAGE = 100
_WEB_URL_RE = re.compile(r"^https?://[^/\s]+/(.+?)/-/issues/(\d+)")
_REF_SUFFIX_RE = re.compile(r"#\d+$")

_AUTH_HINTS = ("glab auth login", "401", "unauthorized", "not authenticated", "no token", "invalid token")
_RATE_HINTS = ("429", "too many requests", "rate limit")
_NOT_FOUND_HINTS = ("404", "not found")


def _classify(stderr: str) -> str:
    text = (stderr or "").lower()
    if any(h in text for h in _AUTH_HINTS):
        return "not_authenticated"
    if any(h in text for h in _RATE_HINTS):
        return "rate_limited"
    if any(h in text for h in _NOT_FOUND_HINTS):
        return "not_found"
    return "error"


def run_glab(args: Sequence[str], *, timeout: float = GLAB_TIMEOUT_S, label: str = "glab") -> str:
    """Run ``glab <args>`` and return stdout; :class:`IssueProviderError` on any failure."""
    try:
        proc = subprocess.run(
            ["glab", *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            creationflags=NO_WINDOW,
        )
    except FileNotFoundError as exc:
        raise IssueProviderError("glab not on PATH — install the GitLab CLI", code="not_installed") from exc
    except subprocess.TimeoutExpired as exc:
        raise IssueProviderError(f"{label}: timed out after {timeout:.0f}s", code="timeout") from exc
    except (OSError, subprocess.SubprocessError) as exc:
        raise IssueProviderError(f"{label}: {exc}", code="error") from exc
    if proc.returncode != 0:
        lines = (proc.stderr or proc.stdout or "").strip().splitlines()
        first = lines[0].strip() if lines else "no output"
        code = _classify(proc.stderr or proc.stdout or "")
        raise IssueProviderError(f"{label} exited {proc.returncode}: {first}", code=code)
    return proc.stdout


def _json_values(out: str) -> list[Any]:
    """Every JSON value in ``out``. ``glab api --paginate`` prints one document
    per page back to back (``[…][…]``), so a plain ``json.loads`` is not enough."""
    decoder = json.JSONDecoder()
    text, pos, values = out or "", 0, []
    while True:
        while pos < len(text) and text[pos].isspace():
            pos += 1
        if pos >= len(text):
            return values
        try:
            value, pos = decoder.raw_decode(text, pos)
        except ValueError as exc:
            raise IssueProviderError(f"glab returned unparseable JSON: {exc}", code="error") from exc
        values.append(value)


def _one(out: str, what: str) -> dict[str, Any]:
    values = _json_values(out)
    if len(values) != 1 or not isinstance(values[0], dict):
        raise IssueProviderError(f"glab api {what}: expected one JSON object", code="error")
    return values[0]


def _labels(row: dict[str, Any]) -> tuple[str, ...]:
    out: list[str] = []
    for lab in row.get("labels") or []:
        name = lab.get("name") if isinstance(lab, dict) else lab   # ``with_labels_details`` shape, or plain names
        if name:
            out.append(str(name))
    return tuple(out)


class GitLabProvider:
    """``glab api``-backed :class:`~src.issues.base.IssueProvider`."""

    name = "gitlab"

    def __init__(self, group: str, assignee: str = "@me", host: str = "", *, timeout: float = GLAB_TIMEOUT_S) -> None:
        self.group = (group or "").strip().strip("/")
        self.assignee = (assignee or "@me").strip() or "@me"
        self.host = (host or "").strip().rstrip("/") or DEFAULT_HOST
        self.timeout = timeout
        self._assignee_id: int | None = None

    # ------------------------------------------------------------ helpers
    def _api(self, endpoint: str, *flags: str) -> str:
        """``glab api --hostname <host> [flags…] <endpoint>`` — the endpoint names the call in errors."""
        return run_glab(["api", "--hostname", self.host, *flags, endpoint], timeout=self.timeout,
                        label=f"glab api {endpoint.split('?', 1)[0]}")

    @staticmethod
    def _project(repo: str) -> str:
        return "projects/" + quote(repo.strip().strip("/"), safe="")

    def _info(self, row: dict[str, Any], repo: str | None = None) -> IssueInfo:
        full = repo or ""
        if not full:
            ref = str((row.get("references") or {}).get("full") or "")
            full = _REF_SUFFIX_RE.sub("", ref)
        if not full:
            m = _WEB_URL_RE.search(str(row.get("web_url") or ""))
            full = m.group(1) if m else ""
        state = str(row.get("state") or "opened").lower()
        return IssueInfo(
            provider=self.name,
            repo=full,
            number=int(row.get("iid") or 0),
            title=str(row.get("title") or "").strip(),
            url=str(row.get("web_url") or ""),
            state="open" if state == "opened" else state,
            labels=_labels(row),
            updated_at=row.get("updated_at"),
            body=row.get("description"),
        )

    def _resolve_assignee_id(self) -> int:
        """The numeric user id ``POST …/issues`` needs — ``@me`` is ``GET user``."""
        if self._assignee_id is None:
            if self.assignee == "@me":
                user = _one(self._api("user"), "user")
            else:
                users = _json_values(self._api("users?" + urlencode({"username": self.assignee})))
                found = [u for page in users for u in (page if isinstance(page, list) else [page]) if isinstance(u, dict)]
                if not found:
                    raise IssueProviderError(f"GitLab user {self.assignee!r} not found on {self.host}", code="not_found")
                user = found[0]
            if not user.get("id"):
                raise IssueProviderError(f"glab api user: no id for {self.assignee!r} on {self.host}", code="error")
            self._assignee_id = int(user["id"])
        return self._assignee_id

    # ----------------------------------------------------------- contract
    def is_configured(self) -> tuple[bool, str | None]:
        if not self.group:
            return False, "issues.owner (the GitLab group) is not set in config"
        if shutil.which("glab") is None:
            return False, "glab not on PATH — install the GitLab CLI"
        return True, None

    def list_open_assigned(self) -> list[IssueInfo]:
        query: dict[str, str | int] = {"state": "opened", "order_by": "updated_at", "per_page": PER_PAGE}
        if self.assignee == "@me":
            query["scope"] = "assigned_to_me"
        else:
            query.update(scope="all", assignee_username=self.assignee)
        endpoint = "groups/" + quote(self.group, safe="") + "/issues?" + urlencode(query)
        pages = _json_values(self._api(endpoint, "--paginate"))
        if not all(isinstance(p, list) for p in pages):
            raise IssueProviderError("glab api group issues: expected JSON lists", code="error")
        issues = [self._info(r) for page in pages for r in page if isinstance(r, dict)]
        return [i for i in issues if i.repo and i.number]

    def get(self, repo: str, number: int) -> IssueInfo:
        row = _one(self._api(f"{self._project(repo)}/issues/{int(number)}"), f"{repo}#{number}")
        return self._info(row, repo=repo)

    def create(self, repo: str, title: str, body: str) -> IssueInfo:
        assignee_id = self._resolve_assignee_id()
        row = _one(self._api(
            f"{self._project(repo)}/issues",
            "-X", "POST",
            "-f", f"title={title}",
            "-f", f"description={body or ''}",
            "-F", f"assignee_id={assignee_id}",
        ), f"create {repo}")
        info = self._info(row, repo=repo)
        if not info.number:
            raise IssueProviderError(f"glab api create {repo}: no iid in the response", code="error")
        return info


__all__ = ["DEFAULT_HOST", "GLAB_TIMEOUT_S", "GitLabProvider", "run_glab"]
