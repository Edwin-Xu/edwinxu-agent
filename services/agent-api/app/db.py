from __future__ import annotations

import json
import os
import sqlite3
import time
from dataclasses import dataclass
import threading
from typing import Any


SCHEMA_SQL = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS sessions (
  id TEXT PRIMARY KEY,
  created_at_ms INTEGER NOT NULL,
  title TEXT,
  config_json TEXT
);

CREATE TABLE IF NOT EXISTS messages (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL,
  role TEXT NOT NULL,
  content_json TEXT NOT NULL,
  created_at_ms INTEGER NOT NULL,
  trace_id TEXT,
  FOREIGN KEY(session_id) REFERENCES sessions(id)
);

CREATE TABLE IF NOT EXISTS mcp_servers (
  name TEXT PRIMARY KEY,
  transport TEXT NOT NULL,
  command TEXT,
  args_json TEXT,
  url TEXT,
  env_json TEXT,
  timeout_ms INTEGER NOT NULL,
  enabled INTEGER NOT NULL,
  created_at_ms INTEGER NOT NULL,
  updated_at_ms INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS tool_calls (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL,
  trace_id TEXT NOT NULL,
  tool_name TEXT NOT NULL,
  input_json TEXT NOT NULL,
  result_json TEXT NOT NULL,
  started_at_ms INTEGER NOT NULL,
  finished_at_ms INTEGER NOT NULL,
  status TEXT NOT NULL,
  FOREIGN KEY(session_id) REFERENCES sessions(id)
);

CREATE TABLE IF NOT EXISTS runs (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL,
  trace_id TEXT NOT NULL,
  status TEXT NOT NULL,
  created_at_ms INTEGER NOT NULL,
  finished_at_ms INTEGER,
  error_json TEXT,
  result_message_id TEXT,
  FOREIGN KEY(session_id) REFERENCES sessions(id)
);
"""


@dataclass(frozen=True)
class Db:
    conn: sqlite3.Connection
    lock: threading.Lock


def now_ms() -> int:
    return int(time.time() * 1000)


def ensure_parent_dir(path: str) -> None:
    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, exist_ok=True)


def connect(db_path: str) -> Db:
    ensure_parent_dir(db_path)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    return Db(conn=conn, lock=threading.Lock())


def _json_dumps(x: Any) -> str:
    return json.dumps(x, ensure_ascii=False, separators=(",", ":"))


def create_session(db: Db, session_id: str, title: str | None, config: dict[str, Any] | None) -> None:
    with db.lock:
        db.conn.execute(
            "INSERT INTO sessions(id, created_at_ms, title, config_json) VALUES (?, ?, ?, ?)",
            (session_id, now_ms(), title, _json_dumps(config or {})),
        )
        db.conn.commit()


def get_session(db: Db, session_id: str) -> dict[str, Any] | None:
    with db.lock:
        row = db.conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
    if not row:
        return None
    return {
        "id": row["id"],
        "created_at_ms": row["created_at_ms"],
        "title": row["title"],
        "config": json.loads(row["config_json"] or "{}"),
    }


def list_sessions(db: Db, limit: int = 50) -> list[dict[str, Any]]:
    with db.lock:
        rows = db.conn.execute(
            "SELECT * FROM sessions ORDER BY created_at_ms DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [
        {
            "id": r["id"],
            "created_at_ms": r["created_at_ms"],
            "title": r["title"],
        }
        for r in rows
    ]


def delete_session(db: Db, session_id: str) -> bool:
    """
    Best-effort cascade delete.
    (SQLite foreign keys are not enforced by default unless PRAGMA foreign_keys=ON.)
    """
    with db.lock:
        db.conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
        db.conn.execute("DELETE FROM tool_calls WHERE session_id = ?", (session_id,))
        db.conn.execute("DELETE FROM runs WHERE session_id = ?", (session_id,))
        cur = db.conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        db.conn.commit()
        return cur.rowcount > 0


def add_message(
    db: Db,
    message_id: str,
    session_id: str,
    role: str,
    content: Any,
    trace_id: str | None,
) -> None:
    with db.lock:
        db.conn.execute(
            "INSERT INTO messages(id, session_id, role, content_json, created_at_ms, trace_id) VALUES (?, ?, ?, ?, ?, ?)",
            (message_id, session_id, role, _json_dumps(content), now_ms(), trace_id),
        )
        db.conn.commit()


def list_messages(db: Db, session_id: str, limit: int = 200) -> list[dict[str, Any]]:
    with db.lock:
        rows = db.conn.execute(
            "SELECT * FROM messages WHERE session_id = ? ORDER BY created_at_ms ASC LIMIT ?",
            (session_id, limit),
        ).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        out.append(
            {
                "id": r["id"],
                "session_id": r["session_id"],
                "role": r["role"],
                "content": json.loads(r["content_json"]),
                "created_at_ms": r["created_at_ms"],
                "trace_id": r["trace_id"],
            }
        )
    return out


def upsert_mcp_server(
    db: Db,
    *,
    name: str,
    transport: str,
    command: str | None,
    args: list[str] | None,
    url: str | None,
    env: dict[str, str] | None,
    timeout_ms: int,
    enabled: bool,
) -> None:
    ts = now_ms()
    with db.lock:
        existing = db.conn.execute("SELECT name FROM mcp_servers WHERE name = ?", (name,)).fetchone()
        if existing:
            db.conn.execute(
                """
                UPDATE mcp_servers
                SET transport = ?, command = ?, args_json = ?, url = ?, env_json = ?, timeout_ms = ?, enabled = ?, updated_at_ms = ?
                WHERE name = ?
                """,
                (
                    transport,
                    command,
                    _json_dumps(args or []),
                    url,
                    _json_dumps(env or {}),
                    int(timeout_ms),
                    1 if enabled else 0,
                    ts,
                    name,
                ),
            )
        else:
            db.conn.execute(
                """
                INSERT INTO mcp_servers(name, transport, command, args_json, url, env_json, timeout_ms, enabled, created_at_ms, updated_at_ms)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    name,
                    transport,
                    command,
                    _json_dumps(args or []),
                    url,
                    _json_dumps(env or {}),
                    int(timeout_ms),
                    1 if enabled else 0,
                    ts,
                    ts,
                ),
            )
        db.conn.commit()


