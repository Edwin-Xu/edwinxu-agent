from __future__ import annotations

import json
import queue
import threading
import time
from typing import Any, Optional

import httpx
import typer


app = typer.Typer(add_completion=False, no_args_is_help=True)


def _iter_sse_lines(resp: httpx.Response):
    for line in resp.iter_lines():
        if not line:
            continue
        yield line


def _parse_sse_data(line: str) -> dict[str, Any] | None:
    if not line.startswith("data:"):
        return None
    data = line[len("data:") :].strip()
    if not data:
        return None
    try:
        return json.loads(data)
    except Exception:  # noqa: BLE001
        return None


def _create_session(client: httpx.Client, api: str) -> str:
    r = client.post(f"{api}/v1/sessions", json={"title": "cli"})
    r.raise_for_status()
    return r.json()["id"]


def _send_message(client: httpx.Client, api: str, session_id: str, content: str) -> dict[str, Any]:
    r = client.post(
        f"{api}/v1/sessions/{session_id}/messages",
        json={
            "content": content,
            "stream": True,
            # allowlist empty => allow all skills (server-side convention)
            "skills": {"mode": "allowlist", "allow": [], "deny": []},
            "policy": {"max_tool_calls": 12, "tool_timeout_ms": 30000, "require_confirmation_for": []},
            "metadata": {"client": "cli"},
        },
        timeout=60,
    )
    r.raise_for_status()
    return r.json()


@app.command()
def run(
    prompt: str = typer.Argument(..., help="User prompt"),
    api: str = typer.Option("http://localhost:8080", "--api", help="Agent API base url"),
    session: Optional[str] = typer.Option(None, "--session", help="Reuse an existing session_id"),
    json_out: bool = typer.Option(False, "--json", help="Output final result as JSON"),
) -> None:
    """
    Run one prompt against the agent.
    """
    with httpx.Client() as post_client:
        session_id = session or _create_session(post_client, api)

        # Start SSE listener first (best-effort, avoids missing early deltas).
        evq: "queue.Queue[dict[str, Any]]" = queue.Queue()
        stop = threading.Event()

        def listen():
            try:
                with httpx.Client() as sse_client:
                    with sse_client.stream("GET", f"{api}/v1/sessions/{session_id}/events", timeout=None) as resp:
                        for line in _iter_sse_lines(resp):
                            if stop.is_set():
                                return
                            evt = _parse_sse_data(line)
                            if evt:
                                evq.put(evt)
            except Exception:  # noqa: BLE001
                return

        t = threading.Thread(target=listen, daemon=True)
        t.start()

        send_res = _send_message(post_client, api, session_id, prompt)
        trace_id = send_res.get("trace_id")

        final_text = ""
        tool_calls = 0
        started = time.time()
        done = False

        while not done:
            try:
                evt = evq.get(timeout=30)
            except queue.Empty:
                break

            et = evt.get("type")
            if et == "assistant.delta":
                if evt.get("trace_id") == trace_id:
                    delta = evt.get("delta") or ""
                    final_text += delta
                    typer.echo(delta, nl=False)
            elif et == "tool.call" and evt.get("trace_id") == trace_id:
                tool_calls += 1
                typer.echo(f"\n[tool.call] {evt.get('tool_name')} {json.dumps(evt.get('input') or {}, ensure_ascii=False)}")
            elif et == "tool.result" and evt.get("trace_id") == trace_id:
                typer.echo(f"[tool.result] {evt.get('tool_name')} status={evt.get('result', {}).get('status')}")
            elif et == "assistant.message" and evt.get("trace_id") == trace_id:
                # If we printed deltas, this may already be shown; ensure newline.
                if not final_text and evt.get("message", {}).get("content"):
                    final_text = str(evt["message"]["content"])
                typer.echo("")
                done = True
            elif et == "agent.state" and evt.get("trace_id") == trace_id and evt.get("state") == "DONE":
                done = True

        stop.set()

        if json_out:
            typer.echo(
                json.dumps(
                    {
                        "session_id": session_id,
                        "trace_id": trace_id,
                        "assistant": {"content": final_text},
                        "meta": {"tool_calls": tool_calls, "duration_ms": int((time.time() - started) * 1000)},
                    },
                    ensure_ascii=False,
                )
            )


@app.command()
def chat(
    api: str = typer.Option("http://localhost:8080", "--api", help="Agent API base url"),
    session: Optional[str] = typer.Option(None, "--session", help="Reuse an existing session_id"),
) -> None:
    """
    Interactive chat loop.
    """
    with httpx.Client() as client:
        session_id = session or _create_session(client, api)
        typer.echo(f"session_id={session_id}")
        while True:
            prompt = typer.prompt("you", prompt_suffix="> ")
            if prompt.strip() in ("/exit", "/quit"):
                return
            run(prompt, api=api, session=session_id, json_out=False)

