"use client";

import React, { useEffect, useMemo, useRef, useState } from "react";
import { Markdown } from "./Markdown";

type ChatMsg = { role: "user" | "assistant"; text: string };
type ToolEvent = { tool_name: string; input?: any; result?: any; trace_id?: string; ts?: number; kind: "call" | "result" };
type Skill = { name: string; version?: string; description?: string; tags?: string[]; tools?: { name: string; description?: string }[] };
type SessionItem = { id: string; created_at_ms: number; title?: string | null };
type McpServer = {
  name: string;
  transport: "stdio" | "http";
  command?: string | null;
  args?: string[];
  url?: string | null;
  env?: Record<string, string>;
  timeout_ms?: number;
  enabled?: boolean;
  created_at_ms?: number;
  updated_at_ms?: number;
};

function apiBase() {
  return process.env.NEXT_PUBLIC_AGENT_API_BASE_URL || "http://localhost:8080";
}

const SESSION_KEY = "edwinxu-agent.sessionId";
const SKILLS_ALLOW_KEY = "edwinxu-agent.skills.allow";

function normalizeAssistantText(s: string): string {
  // Avoid rendering huge vertical whitespace from excessive newlines.
  return String(s ?? "").replace(/\n{3,}/g, "\n\n").trimEnd();
}

