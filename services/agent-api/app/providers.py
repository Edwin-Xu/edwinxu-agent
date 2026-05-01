from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


class ModelProvider(Protocol):
    async def respond(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_tokens: int,
    ) -> dict[str, Any]:
        """
        Return a normalized response:
        {
          "content": [{"type":"text","text":...} | {"type":"tool_use","id":...,"name":...,"input":{...}}...]
        }
        """


@dataclass(frozen=True)
class MockProvider:
    async def respond(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_tokens: int,
    ) -> dict[str, Any]:
        # Simple behavior:
        # - If last user message asks for time and tool exists => tool_use time.now
        # - If last user message is a tool_result for time.now => produce final text
        # - Else => echo last user text
        last_user_text = ""
        last_tool_result: dict[str, Any] | None = None
        for m in reversed(messages):
            if m.get("role") != "user":
                continue
            content = m.get("content")
            if isinstance(content, list) and content and isinstance(content[0], dict) and content[0].get("type") == "tool_result":
                last_tool_result = content[0]
                break
            if isinstance(content, list):
                # concat text blocks
                parts: list[str] = []
                for b in content:
                    if isinstance(b, dict) and b.get("type") == "text" and b.get("text"):
                        parts.append(str(b["text"]))
                last_user_text = "".join(parts).strip()
                break
            if isinstance(content, str):
                last_user_text = content.strip()
                break

        tool_names = {t["name"] for t in tools}
        if last_tool_result and last_tool_result.get("tool_use_id") == "toolu_mock_time":
            # Try to extract ISO time from tool_result content blocks
            iso = None
            content = last_tool_result.get("content") or []
            if isinstance(content, list):
                for b in content:
                    if isinstance(b, dict) and b.get("type") == "text" and isinstance(b.get("text"), str):
                        txt = b["text"]
                        if "iso" in txt and ":" in txt:
                            iso = txt
            if iso is None:
                iso = "（mock）time.now 已完成"
            return {"content": [{"type": "text", "text": f"现在时间：{iso}"}]}

        if any(k in last_user_text.lower() for k in ["time", "时间", "几点"]) and "time.now" in tool_names:
            return {
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu_mock_time",
                        "name": "time.now",
                        "input": {"tz": "Asia/Shanghai"},
                    }
                ]
            }

        return {"content": [{"type": "text", "text": f"（mock）你说：{last_user_text}"}]}


class AnthropicProvider:
    def __init__(
        self,
        *,
        model: str,
        api_key: str | None = None,
        auth_token: str | None = None,
        base_url: str | None = None,
        timeout_ms: int = 300000,
    ) -> None:
        from anthropic import AsyncAnthropic  # local import to keep optional
        import httpx

        # Support custom gateways:
        # - base_url: ANTHROPIC_BASE_URL
        # - auth_token: ANTHROPIC_AUTH_TOKEN (also used as api_key if api_key not provided)
        resolved_key = api_key or auth_token
        if not resolved_key:
            raise ValueError("AnthropicProvider requires api_key or auth_token")

        default_headers = {}
        if auth_token:
            # Many gateways expect Authorization; we send it in addition to x-api-key for compatibility.
            default_headers["Authorization"] = auth_token

        http_client = httpx.AsyncClient(timeout=httpx.Timeout(timeout_ms / 1000.0))
        self._client = AsyncAnthropic(
            api_key=resolved_key,
            base_url=base_url,
            default_headers=default_headers or None,
            http_client=http_client,
        )
        self._model = model

    async def respond(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_tokens: int,
    ) -> dict[str, Any]:
        # Anthropic SDK returns content blocks; we normalize to dict form.
        resp = await self._client.messages.create(
            model=self._model,
            max_tokens=max_tokens,
            system=system,
            tools=tools,
            messages=messages,
        )
        content: list[dict[str, Any]] = []
        for block in resp.content:
            btype = getattr(block, "type", None)
            if btype == "text":
                content.append({"type": "text", "text": block.text})
            elif btype == "tool_use":
                content.append(
                    {
                        "type": "tool_use",
                        "id": block.id,
                        "name": block.name,
                        "input": block.input,
                    }
                )
        return {"content": content}

