"""``src/certs.py`` — the two uvicorn spawn shapes make one HTTPS decision.

``launcher.py webapp`` runs uvicorn in-process (keyword arguments) and the
tray's ``WebappManager`` spawns it as a subprocess (CLI flags); CLAUDE.md
requires the two to agree. Hermetic: ``cert_paths`` is stubbed, no real pair.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from src import certs


def test_both_shapes_carry_the_same_pair(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    cert, key = tmp_path / "cert.pem", tmp_path / "key.pem"
    monkeypatch.setattr(certs, "cert_paths", lambda: (cert, key))
    assert certs.uvicorn_ssl_kwargs() == {"ssl_certfile": str(cert), "ssl_keyfile": str(key)}
    assert certs.uvicorn_ssl_args() == ["--ssl-keyfile", str(key), "--ssl-certfile", str(cert)]


def test_no_pair_is_plain_http_said_out_loud_by_both(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(certs, "cert_paths", lambda: None)
    with caplog.at_level(logging.WARNING, logger="src.certs"):
        assert certs.uvicorn_ssl_kwargs() == {}
        assert certs.uvicorn_ssl_args() == []
    assert [r.getMessage().count("serving PLAIN HTTP") for r in caplog.records] == [1, 1]