export default function Page() {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [traceId, setTraceId] = useState<string | null>(null);
  const [state, setState] = useState<string>("IDLE");
  const [text, setText] = useState("");
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [toolEvents, setToolEvents] = useState<ToolEvent[]>([]);
  const [sessions, setSessions] = useState<SessionItem[]>([]);
  const [sessionsLoading, setSessionsLoading] = useState(false);
  const [skills, setSkills] = useState<Skill[]>([]);
  const [skillsAllow, setSkillsAllow] = useState<string[]>([]);
  const [mcpServers, setMcpServers] = useState<McpServer[]>([]);
  const [newMcp, setNewMcp] = useState<McpServer>({
    name: "",
    transport: "stdio",
    command: "node",
    args: [],
    url: "",
    env: {},
    timeout_ms: 30000,
    enabled: true,
  });
  const [mcpFormOpen, setMcpFormOpen] = useState(false);
  const [mcpEditingName, setMcpEditingName] = useState<string | null>(null);
  const assistantStreamRef = useRef<string>("");
  const esRef = useRef<EventSource | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);

  const base = useMemo(() => apiBase(), []);

  function setActiveSession(id: string) {
    setSessionId(id);
    setMessages([]);
    setText("");
    setTraceId(null);
    setState("IDLE");
    setToolEvents([]);
    assistantStreamRef.current = "";
    try {
      localStorage.setItem(SESSION_KEY, id);
    } catch {
      // ignore
    }
    const sp = new URLSearchParams(window.location.search);
    sp.set("session", id);
    window.history.replaceState(null, "", `/?${sp.toString()}`);
  }

  async function refreshSessions(): Promise<SessionItem[]> {
    setSessionsLoading(true);
    try {
      const r = await fetch(`${base}/v1/sessions?limit=50`);
      const j = await r.json();
      const list: SessionItem[] = j.sessions ?? [];
      setSessions(list);
      return list;
    } finally {
      setSessionsLoading(false);
    }
  }

  async function createNewSession() {
    const r = await fetch(`${base}/v1/sessions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title: null }),
    });
    const j = await r.json();
    await refreshSessions();
    setMessages([]);
    setActiveSession(String(j.id));
  }

  async function deleteSessionById(id: string) {
    if (!confirm("确定要删除这个会话吗？删除后无法恢复。")) return;
    await fetch(`${base}/v1/sessions/${encodeURIComponent(id)}`, { method: "DELETE" });
    const list = await refreshSessions();
    if (sessionId === id) {
      const next = list.filter((s) => s.id !== id)[0]?.id;
      if (next) setActiveSession(next);
      else await createNewSession();
    }
  }

  useEffect(() => {
    let cancelled = false;

    (async () => {
      const sp = new URLSearchParams(window.location.search);
      const urlSid = sp.get("session");
      let storedSid: string | null = null;
      try {
        storedSid = localStorage.getItem(SESSION_KEY);
      } catch {
        storedSid = null;
      }

      if (cancelled) return;
      const list = await refreshSessions();
      const candidate = urlSid || storedSid;
      if (candidate) {
        try {
          const r = await fetch(`${base}/v1/sessions/${candidate}`);
          if (r.ok) {
            setActiveSession(candidate);
            return;
          }
        } catch {
          // ignore
        }
      }

      // fallback to most recent session, or create one if none
      const latest = (list[0]?.id as string | undefined) ?? null;
      if (latest) setActiveSession(latest);
      else await createNewSession();
    })().catch(console.error);

    return () => {
      cancelled = true;
    };
  }, [base]);

  useEffect(() => {
    (async () => {
      const r = await fetch(`${base}/v1/skills`);
      const j = await r.json();
      const loadedSkills: Skill[] = j.skills ?? [];
      setSkills(loadedSkills);
    })().catch(console.error);

    (async () => {
      const r = await fetch(`${base}/v1/mcp/servers`);
      const j = await r.json();
      setMcpServers(j.servers ?? []);
    })().catch(() => {
      // ok if backend doesn't support yet; UI will just show empty
      setMcpServers([]);
    });
  }, [base]);

  useEffect(() => {
    try {
      const raw = localStorage.getItem(SKILLS_ALLOW_KEY);
      if (raw) {
        const parsed = JSON.parse(raw);
        if (Array.isArray(parsed)) setSkillsAllow(parsed.map(String));
      }
    } catch {
      // ignore
    }
  }, []);

  useEffect(() => {
    // default allowlist: all loaded skills (so existing behavior keeps working)
    if (skills.length === 0) return;
    if (skillsAllow.length > 0) return;
    const all = skills.map((s) => s.name).filter(Boolean);
    setSkillsAllow(all);
  }, [skills, skillsAllow.length]);

  useEffect(() => {
    try {
      localStorage.setItem(SKILLS_ALLOW_KEY, JSON.stringify(skillsAllow));
    } catch {
      // ignore
    }
  }, [skillsAllow]);

  useEffect(() => {
    if (!sessionId) return;
    (async () => {
      const r = await fetch(`${base}/v1/sessions/${sessionId}/messages?limit=200`);
      const j = await r.json();
      const loaded: ChatMsg[] = (j.messages ?? [])
        .filter((m: any) => m && (m.role === "user" || m.role === "assistant"))
        .map((m: any) => {
          const c = m.content;
          const t = typeof c === "string" ? c : c?.text ?? JSON.stringify(c);
          return { role: m.role, text: String(t) };
        });
      setMessages(loaded);
    })().catch(console.error);
  }, [base, sessionId]);

  useEffect(() => {
    if (!sessionId) return;
    if (esRef.current) esRef.current.close();

    const es = new EventSource(`${base}/v1/sessions/${sessionId}/events`);
    esRef.current = es;

    es.onmessage = (ev) => {
      try {
        const e = JSON.parse(ev.data);
        if (e.type === "agent.state") {
          setState(e.state);
          if (e.trace_id) setTraceId(e.trace_id);
        }
        if (e.type === "assistant.delta") {
          assistantStreamRef.current += e.delta || "";
          setMessages((prev) => {
            const next = [...prev];
            const last = next[next.length - 1];
            const view = normalizeAssistantText(assistantStreamRef.current);
            if (!last || last.role !== "assistant" || last.text.includes("（流式）") === false) {
              next.push({ role: "assistant", text: `（流式）${view}` });
            } else {
              next[next.length - 1] = { role: "assistant", text: `（流式）${view}` };
            }
            return next;
          });
        }
        if (e.type === "assistant.message") {
          assistantStreamRef.current = "";
          const content = normalizeAssistantText(e.message?.content ?? "");
          setMessages((prev) => {
            // replace last streaming assistant message if exists
            const next = [...prev];
            if (next.length && next[next.length - 1].role === "assistant" && next[next.length - 1].text.startsWith("（流式）")) {
              next[next.length - 1] = { role: "assistant", text: String(content) };
            } else {
              next.push({ role: "assistant", text: String(content) });
            }
            return next;
          });
        }
        if (e.type === "tool.call") {
          setToolEvents((prev) => [
            ...prev,
            { kind: "call", tool_name: e.tool_name, input: e.input, trace_id: e.trace_id, ts: Date.now() },
          ]);
        }
        if (e.type === "tool.result") {
          setToolEvents((prev) => [
            ...prev,
            { kind: "result", tool_name: e.tool_name, result: e.result, trace_id: e.trace_id, ts: Date.now() },
          ]);
        }
      } catch (err) {
        console.error(err);
      }
    };

    es.onerror = (err) => {
      console.error("SSE error", err);
    };

    return () => {
      es.close();
    };
  }, [base, sessionId]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages.length, toolEvents.length]);

  async function send() {
    if (!sessionId) return;
    const content = text.trim();
    if (!content) return;
    setText("");
    setMessages((prev) => [...prev, { role: "user", text: content }]);
    assistantStreamRef.current = "";

    await fetch(`${base}/v1/sessions/${sessionId}/messages`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        content,
        stream: true,
        skills: { mode: "allowlist", allow: skillsAllow, deny: [] },
        policy: { max_tool_calls: 12, tool_timeout_ms: 30000, require_confirmation_for: [] },
        metadata: { client: "web" },
      }),
    });
  }

  async function refreshSkills() {
    const r = await fetch(`${base}/v1/skills`);
    const j = await r.json();
    setSkills(j.skills ?? []);
  }

  async function refreshMcp() {
    const r = await fetch(`${base}/v1/mcp/servers`);
    const j = await r.json();
    setMcpServers(j.servers ?? []);
  }

  async function upsertMcp() {
    const payload = {
      server: {
        ...newMcp,
        name: newMcp.name.trim(),
        args: (newMcp.args ?? []).filter(Boolean),
        env: newMcp.env ?? {},
      },
    };
    await fetch(`${base}/v1/mcp/servers`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    await refreshMcp();
    setNewMcp((p) => ({ ...p, name: "" }));
    closeMcpForm();
  }

  function closeMcpForm() {
    setMcpFormOpen(false);
    setMcpEditingName(null);
  }

  function resetMcpFormForCreate() {
    setNewMcp({
      name: "",
      transport: "stdio",
      command: "node",
      args: [],
      url: "",
      env: {},
      timeout_ms: 30000,
      enabled: true,
    });
    setMcpEditingName(null);
    setMcpFormOpen(true);
  }

  function openMcpFormForEdit(s: McpServer) {
    setNewMcp({
      name: s.name,
      transport: s.transport,
      command: s.command ?? "node",
      args: s.args ?? [],
      url: s.url ?? "",
      env: s.env ?? {},
      timeout_ms: s.timeout_ms ?? 30000,
      enabled: s.enabled ?? true,
    });
    setMcpEditingName(s.name);
    setMcpFormOpen(true);
  }

  const canSaveMcp =
    !!newMcp.name.trim() &&
    (newMcp.transport === "http" ? !!String(newMcp.url ?? "").trim() : !!String(newMcp.command ?? "").trim());

  useEffect(() => {
    if (!mcpFormOpen) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") closeMcpForm();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [mcpFormOpen]);

  return (
    <div className="layout">
      <div className="leftCol">
        <div className="panel panelFill">
          <div className="panelHeader">
            <div style={{ fontWeight: 700 }}>会话</div>
            <div className="row" style={{ gap: 8 }}>
              <button className="btn" onClick={() => createNewSession().catch(console.error)}>
                新建会话
              </button>
              <span className="badge">{sessionsLoading ? "加载中…" : sessionId ? "就绪" : "创建中…"}</span>
            </div>
          </div>
          <div className="panelBody" style={{ padding: 0, minHeight: 0 }}>
            <div style={{ height: "100%", display: "grid", gridTemplateRows: "1fr 1fr", minHeight: 0 }}>
              <div style={{ padding: "12px 14px", overflow: "auto", minHeight: 0 }}>
                <div className="muted small" style={{ marginBottom: 8 }}>
                  会话列表
                </div>
                <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                  {sessions.length === 0 ? <div className="muted small">暂无会话</div> : null}
                  {sessions.map((s) => {
                    const active = s.id === sessionId;
                    const title = (s.title ?? "").trim() || "未命名会话";
                    return (
                      <div
                        key={s.id}
                        className="row"
                        style={{
                          justifyContent: "space-between",
                          padding: "8px 10px",
                          borderRadius: 12,
                          border: `1px solid var(--border)`,
                          background: active ? "color-mix(in srgb, var(--btn-bg), transparent 40%)" : "transparent",
                          cursor: "pointer",
                        }}
                        onClick={() => setActiveSession(s.id)}
                        title={s.id}
                      >
                        <div style={{ display: "flex", flexDirection: "column", gap: 2, minWidth: 0 }}>
                          <div style={{ fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{title}</div>
                          <div className="muted small" style={{ fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace" }}>
                            {s.id}
                          </div>
                        </div>
                        <button
                          className="btn"
                          onClick={(e) => {
                            e.stopPropagation();
                            deleteSessionById(s.id).catch(console.error);
                          }}
                        >
                          删除
                        </button>
                      </div>
                    );
                  })}
                </div>
              </div>

              <div style={{ padding: "12px 14px", overflow: "auto", borderTop: "1px solid var(--border)", minHeight: 0 }}>
                <div className="kv">
                  <div className="muted">会话 ID</div>
                  <div style={{ wordBreak: "break-all" }}>{sessionId || "-"}</div>
                  <div className="muted">追踪 ID</div>
                  <div style={{ wordBreak: "break-all" }}>{traceId || "-"}</div>
                  <div className="muted">状态</div>
                  <div>{state}</div>
                </div>
                <div style={{ height: 12 }} />
                <div style={{ fontWeight: 700, marginBottom: 8 }}>会话配置</div>
                <div className="row" style={{ gap: 8, marginBottom: 8, flexWrap: "wrap" }}>
                  <button
                    className="btn"
                    onClick={() => {
                      const all = skills.map((s) => s.name);
                      setSkillsAllow(all);
                    }}
                  >
                    全选技能
                  </button>
                  <button className="btn" onClick={() => setSkillsAllow([])}>
                    清空允许列表
                  </button>
                  <button className="btn" onClick={() => refreshSkills().catch(console.error)}>
                    刷新技能
                  </button>
                </div>
                <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                  {skills.length === 0 ? <div className="muted small">技能加载中…</div> : null}
                  {skills.map((s) => {
                    const checked = skillsAllow.includes(s.name);
                    return (
                      <label key={s.name} className="row" style={{ justifyContent: "space-between" }}>
                        <span style={{ fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace" }}>{s.name}</span>
                        <input
                          type="checkbox"
                          checked={checked}
                          onChange={(e) => {
                            const on = e.target.checked;
                            setSkillsAllow((prev) => {
                              const set = new Set(prev);
                              if (on) set.add(s.name);
                              else set.delete(s.name);
                              return Array.from(set);
                            });
                          }}
                        />
                      </label>
                    );
                  })}
                </div>
              </div>
            </div>
          </div>
        </div>

        <div className="panel panelFill">
          <div className="panelHeader">
            <div style={{ fontWeight: 700 }}>MCP 配置</div>
            <div className="row" style={{ gap: 8 }}>
              <button className="btn" onClick={() => refreshMcp().catch(console.error)}>
                刷新
              </button>
              <button className="btn" onClick={() => resetMcpFormForCreate()}>
                新增
              </button>
              <span className="badge">{mcpServers.length}</span>
            </div>
          </div>
          <div className="panelBodyScroll">
            {mcpServers.length === 0 ? <div className="muted small">暂无 MCP 服务</div> : null}
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {mcpServers.map((s) => (
                <div key={s.name} className="row" style={{ justifyContent: "space-between" }}>
                  <div style={{ display: "flex", flexDirection: "column" }}>
                    <div style={{ fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace" }}>{s.name}</div>
                    <div className="muted small">
                      {s.transport} · {s.enabled ? "已启用" : "已禁用"}
                    </div>
                  </div>
                  <div className="row" style={{ gap: 8 }}>
                    <button className="btn" onClick={() => openMcpFormForEdit(s)}>
                      编辑
                    </button>
                    <button
                      className="btn"
                      onClick={async () => {
                        await fetch(`${base}/v1/mcp/servers/${encodeURIComponent(s.name)}:${s.enabled ? "disable" : "enable"}`, {
                          method: "POST",
                        });
                        await refreshMcp();
                      }}
                    >
                      {s.enabled ? "禁用" : "启用"}
                    </button>
                    <button
                      className="btn"
                      onClick={async () => {
                        await fetch(`${base}/v1/mcp/servers/${encodeURIComponent(s.name)}`, { method: "DELETE" });
                        await refreshMcp();
                      }}
                    >
                      删除
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      {mcpFormOpen ? (
        <div
          className="modalBackdrop"
          role="dialog"
          aria-modal="true"
          onMouseDown={(e) => {
            if (e.target === e.currentTarget) closeMcpForm();
          }}
        >
          <div className="modal" onMouseDown={(e) => e.stopPropagation()}>
            <div className="modalHeader">
              <div style={{ fontWeight: 700 }}>{mcpEditingName ? "编辑 MCP 服务" : "新增 MCP 服务"}</div>
              <div className="row" style={{ gap: 8 }}>
                <button className="btn" onClick={() => closeMcpForm()}>
                  关闭
                </button>
              </div>
            </div>
            <div className="modalBody">
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                <input
                  className="input"
                  value={newMcp.name}
                  onChange={(e) => setNewMcp((p) => ({ ...p, name: e.target.value }))}
                  placeholder="名称（例如 repo）"
                  disabled={!!mcpEditingName}
                />
                <select
                  className="input"
                  value={newMcp.transport}
                  onChange={(e) => setNewMcp((p) => ({ ...p, transport: e.target.value as any }))}
                >
                  <option value="stdio">stdio</option>
                  <option value="http">http</option>
                </select>
                {newMcp.transport === "http" ? (
                  <input
                    className="input"
                    value={String(newMcp.url ?? "")}
                    onChange={(e) => setNewMcp((p) => ({ ...p, url: e.target.value }))}
                    placeholder="URL（例如 https://mcp.example.com）"
                  />
                ) : (
                  <>
                    <input
                      className="input"
                      value={String(newMcp.command ?? "")}
                      onChange={(e) => setNewMcp((p) => ({ ...p, command: e.target.value }))}
                      placeholder="命令（例如 node）"
                    />
                    <input
                      className="input"
                      value={(newMcp.args ?? []).join(" ")}
                      onChange={(e) => setNewMcp((p) => ({ ...p, args: e.target.value.split(/\s+/).filter(Boolean) }))}
                      placeholder="参数（空格分隔）"
                    />
                  </>
                )}
                <div className="row" style={{ gap: 8, justifyContent: "flex-end" }}>
                  <button className="btn" onClick={() => closeMcpForm()}>
                    取消
                  </button>
                  <button className="btn" disabled={!canSaveMcp} onClick={() => upsertMcp().catch(console.error)}>
                    保存
                  </button>
                </div>
              </div>
              <div className="muted small" style={{ marginTop: 10 }}>
                说明：当前仅管理配置；MCP 工具接入后续实现。（支持按 Esc 或点击遮罩关闭）
              </div>
            </div>
          </div>
        </div>
      ) : null}

      <div className="panel" style={{ display: "grid", gridTemplateRows: "54px 1fr auto" }}>
        <div className="panelHeader">
          <div style={{ fontWeight: 700 }}>对话</div>
          <div className="row">
            <span className="badge">{state}</span>
          </div>
        </div>

        <div className="messages" ref={scrollRef}>
          {messages.length === 0 ? (
            <div className="muted">输入 “现在几点了？” 试试（会触发 `time.now`）。</div>
          ) : null}
          {messages.map((m, idx) => (
            <div key={idx} className={`bubble ${m.role}`}>
              <div className="muted small" style={{ marginBottom: 6 }}>
                {m.role === "user" ? "用户" : "助手"}
              </div>
              {m.role === "assistant" ? (
                <Markdown>{m.text.startsWith("（流式）") ? m.text.slice("（流式）".length) : m.text}</Markdown>
              ) : (
                m.text
              )}
            </div>
          ))}
        </div>

        <div className="composer">
          <textarea
            className="input"
            rows={3}
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="说点什么…（Enter 发送，Shift+Enter 换行）"
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                send().catch(console.error);
              }
            }}
          />
          <button className="btn" onClick={() => send().catch(console.error)}>
            发送
          </button>
        </div>
      </div>

      <div className="panel">
        <div className="panelHeader">
          <div style={{ fontWeight: 700 }}>调试面板</div>
          <span className="badge">{toolEvents.length} 条事件</span>
        </div>
        <div className="panelBody" style={{ overflow: "auto", height: "calc(100vh - 24px - 54px)" }}>
          {toolEvents.length === 0 ? (
            <div className="muted">工具调用会显示在这里（input / result）。</div>
          ) : null}
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {toolEvents.map((e, idx) => (
              <div key={idx} className="bubble assistant" style={{ maxWidth: "unset" }}>
                <div className="row" style={{ justifyContent: "space-between" }}>
                  <div style={{ fontWeight: 600 }}>
                    {e.kind === "call" ? "工具调用" : "工具结果"} · {e.tool_name}
                  </div>
                  <span className="badge">{e.trace_id || "-"}</span>
                </div>
                <div style={{ height: 8 }} />
                <pre style={{ margin: 0, whiteSpace: "pre-wrap" }}>
                  {JSON.stringify(e.kind === "call" ? e.input : e.result, null, 2)}
                </pre>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

