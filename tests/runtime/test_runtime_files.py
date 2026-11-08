"""The guarded writer: code folders are refused, everything else is written."""

from __future__ import annotations

import sqlite3
import tomllib
from pathlib import Path

import pytest

from src import db
from src.runtime import files as runtime_files


def test_code_folders_match_the_ratchets_config() -> None:
    """The guard and the runtime-write ratchet name the same folders."""
    table = tomllib.loads((runtime_files.REPO_ROOT / ".fleet.toml").read_text(encoding="utf-8"))
    declared = table["runtime_write_ratchet"].get("code_folders", list(runtime_files.CODE_FOLDERS))
    assert tuple(declared) == runtime_files.CODE_FOLDERS


@pytest.mark.parametrize("folder", runtime_files.CODE_FOLDERS)
def test_every_writer_refuses_a_code_folder(folder: str) -> None:
    target = runtime_files.REPO_ROOT / folder / "never-written.txt"
    with pytest.raises(runtime_files.CodeFolderWrite):
        runtime_files.save_text(target, "x")
    with pytest.raises(runtime_files.CodeFolderWrite):
        runtime_files.make_dir(target.parent / "sub")
    with pytest.raises(runtime_files.CodeFolderWrite):
        runtime_files.open_append(target)
    with pytest.raises(runtime_files.CodeFolderWrite):
        runtime_files.rotating_file_handler(target, max_bytes=10, backups=1)
    with pytest.raises(runtime_files.CodeFolderWrite):
        runtime_files.copy_file(__file__, target)
    with pytest.raises(runtime_files.CodeFolderWrite):
        db.connect(target)
    assert not target.exists()


def test_a_dotdot_path_into_a_code_folder_is_still_refused(tmp_path: Path) -> None:
    sneaky = runtime_files.REPO_ROOT / "data" / ".." / "src" / "never-written.txt"
    with pytest.raises(runtime_files.CodeFolderWrite):
        runtime_files.save_text(sneaky, "x")


def test_gitignored_live_state_inside_the_checkout_is_allowed() -> None:
    for folder in ("data", "config", "webapp"):
        target = runtime_files.REPO_ROOT / folder / "x.txt"
        assert runtime_files.checked(target) == target


def test_writers_write_outside_the_code_folders(tmp_path: Path) -> None:
    out = runtime_files.make_dir(tmp_path / "a" / "b")
    note = runtime_files.save_text(out / "note.txt", "line\n", newline="\n")
    assert note.read_bytes() == b"line\n"
    log = runtime_files.open_append(out / "log.txt")
    log.write("one\n")  # type: ignore[arg-type]
    log.close()
    raw = runtime_files.open_append(out / "raw.bin", binary=True)
    raw.write(b"\x00")  # type: ignore[arg-type]
    raw.close()
    copied = runtime_files.copy_file(note, out / "copy.txt")
    assert copied.read_text(encoding="utf-8") == "line\n"
    handler = runtime_files.rotating_file_handler(out / "rot.log", max_bytes=100, backups=1)
    handler.close()
    assert (out / "rot.log").exists()


def test_connect_read_only_cannot_write(tmp_path: Path) -> None:
    path = tmp_path / "x.db"
    conn = db.connect(path)
    conn.execute("CREATE TABLE t (a)")
    conn.commit()
    conn.close()
    ro = db.connect_read_only(path)
    with pytest.raises(sqlite3.OperationalError):
        ro.execute("INSERT INTO t VALUES (1)")
    ro.close()


def test_plain_connect_skips_the_fleet_pragmas(tmp_path: Path) -> None:
    conn = db.connect(tmp_path / "plain.db", pragmas=False)
    assert conn.row_factory is None
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
    conn.close()
