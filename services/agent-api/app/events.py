from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from typing import Any, AsyncIterator


def now_ms() -> int:
    return int(time.time() * 1000)


def sse_pack(event: dict[str, Any]) -> bytes:
    # SSE: each message is one "data:" line + blank line
    payload = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
    return f"data: {payload}\n\n".encode("utf-8")


@dataclass
class SessionEventBus:
    queues: dict[str, "asyncio.Queue[dict[str, Any]]"]

    def __init__(self) -> None:
        self.queues = {}

    def get_queue(self, session_id: str) -> "asyncio.Queue[dict[str, Any]]":
        q = self.queues.get(session_id)
        if q is None:
            q = asyncio.Queue()
            self.queues[session_id] = q
        return q

    async def publish(self, session_id: str, event: dict[str, Any]) -> None:
        q = self.get_queue(session_id)
        await q.put(event)

    async def subscribe(self, session_id: str) -> AsyncIterator[dict[str, Any]]:
        q = self.get_queue(session_id)
        while True:
            event = await q.get()
            yield event

