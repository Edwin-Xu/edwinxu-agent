from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Union

import yaml


ToolHandler = Union[
    Callable[[dict[str, Any]], dict[str, Any]],
    Callable[[dict[str, Any]], Awaitable[dict[str, Any]]],
]


@dataclass(frozen=True)
class ToolDef:
    name: str
    description: str
    input_schema: dict[str, Any]
    timeout_ms: int
    handler: ToolHandler


@dataclass(frozen=True)
class SkillDef:
    name: str
    version: str
    description: str
    tags: list[str]
    tools: list[ToolDef]


class SkillRegistry:
    def __init__(self) -> None:
        self._skills: dict[str, SkillDef] = {}
        self._tools: dict[str, ToolDef] = {}

    def list_skills(self) -> list[dict[str, Any]]:
        return [
            {
                "name": s.name,
                "version": s.version,
                "description": s.description,
                "tags": s.tags,
                "tools": [{"name": t.name, "description": t.description} for t in s.tools],
            }
            for s in sorted(self._skills.values(), key=lambda x: x.name)
        ]

    def list_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "name": t.name,
                "description": t.description,
                "input_schema": t.input_schema,
                "timeout_ms": t.timeout_ms,
            }
            for t in sorted(self._tools.values(), key=lambda x: x.name)
        ]

    def get_tool(self, tool_name: str) -> ToolDef | None:
        return self._tools.get(tool_name)

    def register_skill(self, skill: SkillDef) -> None:
        if skill.name in self._skills:
            raise ValueError(f"Duplicate skill name: {skill.name}")
        for t in skill.tools:
            if t.name in self._tools:
                raise ValueError(f"Duplicate tool name: {t.name}")
        self._skills[skill.name] = skill
        for t in skill.tools:
            self._tools[t.name] = t


def tool_result(
    *,
    status: str,
    summary: str,
    data: dict[str, Any] | None = None,
    next_actions: list[str] | None = None,
    artifacts: list[str] | None = None,
    raw: str | None = None,
    duration_ms: int | None = None,
    retries: int | None = None,
) -> dict[str, Any]:
    metrics: dict[str, Any] = {}
    if duration_ms is not None:
        metrics["duration_ms"] = duration_ms
    if retries is not None:
        metrics["retries"] = retries
    out: dict[str, Any] = {
        "status": status,
        "summary": summary,
        "next_actions": next_actions or [],
        "artifacts": artifacts or [],
        "data": data or {},
        "metrics": metrics,
    }
    if raw is not None:
        out["raw"] = raw
    return out


def load_yaml_skill(skill_dir: str) -> dict[str, Any]:
    with open(os.path.join(skill_dir, "skill.yaml"), "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_json_schema(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_builtin_skills(skills_root: str, handlers: dict[str, ToolHandler]) -> SkillRegistry:
    """
    Load skills from `packages/skills/*/skill.yaml`.
    Map tool.name -> handler via `handlers`.
    """
    reg = SkillRegistry()
    if not os.path.isdir(skills_root):
        return reg

    for entry in sorted(os.listdir(skills_root)):
        skill_dir = os.path.join(skills_root, entry)
        if not os.path.isdir(skill_dir):
            continue
        skill_yaml = os.path.join(skill_dir, "skill.yaml")
        if not os.path.isfile(skill_yaml):
            continue

        meta = load_yaml_skill(skill_dir)
        tools: list[ToolDef] = []
        for t in meta.get("tools", []):
            tool_name = t["name"]
            handler = handlers.get(tool_name)
            if handler is None:
                raise ValueError(f"Missing handler for tool: {tool_name}")

            input_schema_ref = t.get("input_schema")
            if isinstance(input_schema_ref, str):
                schema_path = os.path.join(skill_dir, input_schema_ref)
                input_schema = load_json_schema(schema_path)
            else:
                input_schema = input_schema_ref or {"type": "object", "properties": {}}

            tools.append(
                ToolDef(
                    name=tool_name,
                    description=t.get("description", ""),
                    input_schema=input_schema,
                    timeout_ms=int(t.get("timeout_ms", 30000)),
                    handler=handler,
                )
            )

        reg.register_skill(
            SkillDef(
                name=meta["name"],
                version=meta.get("version", "0.0.0"),
                description=meta.get("description", ""),
                tags=meta.get("tags", []) or [],
                tools=tools,
            )
        )

    return reg

