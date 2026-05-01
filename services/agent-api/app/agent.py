from __future__ import annotations

import asyncio
import inspect
import time
import uuid
from typing import Any

from .db import Db, add_message, add_tool_call, list_messages
from .events import SessionEventBus
from .models import SkillsConfig
from .providers import ModelProvider
from .skills_registry import SkillRegistry, tool_result


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def to_model_messages(history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Convert stored messages to model messages.
    We keep user/assistant text blocks; tool messages are not replayed (tool results will be appended at runtime).
    """
    out: list[dict[str, Any]] = []
    for m in history:
        role = m["role"]
        if role not in ("user", "assistant"):
            continue

        content = m["content"]
        if isinstance(content, dict) and "text" in content:
            text = content["text"]
        elif isinstance(content, str):
            text = content
        else:
            text = str(content)

        out.append({"role": role, "content": [{"type": "text", "text": text}]})
    return out


def tools_for_model(reg: SkillRegistry) -> list[dict[str, Any]]:
    tools: list[dict[str, Any]] = []
    for t in reg.list_tools():
        tools.append(
            {
                "name": t["name"],
                "description": t["description"],
                "input_schema": t["input_schema"],
            }
        )
    return tools


def _tool_to_skill_name(tool_name: str) -> str:
    # convention: "<skill>.<tool>"
    # MCP convention: "mcp.<server>.<tool...>" => skill is <server>
    if tool_name.startswith("mcp."):
        parts = tool_name.split(".")
        if len(parts) >= 2:
            return parts[1]
    if "." in tool_name:
        return tool_name.split(".", 1)[0]
    return tool_name


def _is_tool_allowed(tool_name: str, skills: SkillsConfig) -> bool:
    if skills.mode == "auto":
        return True
    deny = set(skills.deny or [])
    allow = set(skills.allow or [])
    skill = _tool_to_skill_name(tool_name)
    if skill in deny:
        return False
    # allowlist empty => allow all (backwards compatible)
    if not allow:
        return True
    return skill in allow


async def run_turn(
    *,
    db: Db,
    bus: SessionEventBus,
    session_id: str,
    trace_id: str,
    provider: ModelProvider,
    reg: SkillRegistry,
    user_text: str,
    max_tool_calls: int,
    skills: SkillsConfig,
) -> str:
    # Persist user message
    user_mid = new_id("m")
    add_message(db, user_mid, session_id, "user", {"text": user_text}, trace_id)
    await bus.publish(session_id, {"type": "agent.state", "session_id": session_id, "trace_id": trace_id, "state": "RECEIVING"})

    system = "You are a helpful agent. Use tools when beneficial. Keep responses concise."

    tool_calls = 0
    assistant_text_acc = ""
    model_messages = to_model_messages(list_messages(db, session_id))

    while True:
        await bus.publish(session_id, {"type": "agent.state", "session_id": session_id, "trace_id": trace_id, "state": "CALLING_MODEL"})
        tools = [t for t in tools_for_model(reg) if _is_tool_allowed(t["name"], skills)]

        resp = await provider.respond(system=system, messages=model_messages, tools=tools, max_tokens=800)
        blocks = resp.get("content", [])

        text_blocks: list[dict[str, Any]] = []
        for b in blocks:
            if b.get("type") == "text" and b.get("text"):
                text_blocks.append({"type": "text", "text": b["text"]})
                assistant_text_acc += b["text"]
                await bus.publish(session_id, {"type": "assistant.delta", "session_id": session_id, "trace_id": trace_id, "delta": b["text"]})

        tool_uses = [b for b in blocks if b.get("type") == "tool_use"]
        if not tool_uses:
            # finalize assistant message
            amid = new_id("m")
            add_message(db, amid, session_id, "assistant", {"text": assistant_text_acc}, trace_id)
            await bus.publish(
                session_id,
                {
                    "type": "assistant.message",
                    "session_id": session_id,
                    "trace_id": trace_id,
                    "message": {"id": amid, "role": "assistant", "content": assistant_text_acc},
                },
            )
            await bus.publish(session_id, {"type": "agent.state", "session_id": session_id, "trace_id": trace_id, "state": "DONE"})
            return assistant_text_acc

        # Append assistant blocks (text + tool_use) into model messages
        assistant_blocks = [*text_blocks, *tool_uses]
        model_messages.append({"role": "assistant", "content": assistant_blocks})

        for tu in tool_uses:
            if tool_calls >= max_tool_calls:
                # stop condition
                assistant_text_acc += "\n\n（已达到最大工具调用次数限制）"
                continue

            tool_calls += 1
            tool_use_id = tu.get("id") or new_id("toolu")
            tool_name = tu.get("name") or ""
            tool_input = tu.get("input") or {}

            await bus.publish(
                session_id,
                {"type": "tool.call", "session_id": session_id, "trace_id": trace_id, "tool_name": tool_name, "input": tool_input},
            )

            if not _is_tool_allowed(tool_name, skills):
                started = int(time.time() * 1000)
                result = tool_result(
                    status="error",
                    summary=f"Tool not allowed by skills policy: {tool_name}",
                    next_actions=["Adjust skills allowlist/denylist and retry."],
                    data={},
                    duration_ms=0,
                )
                finished = int(time.time() * 1000)
                tool_call_id = new_id("tc")
                add_tool_call(
                    db,
                    tool_call_id,
                    session_id,
                    trace_id,
                    tool_name,
                    tool_input,
                    result,
                    started,
                    finished,
                    result.get("status", "error"),
                )
                add_message(
                    db,
                    new_id("m"),
                    session_id,
                    "tool",
                    {"tool_name": tool_name, "input": tool_input, "result": result},
                    trace_id,
                )
                await bus.publish(
                    session_id,
                    {
                        "type": "tool.result",
                        "session_id": session_id,
                        "trace_id": trace_id,
                        "tool_name": tool_name,
                        "result": result,
                    },
                )
                model_messages.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": tool_use_id,
                                "content": [{"type": "text", "text": result.get("summary", "")}],
                            }
                        ],
                    }
                )
                continue

            tool_def = reg.get_tool(tool_name)
            started = int(time.time() * 1000)
            if tool_def is None:
                result = tool_result(
                    status="error",
                    summary=f"Unknown tool: {tool_name}",
                    next_actions=["Use only available tools."],
                    data={},
                    duration_ms=0,
                )
            else:
                try:
                    async def _invoke():
                        out = tool_def.handler(tool_input)
                        if inspect.isawaitable(out):
                            return await out
                        return out

                    data = await asyncio.wait_for(_invoke(), timeout=tool_def.timeout_ms / 1000.0)
                    result = tool_result(
                        status="success",
                        summary="Tool executed",
                        data=data,
                        duration_ms=int(time.time() * 1000) - started,
                    )
                except Exception as e:  # noqa: BLE001
                    result = tool_result(
                        status="error",
                        summary="Tool failed",
                        next_actions=["Check input schema and retry with valid arguments."],
                        data={"error": str(e)},
                        duration_ms=int(time.time() * 1000) - started,
                    )

            finished = int(time.time() * 1000)
            tool_call_id = new_id("tc")
            add_tool_call(
                db,
                tool_call_id,
                session_id,
                trace_id,
                tool_name,
                tool_input,
                result,
                started,
                finished,
                result.get("status", "error"),
            )

            # Store as tool message (kept for audit; not yet sent to model in MVP)
            add_message(
                db,
                new_id("m"),
                session_id,
                "tool",
                {"tool_name": tool_name, "input": tool_input, "result": result},
                trace_id,
            )

            await bus.publish(
                session_id,
                {
                    "type": "tool.result",
                    "session_id": session_id,
                    "trace_id": trace_id,
                    "tool_name": tool_name,
                    "result": result,
                },
            )

            # Append tool_result back to model messages (Anthropic-style)
            model_messages.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": tool_use_id,
                            "content": [
                                {"type": "text", "text": result.get("summary", "")},
                                {"type": "text", "text": str(result.get("data", {}))},
                            ],
                        }
                    ],
                }
            )

        # Continue loop; model now has tool_result blocks.