def list_mcp_servers(db: Db) -> list[dict[str, Any]]:
    with db.lock:
        rows = db.conn.execute("SELECT * FROM mcp_servers ORDER BY updated_at_ms DESC").fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        out.append(
            {
                "name": r["name"],
                "transport": r["transport"],
                "command": r["command"],
                "args": json.loads(r["args_json"] or "[]"),
                "url": r["url"],
                "env": json.loads(r["env_json"] or "{}"),
                "timeout_ms": r["timeout_ms"],
                "enabled": bool(r["enabled"]),
                "created_at_ms": r["created_at_ms"],
                "updated_at_ms": r["updated_at_ms"],
            }
        )
    return out


def delete_mcp_server(db: Db, name: str) -> bool:
    with db.lock:
        cur = db.conn.execute("DELETE FROM mcp_servers WHERE name = ?", (name,))
        db.conn.commit()
        return cur.rowcount > 0


def set_mcp_server_enabled(db: Db, name: str, enabled: bool) -> bool:
    with db.lock:
        cur = db.conn.execute(
            "UPDATE mcp_servers SET enabled = ?, updated_at_ms = ? WHERE name = ?",
            (1 if enabled else 0, now_ms(), name),
        )
        db.conn.commit()
        return cur.rowcount > 0


def add_tool_call(
    db: Db,
    tool_call_id: str,
    session_id: str,
    trace_id: str,
    tool_name: str,
    tool_input: dict[str, Any],
    result: dict[str, Any],
    started_at_ms: int,
    finished_at_ms: int,
    status: str,
) -> None:
    with db.lock:
        db.conn.execute(
            """
            INSERT INTO tool_calls(id, session_id, trace_id, tool_name, input_json, result_json, started_at_ms, finished_at_ms, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                tool_call_id,
                session_id,
                trace_id,
                tool_name,
                _json_dumps(tool_input),
                _json_dumps(result),
                started_at_ms,
                finished_at_ms,
                status,
            ),
        )
        db.conn.commit()


def create_run(db: Db, run_id: str, session_id: str, trace_id: str) -> None:
    with db.lock:
        db.conn.execute(
            "INSERT INTO runs(id, session_id, trace_id, status, created_at_ms) VALUES (?, ?, ?, ?, ?)",
            (run_id, session_id, trace_id, "queued", now_ms()),
        )
        db.conn.commit()


def update_run_status(
    db: Db,
    run_id: str,
    status: str,
    *,
    finished_at_ms: int | None = None,
    error: dict[str, Any] | None = None,
    result_message_id: str | None = None,
) -> None:
    with db.lock:
        db.conn.execute(
            """
            UPDATE runs
            SET status = ?, finished_at_ms = COALESCE(?, finished_at_ms), error_json = COALESCE(?, error_json), result_message_id = COALESCE(?, result_message_id)
            WHERE id = ?
            """,
            (
                status,
                finished_at_ms,
                _json_dumps(error) if error is not None else None,
                result_message_id,
                run_id,
            ),
        )
        db.conn.commit()


def get_run(db: Db, run_id: str) -> dict[str, Any] | None:
    with db.lock:
        row = db.conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    if not row:
        return None
    return {
        "id": row["id"],
        "session_id": row["session_id"],
        "trace_id": row["trace_id"],
        "status": row["status"],
        "created_at_ms": row["created_at_ms"],
        "finished_at_ms": row["finished_at_ms"],
        "error": json.loads(row["error_json"]) if row["error_json"] else None,
        "result_message_id": row["result_message_id"],
    }

