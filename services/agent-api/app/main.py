from __future__ import annotations

import os
import time
import uuid
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from .agent import run_turn
from .builtin_tools import builtin_handlers
from .config import get_settings
import asyncio

from .db import (
    connect,
    create_run,
    create_session,
    delete_session,
    delete_mcp_server,
    get_run,
    get_session,
    list_mcp_servers,
    list_messages,
    list_sessions,
    set_mcp_server_enabled,
    update_run_status,
    upsert_mcp_server,
)
from .events import SessionEventBus, sse_pack
from .models import (
    CreateSessionRequest,
    CreateSessionResponse,
    McpServer,
    RunCreateRequest,
    RunCreateResponse,
    RunResponse,
    SendMessageRequest,
    UpsertMcpServerRequest,
)
from .providers import AnthropicProvider, MockProvider
from .skills_registry import SkillDef, ToolDef, load_builtin_skills
from .mcp_connector import McpServerConfig, call_tool_sync, list_tools_sync


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


# Load .env and also respect exported environment variables (exported wins).
load_dotenv(override=False)
settings = get_settings()
db = connect(settings.db_path)
bus = SessionEventBus()
registry_lock: asyncio.Lock | None = None

repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
skills_root = os.path.join(repo_root, "packages", "skills")
registry = load_builtin_skills(skills_root, builtin_handlers())

app = FastAPI(title="edwinxu-agent-api", version="0.1.0")


def _to_mcp_cfg(d: dict[str, Any]) -> McpServerConfig:
    return McpServerConfig(
        name=str(d.get("name")),
        transport=str(d.get("transport")),
        command=d.get("command"),
        args=list(d.get("args") or []),
        url=d.get("url"),
        env=dict(d.get("env") or {}),
        timeout_ms=int(d.get("timeout_ms") or 30000),
        enabled=bool(d.get("enabled")),
    )


async def refresh_registry() -> None:
    global registry
    global registry_lock
    if registry_lock is None:
        registry_lock = asyncio.Lock()
    async with registry_lock:
        reg = load_builtin_skills(skills_root, builtin_handlers())

        servers = [_to_mcp_cfg(s) for s in list_mcp_servers(db) if s.get("enabled")]
        for s in servers:
            try:
                # Keep startup/refresh responsive even if a server is broken.
                tools = await asyncio.wait_for(
                    asyncio.to_thread(list_tools_sync, s),
                    timeout=min(2.5, max(0.5, s.timeout_ms / 1000.0)),
                )
            except Exception:
                continue
            if not tools:
                continue

            tool_defs: list[ToolDef] = []
            for t in tools:
                upstream_name = str(t.get("name") or "")
                if not upstream_name:
                    continue
                # Namespace MCP tools to avoid collisions:
                # e.g. upstream "stocks.lookup" from server "stocks" => "mcp.stocks.stocks.lookup"
                mapped_name = f"mcp.{s.name}.{upstream_name}"

                async def handler(inp: dict[str, Any], *, _s=s, _upstream=upstream_name) -> dict[str, Any]:
                    res = await asyncio.to_thread(call_tool_sync, _s, _upstream, inp)
                    return res.get("data") or {}

                tool_defs.append(
                    ToolDef(
                        name=mapped_name,
                        description=f"[mcp:{s.name}] {str(t.get('description') or '')}".strip(),
                        input_schema=t.get("input_schema") or {"type": "object"},
                        timeout_ms=int(getattr(s, "timeout_ms", 30000)),
                        handler=handler,
                    )
                )

            reg.register_skill(
                SkillDef(
                    name=s.name,
                    version="0.1.0",
                    description=f"MCP server: {s.name}",
                    tags=["mcp"],
                    tools=tool_defs,
                )
            )

        registry = reg


@app.on_event("startup")
async def _startup() -> None:
    # Don't block server start on external processes (MCP servers).
    # Registry already contains builtin skills; MCP tools will be loaded in background.
    asyncio.create_task(refresh_registry())

if settings.anthropic_api_key or settings.anthropic_auth_token:
    provider = AnthropicProvider(
        model=settings.anthropic_model,
        api_key=settings.anthropic_api_key,
        auth_token=settings.anthropic_auth_token,
        base_url=settings.anthropic_base_url,
        timeout_ms=settings.api_timeout_ms,
    )
else:
    provider = MockProvider()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000", "*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/healthz")
def healthz() -> dict[str, Any]:
    return {"ok": True}


@app.post("/v1/sessions", response_model=CreateSessionResponse)
def api_create_session(req: CreateSessionRequest) -> CreateSessionResponse:
    sid = new_id("s")
    create_session(db, sid, req.title, config={})
    s = get_session(db, sid)
    assert s is not None
    return CreateSessionResponse(id=s["id"], created_at_ms=s["created_at_ms"], title=s["title"])


@app.get("/v1/sessions")
def api_list_sessions(limit: int = 50) -> dict[str, Any]:
    return {"sessions": list_sessions(db, limit=limit)}


