"""Operator-only admin endpoints (mode switch, scheduler status).

These endpoints are *not* rate-limited or auth-gated at the FastAPI layer
because the dashboard is fronted by Caddy basic-auth in production. Do not
expose this API directly to the public internet.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Literal

import structlog
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

logger = structlog.get_logger().bind(component="admin_route")

router = APIRouter(prefix="/api/admin", tags=["admin"])


# Paths inside the dashboard-api container — mounted from host via compose.
# Both paths intentionally point at the project root mount; the API only
# needs to read/write `.env` and shell out to docker compose.
HOST_PROJECT_DIR = Path(os.environ.get("HOST_PROJECT_DIR", "/host"))
HOST_ENV_FILE = HOST_PROJECT_DIR / ".env"


class ModeStatus(BaseModel):
    """Current trading mode + the mode persisted in the host .env file."""

    runtime_mode: Literal["paper", "live"]
    file_mode: Literal["paper", "live"] | None
    can_switch: bool
    reason: str | None = None


class ModeSwitchRequest(BaseModel):
    """User request to flip trading modes.

    `confirmation` must literally equal the target mode in upper case
    ("PAPER" or "LIVE"). The frontend wraps this with a typed-confirmation
    modal as well; the server-side check is defence in depth.
    """

    target: Literal["paper", "live"]
    confirmation: str = Field(..., min_length=1)

    @field_validator("confirmation")
    @classmethod
    def confirmation_must_match_target(cls, v: str, info):
        target = info.data.get("target")
        if target and v.strip() != target.upper():
            raise ValueError(
                f"confirmation must be the literal string '{target.upper()}'"
            )
        return v


class ModeSwitchResponse(BaseModel):
    previous_mode: str
    new_mode: str
    restarted_services: list[str]
    note: str


def _read_runtime_mode() -> str:
    """Mode this dashboard-api process was started with."""
    return (os.environ.get("TRADING_MODE", "paper").strip().lower() or "paper")


def _read_file_mode() -> str | None:
    """Read TRADING_MODE from the mounted host .env file, if reachable."""
    if not HOST_ENV_FILE.exists():
        return None
    try:
        for line in HOST_ENV_FILE.read_text().splitlines():
            stripped = line.strip()
            if stripped.startswith("TRADING_MODE="):
                return stripped.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        logger.warning("admin.read_env_failed", exc_info=True)
    return None


def _can_switch_mode() -> tuple[bool, str | None]:
    """Decide whether mode switching is wired up in this deployment."""
    if not HOST_ENV_FILE.exists():
        return False, ".env file not mounted into dashboard-api"
    if not os.path.exists("/var/run/docker.sock"):
        return False, "docker socket not mounted into dashboard-api"
    if shutil.which("docker") is None:
        return False, "docker CLI not installed in dashboard-api image"
    return True, None


@router.get("/mode", response_model=ModeStatus)
async def get_mode() -> ModeStatus:
    """Report current runtime mode and persisted file mode.

    The two can disagree briefly during a switch (file changed, restart in
    progress) — the dashboard uses this signal to show a "transitioning"
    state.
    """
    can, reason = _can_switch_mode()
    return ModeStatus(
        runtime_mode=_read_runtime_mode(),
        file_mode=_read_file_mode(),
        can_switch=can,
        reason=reason,
    )


def _update_env_mode(target: str) -> None:
    """Rewrite the TRADING_MODE line in the mounted .env atomically."""
    text = HOST_ENV_FILE.read_text()
    pattern = re.compile(r"^TRADING_MODE=.*$", re.MULTILINE)
    if pattern.search(text):
        new_text = pattern.sub(f"TRADING_MODE={target}", text)
    else:
        # Append if missing entirely
        new_text = text.rstrip() + f"\nTRADING_MODE={target}\n"
    tmp = HOST_ENV_FILE.with_suffix(".tmp")
    tmp.write_text(new_text)
    tmp.replace(HOST_ENV_FILE)


def _recreate_services(services: list[str]) -> None:
    """Trigger `docker compose up -d --force-recreate <services>`."""
    cmd = [
        "docker",
        "compose",
        "-f",
        str(HOST_PROJECT_DIR / "docker-compose.yml"),
        "-f",
        str(HOST_PROJECT_DIR / "docker-compose.prod.yml"),
        "up",
        "-d",
        "--force-recreate",
        *services,
    ]
    logger.info("admin.compose_invoke", cmd=cmd)
    # Detach: docker compose blocks while restarting, but our own container
    # may be in that group — we don't want this HTTP request hung waiting on
    # a container we're not even restarting. Spawn and forget.
    subprocess.Popen(  # noqa: S603 — args fully constructed locally above
        cmd,
        cwd=str(HOST_PROJECT_DIR),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


@router.post("/mode", response_model=ModeSwitchResponse)
async def switch_mode(req: ModeSwitchRequest) -> ModeSwitchResponse:
    """Switch the trading engine between paper and live mode.

    Mechanics:
      1. Validate confirmation matches target (server-side belt + braces).
      2. Rewrite TRADING_MODE in the mounted .env file.
      3. Trigger `docker compose up -d --force-recreate trading ib-gateway`
         in a detached subprocess. The trading + IB Gateway containers
         will come down and back up with the new mode; the dashboard-api
         and dashboard-ui keep serving so the user sees a transitioning
         status rather than a hard 502.
    """
    can, reason = _can_switch_mode()
    if not can:
        raise HTTPException(
            status_code=503,
            detail=f"Mode switching not available: {reason}",
        )

    previous = _read_file_mode() or _read_runtime_mode()
    if previous == req.target:
        raise HTTPException(
            status_code=409,
            detail=f"System is already in {req.target} mode",
        )

    try:
        _update_env_mode(req.target)
    except OSError as exc:
        logger.error("admin.env_update_failed", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to update .env: {exc}",
        ) from exc

    services = ["trading", "ib-gateway"]
    try:
        _recreate_services(services)
    except Exception as exc:
        logger.error("admin.compose_failed", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to invoke docker compose: {exc}",
        ) from exc

    logger.warning(
        "admin.mode_switched",
        previous=previous,
        new=req.target,
    )

    return ModeSwitchResponse(
        previous_mode=previous,
        new_mode=req.target,
        restarted_services=services,
        note=(
            "Trading engine and IB Gateway restarting. The dashboard will "
            "show the new mode within ~60 seconds once the containers come "
            "back up."
        ),
    )
