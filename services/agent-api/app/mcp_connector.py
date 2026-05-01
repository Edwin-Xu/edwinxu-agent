from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class McpServerConfig:
    name: str
    transport: str  # "stdio" | "http"
    command: str | None
    args: list[str]
    url: str | None
    env: dict[str, str]
    timeout_ms: int
    enabled: bool


async def list_tools_stdio(cfg: McpServerConfig) -> list[dict[str, Any]]:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    if not cfg.command:
        return []

    env = dict(os.environ)
    env.update(cfg.env or {})

    server_params = StdioServerParameters(command=cfg.command, args=cfg.args or [], env=env)

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            res = await session.list_tools()

            tools: list[dict[str, Any]] = []
            for t in getattr(res, "tools", []) or []:
                tools.append(
                    {
                        "name": getattr(t, "name", ""),
                        "description": getattr(t, "description", "") or "",
                        "input_schema": getattr(t, "inputSchema", None) or getattr(t, "input_schema", None) or {"type": "object"},
                    }
                )
            return tools


async def call_tool_stdio(cfg: McpServerConfig, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    if not cfg.command:
        raise ValueError("stdio mcp server missing command")

    env = dict(os.environ)
    env.update(cfg.env or {})
    server_params = StdioServerParameters(command=cfg.command, args=cfg.args or [], env=env)

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            res = await session.call_tool(tool_name, arguments=arguments)

            structured = getattr(res, "structuredContent", None)
            if structured is not None:
                return {"data": structured, "raw": None}

            content = getattr(res, "content", None) or []
            texts: list[str] = []
            for c in content:
                if getattr(c, "type", None) == "text":
                    texts.append(getattr(c, "text", ""))
                elif isinstance(c, dict) and c.get("type") == "text":
                    texts.append(str(c.get("text") or ""))
            raw_text = "\n".join([t for t in texts if t])

            # Try parse JSON in text
            try:
                parsed = json.loads(raw_text)
                return {"data": parsed, "raw": raw_text}
            except Exception:  # noqa: BLE001
                return {"data": {"text": raw_text}, "raw": raw_text}


async def list_tools(cfg: McpServerConfig) -> list[dict[str, Any]]:
    if cfg.transport == "stdio":
        return await list_tools_stdio(cfg)
    raise NotImplementedError("http transport not implemented yet")


async def call_tool(cfg: McpServerConfig, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if cfg.transport == "stdio":
        return await call_tool_stdio(cfg, tool_name, arguments)
    raise NotImplementedError("http transport not implemented yet")


def list_tools_sync(cfg: McpServerConfig) -> list[dict[str, Any]]:
    return asyncio.run(list_tools(cfg))


def call_tool_sync(cfg: McpServerConfig, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return asyncio.run(call_tool(cfg, tool_name, arguments))

