#!/usr/bin/env python3
"""Devin account usage monitor using Devin-owned local authentication."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

DEFAULT_CREDENTIALS_FILE = (
    Path.home() / ".local" / "share" / "devin" / "credentials.toml"
)
DEFAULT_USAGE_FILE = Path.home() / ".local" / "share" / "devin" / "usage-limits.json"
USER_STATUS_PATH = "/exa.seat_management_pb.SeatManagementService/GetUserStatus"
CACHE_MAX_AGE = 300
DAEMON_INTERVAL = 300


def _iso_now() -> str:
    return datetime.now(UTC).isoformat()


def _parse_iso(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed


def _number(value: object) -> int | float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return value
    if isinstance(value, str):
        try:
            parsed = float(value)
        except ValueError:
            return None
        return int(parsed) if parsed.is_integer() else parsed
    return None


def _format_reset(value: object) -> str:
    seconds = _number(value)
    if seconds is None:
        return ""
    try:
        reset = datetime.fromtimestamp(float(seconds), UTC)
    except (ValueError, OSError):
        return ""
    minutes = max(0, int((reset - datetime.now(UTC)).total_seconds()) // 60)
    if minutes >= 1440:
        return f"{minutes // 1440}d{(minutes % 1440) // 60}h"
    if minutes >= 60:
        return f"{minutes // 60}h{minutes % 60}m"
    return f"{minutes}m"


def get_credentials_file() -> Path:
    override = os.environ.get("DEVIN_USAGE_CREDENTIALS_FILE")
    if override:
        return Path(override).expanduser()
    data_home = os.environ.get("XDG_DATA_HOME")
    return (
        Path(data_home).expanduser() / "devin" / "credentials.toml"
        if data_home
        else DEFAULT_CREDENTIALS_FILE
    )


def get_usage_file() -> Path:
    override = os.environ.get("DEVIN_USAGE_FILE")
    if override:
        return Path(override).expanduser()
    data_home = os.environ.get("XDG_DATA_HOME")
    return (
        Path(data_home).expanduser() / "devin" / "usage-limits.json"
        if data_home
        else DEFAULT_USAGE_FILE
    )


def get_credentials() -> tuple[str, str]:
    """Read the current API key and server without changing Devin credentials."""
    path = get_credentials_file()
    try:
        data = tomllib.loads(path.read_text())
    except FileNotFoundError as exc:
        raise RuntimeError(f"Devin credentials not found at {path}") from exc
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise RuntimeError(f"Could not read Devin credentials from {path}") from exc
    api_key = data.get("windsurf_api_key")
    server = data.get("api_server_url")
    if not isinstance(api_key, str) or not api_key:
        raise RuntimeError("Devin credentials do not contain a local API key")
    if not isinstance(server, str) or not server:
        raise RuntimeError("Devin credentials do not contain an API server")
    parsed = urllib.parse.urlparse(server)
    if parsed.scheme != "https" or not parsed.hostname:
        raise RuntimeError("Devin credential API server is not a valid HTTPS URL")
    return api_key, server.rstrip("/")


def _devin_version() -> str:
    executable = shutil.which("devin")
    if not executable:
        return "unknown"
    try:
        result = subprocess.run(
            [executable, "version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    match = re.search(r"\b(\d+(?:\.\d+)+)\b", result.stdout)
    return match.group(1) if match else "unknown"


def fetch_usage() -> dict:
    api_key, server = get_credentials()
    version = _devin_version()
    payload = {
        "metadata": {
            "apiKey": api_key,
            "ideName": "devin",
            "ideVersion": version,
            "extensionVersion": version,
            "locale": "en",
        }
    }
    request = urllib.request.Request(
        server + USER_STATUS_PATH,
        data=json.dumps(payload, separators=(",", ":")).encode(),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Connect-Protocol-Version": "1",
            "User-Agent": "devin-cli-usage/0.1",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            result = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise RuntimeError(
                "Devin local API key is no longer accepted; sign in with Devin again"
            ) from exc
        raise RuntimeError(f"Devin user-status API returned HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError("Devin user-status API is unavailable") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError("Devin user-status API returned invalid JSON") from exc
    if not isinstance(result, dict):
        raise RuntimeError("Devin user-status API returned an unexpected response")
    return result


def _normalized_plan_info(payload: dict, plan_status: dict) -> dict:
    info = payload.get("planInfo")
    if not isinstance(info, dict):
        info = plan_status.get("planInfo")
    if not isinstance(info, dict):
        info = {}
    return {
        key: value
        for key, source in (
            ("name", "planName"),
            ("billing_strategy", "billingStrategy"),
            ("monthly_prompt_credits", "monthlyPromptCredits"),
            ("monthly_flow_credits", "monthlyFlowCredits"),
            ("monthly_flex_credits", "monthlyFlexCreditPurchaseAmount"),
        )
        if (value := info.get(source)) is not None
    }


def _normalize(payload: dict) -> dict:
    user_status = payload.get("userStatus")
    if not isinstance(user_status, dict):
        raise RuntimeError("Devin user-status response did not contain userStatus")
    plan_status = user_status.get("planStatus")
    if not isinstance(plan_status, dict):
        plan_status = {}
    quotas = {
        "daily": {
            "remaining_pct": _number(plan_status.get("dailyQuotaRemainingPercent")),
            "reset_at": _number(plan_status.get("dailyQuotaResetAtUnix")),
        },
        "weekly": {
            "remaining_pct": _number(plan_status.get("weeklyQuotaRemainingPercent")),
            "reset_at": _number(plan_status.get("weeklyQuotaResetAtUnix")),
        },
    }
    credits = {
        key: value
        for key, source in (
            ("available_prompt", "availablePromptCredits"),
            ("used_prompt", "usedPromptCredits"),
            ("available_flow", "availableFlowCredits"),
            ("used_flow", "usedFlowCredits"),
            ("available_flex", "availableFlexCredits"),
            ("used_flex", "usedFlexCredits"),
            ("overage_balance_micros", "overageBalanceMicros"),
            ("acu_consumed", "acuConsumed"),
            ("acu_limit", "acuLimit"),
        )
        if (value := _number(plan_status.get(source))) is not None
    }
    return {
        "plan": _normalized_plan_info(payload, plan_status),
        "plan_period": {
            "start": plan_status.get("planStart"),
            "end": plan_status.get("planEnd"),
        },
        "quotas": quotas,
        "credits": credits,
    }


def build_usage_json() -> dict:
    updated_at = _iso_now()
    try:
        usage = _normalize(fetch_usage())
    except Exception as exc:
        return {
            "provider": "devin",
            "status": "unavailable",
            "source": "devin_user_status_api",
            "retrieved_at": updated_at,
            "error": str(exc),
        }
    return {
        "provider": "devin",
        "status": "live",
        "source": "devin_user_status_api",
        "retrieved_at": updated_at,
        **usage,
    }


def write_usage_file(data: dict) -> None:
    path = get_usage_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(data, handle, indent=2)
            handle.write("\n")
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _read_cache() -> dict | None:
    try:
        data = json.loads(get_usage_file().read_text())
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def get_cached_usage(max_age: int = CACHE_MAX_AGE, force_refresh: bool = False) -> dict:
    cached = _read_cache()
    if not force_refresh and cached:
        retrieved = _parse_iso(cached.get("retrieved_at"))
        if retrieved and (datetime.now(UTC) - retrieved).total_seconds() < max_age:
            return {**cached, "status": "cached"}
    fresh = build_usage_json()
    if fresh["status"] == "live":
        write_usage_file(fresh)
        return fresh
    if cached:
        return {**cached, "status": "stale", "refresh_error": fresh.get("error")}
    return fresh


def _quota_value(data: dict) -> tuple[str, dict] | None:
    quotas = data.get("quotas")
    if not isinstance(quotas, dict):
        return None
    candidates = [
        (name, quota)
        for name, quota in quotas.items()
        if isinstance(quota, dict) and quota.get("remaining_pct") is not None
    ]
    return (
        min(candidates, key=lambda item: float(item[1]["remaining_pct"]))
        if candidates
        else None
    )


def _statusline_text(data: dict) -> str:
    selected = _quota_value(data)
    if not selected:
        return "devin:q:unavailable"
    name, quota = selected
    remaining = float(quota["remaining_pct"])
    parts = [f"devin:{name}:{remaining:g}%left"]
    reset = _format_reset(quota.get("reset_at"))
    if reset:
        parts.append(f"reset:{reset}")
    if data.get("status") in {"cached", "stale"}:
        parts.append(str(data["status"]))
    return " ".join(parts)


def _print_status(data: dict) -> None:
    print("Devin usage")
    print(f"Status: {data['status']}")
    plan = data.get("plan")
    if isinstance(plan, dict) and plan.get("name"):
        print(f"Plan: {plan['name']}")
    quotas = data.get("quotas")
    if isinstance(quotas, dict):
        for name in ("daily", "weekly"):
            quota = quotas.get(name)
            if isinstance(quota, dict) and quota.get("remaining_pct") is not None:
                suffix = _format_reset(quota.get("reset_at"))
                reset = f", resets in {suffix}" if suffix else ""
                print(
                    f"{name.title()}: {float(quota['remaining_pct']):g}% remaining{reset}"
                )
    credits = data.get("credits")
    if isinstance(credits, dict):
        if credits.get("available_prompt") is not None:
            print(f"Prompt credits available: {credits['available_prompt']}")
        if credits.get("available_flow") is not None:
            print(f"Flow credits available: {credits['available_flow']}")
        if credits.get("available_flex") is not None:
            print(f"Flex credits available: {credits['available_flex']}")
    if data.get("error"):
        print(f"Error: {data['error']}")
    if data.get("refresh_error"):
        print(f"Refresh error: {data['refresh_error']}")


def cmd_status(_args: argparse.Namespace) -> None:
    _print_status(build_usage_json())


def cmd_json(_args: argparse.Namespace) -> None:
    print(json.dumps(build_usage_json(), indent=2))


def cmd_statusline(args: argparse.Namespace) -> None:
    print(_statusline_text(get_cached_usage(args.max_age, args.refresh)))


def cmd_refresh(_args: argparse.Namespace) -> None:
    data = build_usage_json()
    if data["status"] == "live":
        write_usage_file(data)
    _print_status(data)


def cmd_daemon(args: argparse.Namespace) -> None:
    signal.signal(signal.SIGINT, lambda *_: sys.exit(0))
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    print(f"devin-cli-usage daemon started (refreshing every {args.interval}s)")
    print(f"Writing to {get_usage_file()}")
    while True:
        data = build_usage_json()
        if data["status"] == "live":
            write_usage_file(data)
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {_statusline_text(data)}")
        time.sleep(args.interval)


def cmd_install(_args: argparse.Namespace) -> None:
    print(
        "Install with:\n  uv tool install devin-cli-usage\n\nThen run:\n  devin-cli-usage"
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Devin account usage monitor")
    parser.add_argument(
        "command",
        nargs="?",
        default="status",
        choices=["status", "json", "daemon", "statusline", "refresh", "install"],
    )
    parser.add_argument("-i", "--interval", type=int, default=DAEMON_INTERVAL)
    parser.add_argument("--max-age", type=int, default=CACHE_MAX_AGE)
    parser.add_argument("--refresh", action="store_true")
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    commands = {
        "status": cmd_status,
        "json": cmd_json,
        "daemon": cmd_daemon,
        "statusline": cmd_statusline,
        "refresh": cmd_refresh,
        "install": cmd_install,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()
