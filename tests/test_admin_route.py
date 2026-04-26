"""Tests for /api/admin/mode endpoints.

The endpoints are gated on the host docker socket + .env file existing
inside the dashboard-api container. We monkey-patch those paths to point
at a tmp dir for the tests.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from trading.dashboard.routes import admin
from trading.dashboard.server import create_app


@pytest.fixture
def fake_host(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Pretend a host project dir is mounted with a writable .env."""
    (tmp_path / ".env").write_text(
        "TRADING_MODE=paper\nOTHER=foo\n", encoding="utf-8"
    )
    monkeypatch.setattr(admin, "HOST_PROJECT_DIR", tmp_path)
    monkeypatch.setattr(admin, "HOST_ENV_FILE", tmp_path / ".env")
    # Pretend docker socket and CLI exist.
    monkeypatch.setattr(os.path, "exists", lambda p: True)
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/docker")
    return tmp_path


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


def test_get_mode_reports_runtime_and_file_modes(
    fake_host: Path, client: TestClient
) -> None:
    with patch.dict(os.environ, {"TRADING_MODE": "paper"}):
        resp = client.get("/api/admin/mode")
    assert resp.status_code == 200
    body = resp.json()
    assert body["runtime_mode"] == "paper"
    assert body["file_mode"] == "paper"
    assert body["can_switch"] is True
    assert body["reason"] is None


def test_switch_mode_rejects_missing_confirmation(
    fake_host: Path, client: TestClient
) -> None:
    resp = client.post(
        "/api/admin/mode",
        json={"target": "live", "confirmation": "live"},  # lowercase fails
    )
    assert resp.status_code == 422


def test_switch_mode_rejects_when_already_in_target(
    fake_host: Path, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # File says paper; switching to paper is a no-op
    resp = client.post(
        "/api/admin/mode",
        json={"target": "paper", "confirmation": "PAPER"},
    )
    assert resp.status_code == 409


def test_switch_mode_writes_env_and_invokes_compose(
    fake_host: Path, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    invoked: list[list[str]] = []

    def fake_popen(cmd, **kwargs):  # noqa: ARG001
        invoked.append(list(cmd))
        return None

    monkeypatch.setattr("subprocess.Popen", fake_popen)

    resp = client.post(
        "/api/admin/mode",
        json={"target": "live", "confirmation": "LIVE"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["previous_mode"] == "paper"
    assert body["new_mode"] == "live"
    assert "trading" in body["restarted_services"]
    assert "ib-gateway" in body["restarted_services"]

    # .env file was rewritten
    env_text = (fake_host / ".env").read_text()
    assert "TRADING_MODE=live" in env_text
    assert "TRADING_MODE=paper" not in env_text
    # Other lines preserved
    assert "OTHER=foo" in env_text

    # docker compose was invoked with force-recreate for the right services
    assert len(invoked) == 1
    cmd = invoked[0]
    assert cmd[0] == "docker"
    assert "compose" in cmd
    assert "--force-recreate" in cmd
    assert "trading" in cmd
    assert "ib-gateway" in cmd


def test_get_mode_reports_disabled_when_socket_missing(
    fake_host: Path,
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Pretend the docker socket doesn't exist
    real_exists = Path.exists

    def fake_exists(self):
        if str(self) == "/var/run/docker.sock":
            return False
        return real_exists(self)

    monkeypatch.setattr("os.path.exists", lambda p: p != "/var/run/docker.sock")

    resp = client.get("/api/admin/mode")
    assert resp.status_code == 200
    body = resp.json()
    assert body["can_switch"] is False
    assert "docker socket" in body["reason"].lower()