@app.get("/v1/sessions/{session_id}")
def api_get_session(session_id: str) -> dict[str, Any]:
    s = get_session(db, session_id)
    if not s:
        raise HTTPException(status_code=404, detail="session not found")
    return s


@app.delete("/v1/sessions/{session_id}")
def api_delete_session(session_id: str) -> dict[str, Any]:
    if not delete_session(db, session_id):
        raise HTTPException(status_code=404, detail="session not found")
    return {"ok": True}


@app.get("/v1/skills")
def api_list_skills() -> dict[str, Any]:
    return {"skills": registry.list_skills(), "tools": registry.list_tools()}


@app.post("/v1/sessions/{session_id}/messages")
async def api_send_message(session_id: str, req: SendMessageRequest) -> dict[str, Any]:
    s = get_session(db, session_id)
    if not s:
        raise HTTPException(status_code=404, detail="session not found")

    trace_id = new_id("t")
    await bus.publish(session_id, {"type": "agent.state", "session_id": session_id, "trace_id": trace_id, "state": "QUEUED"})

    await run_turn(
        db=db,
        bus=bus,
        session_id=session_id,
        trace_id=trace_id,
        provider=provider,
        reg=registry,
        user_text=req.content,
        max_tool_calls=req.policy.max_tool_calls,
        skills=req.skills,
    )

    return {"ok": True, "session_id": session_id, "trace_id": trace_id}

@app.get("/v1/sessions/{session_id}/messages")
def api_list_messages(session_id: str, limit: int = 200) -> dict[str, Any]:
    if not get_session(db, session_id):
        raise HTTPException(status_code=404, detail="session not found")
    return {"messages": list_messages(db, session_id, limit=limit)}


@app.get("/v1/sessions/{session_id}/events")
async def api_events(session_id: str):
    async def gen():
        # initial "hello" event for immediate connection feedback
        yield sse_pack({"type": "session.meta", "session_id": session_id})
        async for event in bus.subscribe(session_id):
            yield sse_pack(event)

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.post("/v1/runs", response_model=RunCreateResponse)
async def api_create_run(req: RunCreateRequest) -> RunCreateResponse:
    session_id = req.session_id
    if session_id is None:
        session_id = new_id("s")
        create_session(db, session_id, title=None, config={})
    else:
        if not get_session(db, session_id):
            raise HTTPException(status_code=404, detail="session not found")

    trace_id = new_id("t")
    run_id = new_id("r")
    create_run(db, run_id, session_id, trace_id)
    update_run_status(db, run_id, "running")

    try:
        await run_turn(
            db=db,
            bus=bus,
            session_id=session_id,
            trace_id=trace_id,
            provider=provider,
            reg=registry,
            user_text=req.content,
            max_tool_calls=req.policy.max_tool_calls,
            skills=req.skills,
        )
        update_run_status(db, run_id, "succeeded", finished_at_ms=int(time.time() * 1000))
    except Exception as e:  # noqa: BLE001
        update_run_status(db, run_id, "failed", finished_at_ms=int(time.time() * 1000), error={"message": str(e)})
        raise

    r = get_run(db, run_id)
    assert r is not None
    return RunCreateResponse(id=run_id, session_id=session_id, trace_id=trace_id, status=r["status"])


@app.get("/v1/runs/{run_id}", response_model=RunResponse)
def api_get_run(run_id: str) -> RunResponse:
    r = get_run(db, run_id)
    if not r:
        raise HTTPException(status_code=404, detail="run not found")
    return RunResponse(**r)


@app.get("/v1/mcp/servers")
def api_list_mcp_servers() -> dict[str, Any]:
    return {"servers": list_mcp_servers(db)}


@app.post("/v1/mcp/servers")
async def api_upsert_mcp_server(req: UpsertMcpServerRequest) -> dict[str, Any]:
    s: McpServer = req.server
    upsert_mcp_server(
        db,
        name=s.name,
        transport=s.transport,
        command=s.command,
        args=s.args,
        url=s.url,
        env=s.env,
        timeout_ms=s.timeout_ms,
        enabled=s.enabled,
    )
    await refresh_registry()
    return {"ok": True}


@app.delete("/v1/mcp/servers/{name}")
async def api_delete_mcp_server(name: str) -> dict[str, Any]:
    if not delete_mcp_server(db, name):
        raise HTTPException(status_code=404, detail="mcp server not found")
    await refresh_registry()
    return {"ok": True}


@app.post("/v1/mcp/servers/{name}:enable")
async def api_enable_mcp_server(name: str) -> dict[str, Any]:
    if not set_mcp_server_enabled(db, name, True):
        raise HTTPException(status_code=404, detail="mcp server not found")
    await refresh_registry()
    return {"ok": True}


@app.post("/v1/mcp/servers/{name}:disable")
async def api_disable_mcp_server(name: str) -> dict[str, Any]:
    if not set_mcp_server_enabled(db, name, False):
        raise HTTPException(status_code=404, detail="mcp server not found")
    await refresh_registry()
    return {"ok": True}

