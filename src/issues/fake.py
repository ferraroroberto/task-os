"""A file-backed fake provider — the test double for the sync and the e2e story.

``TASKOS_ISSUE_PROVIDER=fake`` (+ ``TASKOS_ISSUE_FAKE_PATH=<file.json>``)
makes a disposable instance read its "forge" from a JSON file the test edits
between syncs — close an issue, rename one, add one — with no network and
no ``gh``. Also usable in-process for the unit tests (``FakeProvider(path)``
or ``FakeProvider.from_issues([...])``).

File shape::

    {"issues": [{"repo": "example/garden-bot", "number": 12, "title": "…",
                 "state": "open", "url": "…", "labels": ["bug"],
                 "updated_at": "2026-08-17T10:00:00Z", "body": "…",
                 "assigned": true}],
     "error": null}                      # or {"code": "timeout", "message": "…"}

``error`` set → every call raises that :class:`IssueProviderError` (how the
tests exercise the "provider down" states). ``assigned: false`` keeps an
issue out of ``list_open_assigned`` while ``get`` still finds it (the
"missing from the list but still open" case). ``create`` appends to the file.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from src.issues.base import IssueInfo, IssueProviderError

_lock = threading.Lock()


class FakeProvider:
    # It fakes *GitHub*: ``issue_refs.provider`` is constrained to the real
    # provider names, and the UI keys its glyph on it.
    name = "github"

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    @classmethod
    def from_issues(cls, path: Path | str, issues: list[dict[str, Any]], error: dict[str, str] | None = None) -> FakeProvider:
        p = Path(path)
        p.write_text(json.dumps({"issues": issues, "error": error}, indent=1), encoding="utf-8")
        return cls(p)

    # ------------------------------------------------------------- file io
    def _read(self) -> dict[str, Any]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise IssueProviderError(f"fake provider file missing: {self.path}", code="not_installed") from exc
        except ValueError as exc:
            raise IssueProviderError(f"fake provider file unparseable: {exc}", code="error") from exc
        err = data.get("error")
        if err:
            raise IssueProviderError(str(err.get("message") or "fake provider error"), code=str(err.get("code") or "error"))
        return data

    def _write(self, data: dict[str, Any]) -> None:
        self.path.write_text(json.dumps(data, indent=1), encoding="utf-8")

    def _info(self, row: dict[str, Any]) -> IssueInfo:
        return IssueInfo(
            provider=self.name,
            repo=str(row["repo"]),
            number=int(row["number"]),
            title=str(row.get("title") or ""),
            url=str(row.get("url") or f"https://github.com/{row['repo']}/issues/{row['number']}"),
            state=str(row.get("state") or "open").lower(),
            labels=tuple(str(x) for x in row.get("labels") or []),
            updated_at=row.get("updated_at"),
            body=row.get("body"),
        )

    # ------------------------------------------------------------ contract
    def is_configured(self) -> tuple[bool, str | None]:
        if not self.path.exists():
            return False, f"fake provider file missing: {self.path}"
        return True, None

    def list_open_assigned(self) -> list[IssueInfo]:
        with _lock:
            rows = self._read().get("issues") or []
        return [self._info(r) for r in rows if str(r.get("state", "open")).lower() == "open" and r.get("assigned", True)]

    def get(self, repo: str, number: int) -> IssueInfo:
        with _lock:
            rows = self._read().get("issues") or []
        for r in rows:
            if str(r.get("repo")) == repo and int(r.get("number", 0)) == int(number):
                return self._info(r)
        raise IssueProviderError(f"{repo}#{number} not found", code="not_found")

    def create(self, repo: str, title: str, body: str) -> IssueInfo:
        with _lock:
            data = self._read()
            rows = data.setdefault("issues", [])
            number = max([int(r.get("number", 0)) for r in rows if r.get("repo") == repo] or [0]) + 1
            row = {
                "repo": repo, "number": number, "title": title, "state": "open",
                "url": f"https://github.com/{repo}/issues/{number}", "labels": [], "body": body,
                "updated_at": None, "assigned": True,
            }
            rows.append(row)
            self._write(data)
        return self._info(row)


__all__ = ["FakeProvider"]
