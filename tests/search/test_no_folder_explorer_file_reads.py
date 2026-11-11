"""task-os opens no folder-explorer database file; it asks folder-explorer's v1 API.

The flagged-mail poller used to open folder-explorer's email index read-only, which
tied task-os to that service's on-disk schema. This scan keeps `src/` honest: a
read of that file, or a setting naming it, comes back as a failing test.
"""

from __future__ import annotations

import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src"
#: `email_db` stays in `config.py` only as the retired key an old config may still carry.
RETIRED_KEY_HOME = SRC / "config.py"
FILE_READS = re.compile(r"emails\.(?:db|sqlite3)|connect_read_only|read_only_uri|open_readonly|is_archiver_index")
SETTING = re.compile(r"\bemail_db\b")


def _sources() -> list[Path]:
    return [p for p in SRC.rglob("*.py") if "__pycache__" not in p.parts]


def test_email_capture_reads_no_database_file() -> None:
    text = (SRC / "email_capture.py").read_text(encoding="utf-8")
    assert FILE_READS.findall(text) == []
    assert "import sqlite3" in text  # only for the tasks database's own errors
    assert "FolderExplorerClient" in text


def test_no_source_names_folder_explorers_email_files() -> None:
    hits = [f"{p.relative_to(SRC)}: {m}" for p in _sources()
            for m in set(re.findall(r"emails\.(?:db|sqlite3)", p.read_text(encoding="utf-8")))]
    assert hits == []


def test_the_email_db_setting_is_gone_but_for_the_retired_key() -> None:
    hits = [str(p.relative_to(SRC)) for p in _sources()
            if p != RETIRED_KEY_HOME and SETTING.search(p.read_text(encoding="utf-8"))]
    assert hits == []
