from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo


def time_now(inp: dict[str, Any]) -> dict[str, Any]:
    tz = inp.get("tz") or "UTC"
    dt = datetime.now(ZoneInfo(tz))
    return {"iso": dt.isoformat()}


def echo_say(inp: dict[str, Any]) -> dict[str, Any]:
    return {"text": str(inp.get("text") or "")}


def builtin_handlers() -> dict[str, callable]:
    return {
        "time.now": time_now,
        "echo.say": echo_say,
    }

