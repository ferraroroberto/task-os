"""``setup.bat -InPlace`` / ``-MigrateFrom`` carry what ``.fleet.toml [install.migrate]`` names and nothing else:
each file the app keeps per PC is declared, each declared one is ignored by git, and the database stays put."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from src import certs, installer_migrate, password, team
from src.config import load_config
from src.db import DEFAULT_DB_PATH
from src.installer_migrate import Migration, parse_migration, read_fleet_toml
from src.no_window import NO_WINDOW

REPO_ROOT = Path(__file__).resolve().parents[2]


def _declared() -> Migration:
    return parse_migration(read_fleet_toml(REPO_ROOT))


def _covered(path: Path | str, entries: list[str]) -> bool:
    rel = Path(path)
    rel = rel.relative_to(REPO_ROOT) if rel.is_absolute() else rel
    return any(rel == Path(entry) or Path(entry) in rel.parents for entry in entries)


def test_every_per_pc_file_the_app_reads_is_carried_and_none_is_tracked() -> None:
    migration = _declared()
    read_from_the_checkout = [
        "config/config.json", "config/sharepoint-mapping.json", ".env",
        password.DEFAULT_PATH, team.AVATARS_DIR, certs.CERT_FILE, certs.KEY_FILE,
    ]
    assert all(_covered(path, migration.copy) for path in read_from_the_checkout)
    assert all(_covered(secret, migration.copy) for secret in migration.secrets)
    for entry in migration.copy:
        probe = f"{entry}/probe" if not Path(entry).suffix and Path(entry).name != ".env" else entry
        done = subprocess.run(["git", "check-ignore", "-q", probe], cwd=REPO_ROOT, check=False, timeout=60,
                              creationflags=NO_WINDOW)
        assert done.returncode == 0, f"{entry} is not gitignored, so a fresh clone would not stay clean"


def test_the_database_stays_shared_and_verify_asks_the_port_this_pc_serves(tmp_path: Path) -> None:
    migration = _declared()
    assert migration.shared == [DEFAULT_DB_PATH.parent.name]
    assert not [entry for entry in migration.copy if entry.endswith(installer_migrate.DB_SUFFIXES)]
    endpoint = migration.endpoint
    assert endpoint is not None and endpoint.version_path == "/api/version" and endpoint.self_signed
    assert endpoint.port == load_config(REPO_ROOT / "config" / "config.sample.json").port
    (tmp_path / "config").mkdir()
    (tmp_path / endpoint.port_config).write_text(json.dumps({"port": 9123}), encoding="utf-8")
    assert installer_migrate.local_port(tmp_path, endpoint)[0] == 9123
