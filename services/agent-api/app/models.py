from __future__ import annotations

from pydantic import BaseModel, Field
from typing import Any, Literal


class SkillsConfig(BaseModel):
    mode: Literal["allowlist", "auto"] = "allowlist"
    allow: list[str] = Field(default_factory=list)
    deny: list[str] = Field(default_factory=list)


class PolicyConfig(BaseModel):
    max_tool_calls: int = 12
    tool_timeout_ms: int = 30000
    require_confirmation_for: list[Literal["write", "exec", "network"]] = Field(default_factory=list)


class CreateSessionRequest(BaseModel):
    title: str | None = None


class CreateSessionResponse(BaseModel):
    id: str
    created_at_ms: int
    title: str | None = None


class SendMessageRequest(BaseModel):
    content: str
    stream: bool = True
    skills: SkillsConfig = Field(default_factory=SkillsConfig)
    policy: PolicyConfig = Field(default_factory=PolicyConfig)
    metadata: dict[str, Any] = Field(default_factory=dict)


class Message(BaseModel):
    id: str
    role: Literal["user", "assistant", "tool"]
    content: Any
    created_at_ms: int
    trace_id: str | None = None


class RunCreateRequest(BaseModel):
    session_id: str | None = None
    content: str
    stream: bool = True
    skills: SkillsConfig = Field(default_factory=SkillsConfig)
    policy: PolicyConfig = Field(default_factory=PolicyConfig)
    metadata: dict[str, Any] = Field(default_factory=dict)


class RunCreateResponse(BaseModel):
    id: str
    session_id: str
    trace_id: str
    status: str


class RunResponse(BaseModel):
    id: str
    session_id: str
    trace_id: str
    status: str
    created_at_ms: int
    finished_at_ms: int | None = None
    error: dict[str, Any] | None = None
    result_message_id: str | None = None


class McpServer(BaseModel):
    name: str
    transport: Literal["stdio", "http"]
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    url: str | None = None
    env: dict[str, str] = Field(default_factory=dict)
    timeout_ms: int = 30000
    enabled: bool = True
    created_at_ms: int | None = None
    updated_at_ms: int | None = None


class UpsertMcpServerRequest(BaseModel):
    server: McpServer

