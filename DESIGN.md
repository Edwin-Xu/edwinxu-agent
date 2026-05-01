# Agent 应用设计文档（Web 对话 + CLI + Agent 后端 + Skills/Tools 映射）

本文档定义本项目的目标、架构边界、模块接口与运行时协议，确保你可以并行开发：
- **前端对话网站**（Chat UI）
- **命令行 CLI**（脚本化/自动化入口）
- **Agent 后端**（对话编排、工具调用、记忆、任务执行）
- **Skills/Tools 映射系统**（把“技能包”映射为可调用工具与可执行动作）

> 约定：这里的 **Skill** 指“能力包/技能说明 + 工具定义 + 运行适配器”；**Tool** 指运行时可被模型调用的函数（function calling / tool use）。

---

## 目标与非目标

### 目标
- **双入口**：Web 与 CLI 共享同一套 Agent 内核与 Skills registry。
- **可扩展**：新增技能不改核心代码，最多新增一个 skill 包或配置文件。
- **可观测**：每次对话、每次工具调用、每个任务都有 trace，可回放。
- **可控**：支持 tool 白名单、权限、预算（token/成本）与速率限制。
- **可流式**：Web 与 CLI 都支持 streaming 输出与“工具调用中”的中间态。

### 非目标（第一阶段不做或弱化）
- 多租户计费与复杂权限体系
- 分布式执行/大规模队列（先单机/单服务跑通）
- 重型向量数据库（先本地/轻量存储，后续可替换）

---

## 总体架构（推荐形态）

### 推荐仓库目录结构（可直接照此创建）

```text
edwinxu-agent/
  DESIGN.md
  README.md
  apps/
    web/                  # 前端对话网站
    cli/                  # 命令行客户端（可选：也可放 packages/）
  services/
    agent-api/            # 后端服务（HTTP + SSE/WS）
  packages/
    agent-core/           # Agent 编排内核（provider、router、memory、policies）
    skills/               # 内置 skills（每个 skill 一个目录）
    shared/               # 共享协议（JSON Schema / OpenAPI / TS types）
  data/
    sqlite/               # 本地数据库（开发/个人模式）
  artifacts/
    traces/               # tool 调用与回放 artifacts（jsonl）
```

### 模块拆分
- `apps/web`：前端对话网站（Next.js/React 或任意同类）
- `apps/cli`：命令行客户端（Python Typer / Node oclif 等）
- `services/agent-api`：Agent 后端 API（HTTP + SSE/WebSocket）
- `packages/agent-core`：核心编排（session、planner、tool router、memory、policies）
- `packages/skills`：技能包集合（内置 skills + 你自定义 skills）
- `packages/shared`：共享类型/协议（OpenAPI/JSON Schema/TS types）

> 技术栈可替换，但“边界与协议”尽量固定：Web/CLI 都只依赖 `agent-api` 协议；后端依赖 `agent-core` + `skills`。

### 关键数据流
1. Web/CLI 发送 `user_message` 到后端 session
2. 后端 `agent-core` 组装 prompt（系统指令 + 会话历史 + skills 列表/工具 schema + 记忆）
3. LLM 返回 `assistant_text` 与（可选）`tool_use` 请求
4. 后端执行 tool（来自 skills registry），生成标准化 `tool_result`
5. 循环直到完成；将 token/cost/trace 写入存储
6. 通过 streaming 把中间状态推给 Web/CLI

---

## 前端对话网站（Web Chat）

### 体验目标
- **像 ChatGPT 一样顺滑**：流式输出、可中断、可重试、可复制、可导出。
- **透明但不过载**：可折叠显示“工具调用”细节（输入/输出/耗时/错误）。
- **可复现**：每个消息有 `trace_id`，可一键生成 debug bundle（仅本地/管理员）。

### UI 组件拆分（建议）
- **布局**：左侧会话列表 + 中间对话区 + 右侧可折叠 Inspector
- **对话区**：
  - `MessageList`：消息序列（支持虚拟滚动）
  - `Composer`：输入框（支持快捷键、上传附件占位）
  - `StreamingCursor`：流式打字效果与“正在调用工具…”状态条
- **Inspector（可折叠）**：
  - `ToolCallPanel`：tool.name、input、duration、status、summary
  - `TracePanel`：trace_id、token/cost、模型名、latency
  - `SessionConfigPanel`：本会话技能集 allow/deny、预算、策略开关

### 页面与路由（建议）
- `/`：会话列表（按时间/收藏/标签）
- `/chat/[sessionId]`：对话页（主功能）
- `/skills`：技能浏览（启用/禁用、版本、权限范围、测试调用）
- `/settings`：模型/Key/预算/策略（仅本地或登录用户）

### 前端与后端通信
- **发送消息**：`POST /v1/sessions/{id}/messages`
- **流式接收**：
  - 方案 A：SSE `GET /v1/sessions/{id}/events`（简单可靠）
  - 方案 B：WebSocket `wss://.../v1/ws`（双向更灵活）

### SSE 事件（建议 JSON Lines）
SSE 每条 `data:` 携带一段 JSON（前端按 `type` 分发渲染）。

事件示例（仅示意，字段可在 `packages/shared` 固化）：

```json
{ "type": "agent.state", "session_id": "s_123", "trace_id": "t_456", "state": "CALLING_MODEL" }
```

```json
{ "type": "assistant.delta", "session_id": "s_123", "trace_id": "t_456", "delta": "我来帮你…" }
```

```json
{ "type": "tool.call", "session_id": "s_123", "trace_id": "t_456", "tool_name": "time.now", "input": { "tz": "Asia/Shanghai" } }
```

```json
{ "type": "tool.result", "session_id": "s_123", "trace_id": "t_456", "tool_name": "time.now", "result": { "status": "success", "summary": "当前时间已获取", "next_actions": [], "artifacts": [], "data": { "iso": "2026-05-01T21:55:00+08:00" }, "metrics": { "duration_ms": 12 } } }
```

```json
{ "type": "assistant.message", "session_id": "s_123", "trace_id": "t_456", "message": { "id": "m_789", "role": "assistant", "content": "现在是 21:55（UTC+8）。" } }
```

### 前端事件渲染（建议事件类型）
- `assistant.delta`：增量文本
- `assistant.message`：完成的一条 assistant 消息
- `tool.call`：开始调用工具（展示“正在执行…”）
- `tool.result`：工具输出（可折叠）
- `agent.state`：状态机（thinking / acting / waiting / done / error）
- `session.meta`：token/cost/latency 等统计

---

## 命令行（CLI）

### CLI 目标
- 支持脚本化：`agent run "帮我总结这个文件夹"`、`agent chat` 交互模式
- 支持非交互：JSON 输出，便于管道处理
- 支持会话：同一个 `session_id` 复用上下文
- 支持技能控制：`--skills foo,bar` 或 `--deny-skills ...`

### 建议命令
- `agent chat`：进入交互式聊天（流式输出）
- `agent run "<prompt>"`：单次执行（可 `--json`）
- `agent sessions ls|get|rm`
- `agent skills ls|enable|disable|test`
- `agent config set|get`（模型、endpoint、key、预算、默认技能集）

### CLI 输出约定（建议）
- 默认：面向人类（pretty print，带流式增量）
- `--json`：面向机器（最后输出一个 JSON 对象，便于 `jq`/管道）
- `--events-jsonl`：把 SSE/WS 事件原样写到 stdout（JSONL），便于调试/录制

`agent run --json` 最小输出示例：

```json
{
  "session_id": "s_123",
  "trace_id": "t_456",
  "assistant": {
    "content": "我建议拆成 apps/web、services/agent-api、packages/agent-core…"
  },
  "meta": {
    "model": "claude-sonnet-4-6",
    "tool_calls": 3,
    "duration_ms": 8420,
    "token_input": 1024,
    "token_output": 512,
    "cost_usd": 0.0123
  }
}
```

### Session 管理（建议）
- 默认创建 `~/.config/edwinxu-agent/`（或 macOS `~/Library/Application Support/...`）
- `agent chat` 默认复用 `default` session（存一个 `default_session_id`）
- 提供 `--new-session` 强制新建
- 提供 `--session <id>` 指定会话

### CLI 配置与密钥
优先级建议（从高到低）：
1. CLI flag
2. 环境变量（如 `ANTHROPIC_API_KEY`）
3. 用户级配置文件（`~/.config/edwinxu-agent/config.toml`）
4. 项目级配置（`./agent.config.toml`）

---

## Agent 后端（agent-api + agent-core）

### 后端职责
- 管理 session、消息历史、trace
- 统一与 LLM provider 通信（Anthropic/OpenAI/本地模型 可插拔）
- 统一 tool 执行（skills registry）
- 统一策略（预算、权限、速率限制、工具白名单、超时、重试）
- 对外提供 streaming 事件（SSE/WS）

### 状态机（建议）
- `IDLE`：无请求
- `RECEIVING`：收到用户消息
- `PLANNING`：组装上下文/选择技能集（可选）
- `CALLING_MODEL`：请求 LLM
- `TOOL_RUNNING`：执行工具
- `RESPONDING`：输出到客户端
- `DONE`：本轮完成
- `ERROR`：错误（可重试/可回放）

### API 设计（建议 v1）
基础资源：
- `Session`：会话
- `Message`：消息（user/assistant/tool）
- `Event`：流式事件
- `Skill`：技能包元信息
- `Tool`：工具定义（来自 skill）
- `Run`：一次“执行”（可同步也可异步/长任务）

建议 endpoints（示例）：
- `POST /v1/sessions`：创建会话
- `GET /v1/sessions`：列表
- `GET /v1/sessions/{id}`：详情
- `POST /v1/sessions/{id}/messages`：发送用户消息（触发 agent 运行）
- `GET /v1/sessions/{id}/events`：SSE 流
- `POST /v1/runs`：创建一次执行（适合 CLI/自动化）
- `GET /v1/runs/{id}`：查询执行状态与结果
- `POST /v1/runs/{id}:cancel`：取消（尽力而为）
- `GET /v1/skills`：技能列表
- `POST /v1/skills/{name}:enable`、`:disable`
- `POST /v1/tools/{name}:invoke`：手动调用工具（用于调试）

### `POST /v1/sessions/{id}/messages` 请求体（建议）
用于显式控制技能与策略（Web/CLI 都可用）。

```json
{
  "content": "帮我分析一下这个项目应该怎么拆模块",
  "stream": true,
  "skills": {
    "mode": "allowlist",
    "allow": ["planner", "time", "repo", "http"],
    "deny": ["shell.exec"]
  },
  "policy": {
    "max_tool_calls": 12,
    "tool_timeout_ms": 30000,
    "require_confirmation_for": ["write", "exec", "network"]
  },
  "metadata": {
    "client": "web",
    "client_version": "0.1.0"
  }
}
```

### `Run` 模型（长任务/可取消）
当你希望把“对话”与“执行”解耦（尤其是长耗时任务：爬取、批处理、生成文件等），建议引入 `Run`：
- `Run.status`：`queued | running | succeeded | failed | cancelled`
- `Run.result`：最终 assistant message 或产物引用
- `Run.events`：同 SSE 事件流（可回放）

建议规则：
- `POST /v1/runs` 默认创建新 session 或绑定既有 session
- `POST /v1/runs/{id}:cancel` 触发取消信号；tool 执行层应支持超时与取消检查点
- 每个请求可携带 `idempotency_key`（可选），避免 CLI 重试造成重复 run

### 运行时协议：Tool 调用与结果
统一约定 tool result 的结构，避免“黑盒输出”导致 agent 难以恢复。

**ToolResult（标准化）**
- `status`: `success | warning | error`
- `summary`: 一句话总结（给模型与 UI）
- `next_actions`: string[]（建议下一步）
- `artifacts`: string[]（产生的文件/资源路径/ID）
- `data`: object（结构化结果）
- `raw`: string（可选，原始输出，便于 debug）
- `metrics`: { `duration_ms`, `retries`, ... }

**错误恢复契约**
- 每个 error 必须包含：
  - `summary`（根因提示）
  - `next_actions`（安全重试方式）
  - `stop_condition`（什么时候不要再重试，改用替代方案）

---

## Skills/Tools 映射系统（核心设计）

### 设计目标
- Skill 能被“声明式注册”，并映射为一组 Tools（函数调用接口）。
- Skill 有版本、依赖、权限、可见性与测试用例。
- Tools 的输入输出 schema 明确，便于：
  - 模型 tool use
  - 自动生成文档
  - 前端调试面板
  - CLI `skills test`

### 目录与打包形态（建议）
每个 skill 一个目录：
- `packages/skills/<skill-name>/`
  - `skill.yaml`：声明（元数据、工具列表、权限、默认策略）
  - `schemas/`：JSON Schema（inputs/outputs）
  - `impl/`：实现（Python/TS）
  - `tests/`：可选（快照/契约测试）

### `skill.yaml`（建议字段）
- `name`: string
- `version`: semver
- `description`: string
- `tags`: string[]
- `tools`: []
  - `name`: string（全局唯一，建议 `<skill>.<tool>`）
  - `description`: string
  - `input_schema`: path 或 inline JSON schema
  - `output_schema`: path 或 inline JSON schema（用于验证 tool_result.data）
  - `timeout_ms`: number
  - `policy`:
    - `requires_user_confirmation`: boolean（高风险操作）
    - `allowed_paths`: string[]（文件系统范围）
    - `network`: `deny | allowlist`
- `dependencies`: skill 名称列表（可选）

### 一个最小 skill 示例（建议）
`packages/skills/time/skill.yaml`：

```yaml
name: time
version: 0.1.0
description: Time utilities
tags: [utility]
tools:
  - name: time.now
    description: Get current time.
    input_schema: schemas/time.now.input.json
    output_schema: schemas/time.now.output.json
    timeout_ms: 2000
    policy:
      requires_user_confirmation: false
      network: deny
```

`schemas/time.now.input.json`（示意）：

```json
{
  "type": "object",
  "properties": { "tz": { "type": "string", "default": "UTC" } },
  "required": []
}
```

`schemas/time.now.output.json`（示意，校验 `tool_result.data`）：

```json
{
  "type": "object",
  "properties": { "iso": { "type": "string" } },
  "required": ["iso"]
}
```

### Skill Registry（运行时）
后端启动时加载：
- 内置 skills（仓库内）
- 用户自定义 skills（本地目录/远端 git 可选）

Registry 提供：
- `list_skills()`、`list_tools()`、`get_tool_schema(name)`
- `invoke_tool(name, input) -> ToolResult`
- `validate(input/output)`（JSON Schema）

### Skill 选择策略（两种模式）
- **显式模式**：客户端指定 `skills_allowlist`（适合生产/可控）
- **自动模式**：agent 根据问题选择技能（适合探索/个人使用）

自动模式建议实现：
- 先用轻量分类器/规则挑选候选 skills（tags/关键词/路径）
- 再把候选 tools schema 提供给模型调用

### 版本与兼容性（建议）
- Skill 遵循 SemVer：
  - `MAJOR`：tool name 变更、input/output schema 不兼容变更
  - `MINOR`：新增 tool、schema 向后兼容扩展（新增可选字段）
  - `PATCH`：实现修复/性能优化
- Registry 在加载时对 tool name 做全局唯一校验（冲突直接拒绝启动或隔离）
- 允许通过别名机制做迁移（例如 `time.now` -> `clock.now`），但别名需要在 registry 中显式声明（避免模型学到“幽灵工具”）

### Skill 测试（建议）
每个 tool 至少提供一种测试形式：
- **契约测试**：给定输入，输出必须满足 `output_schema`
- **黄金样例**：对纯函数/稳定输出工具使用快照
- **沙盒测试**：涉及文件/网络的 tool 必须可配置为 sandbox（禁用外部副作用）

---

## MCP Server 集成（把外部工具并入 Skills/Tools）

### MCP 是不是“同一个应用”？
一般不建议把 MCP server 和 `agent-api`、Web、CLI 混成同一个进程。

推荐关系：
- **MCP server**：独立进程/独立服务，负责“提供工具/资源/提示模板”
- **`services/agent-api`**：作为 **MCP client + 工具网关**，把 MCP tools 映射成我们统一的 tools，并产出 `ToolResult`
- **Web/CLI**：完全不直接连 MCP server，只连 `agent-api`

### MCP 核心概念（术语对齐）
从系统视角，MCP 可以理解为“AI 应用的插件协议”，把外部能力标准化成三类对象：
- **Tools**：可执行动作（带输入 schema 的函数式调用）
- **Resources**：可读取的上下文（通常以 URI 表达；默认只读，可选订阅）
- **Prompts**：可复用、参数化的提示模板（提升一致性与可控性）

在本项目中：
- `agent-api` 扮演 **Host/Client** 的角色（连接与聚合能力）
- 每个 MCP server 扮演 **Server**（暴露 tools/resources/prompts）

### 设计规范（把 `mcp.md` 的规范落到本项目）
- **不要把 MCP 当“万能 RPC”**：复杂编排留在 `agent-core`/业务服务，MCP server 提供可治理、可审计的“原子能力”。
- **稳定优先**：已发布 tool 尽量保持参数/返回兼容；新增字段尽量可选且有默认值（向后兼容）。
- **显式约束**：对输入输出做强约束（类型/枚举/范围/长度/pattern），避免模型误用造成风险或爆量。
- **最小权限**：避免“任意 SQL/任意 HTTP/任意文件读取”这种万能入口；拆成受控的细粒度工具。
- **可审计**：每次调用必须能关联 `trace_id`/`request_id`、调用者身份、参数摘要（脱敏）、结果摘要（脱敏）、耗时。

### 命名规范（建议与 `mcp.md` 对齐）
- **server 名称**：`kebab-case`，体现域/所有者（如 `ctrip-knowledge`）
- **tool 名称**：推荐 `domain.action`（如 `knowledge.search`、`metrics.query`）
- **resource URI**：语义化可路由（如 `kb://doc/{id}`）
- **prompt 名称**：`domain.task`（如 `release.checklist`）

### 传输选择：本地 stdio vs 远程 Streamable HTTP
- **本地开发/个人使用**：优先 **stdio**（`agent-api` 启动子进程并通过 stdio 通信）
- **部署/远程访问**：优先 **Streamable HTTP**（MCP server 独立部署，`agent-api` 通过 HTTP 连接）

### 推荐目录结构（可放多个 MCP server）

```text
services/
  mcp-servers/
    repo-tools/            # 示例：提供 repo 搜索、索引、读取等工具
    browser-tools/         # 示例：提供抓取、提取、转 markdown 等工具
```

### `agent-api` 中的 MCP servers 配置（建议）
在 `agent-api` 的配置里声明 MCP servers（示意）：

```json
{
  "mcp_servers": [
    {
      "name": "repo",
      "transport": "stdio",
      "command": "node",
      "args": ["services/mcp-servers/repo-tools/dist/index.js"],
      "env": { "REPO_ROOT": "/path/to/workspace" },
      "timeout_ms": 30000
    },
    {
      "name": "browser",
      "transport": "http",
      "url": "https://mcp.example.com",
      "timeout_ms": 30000
    }
  ]
}
```

### MCP tools 如何映射进本项目的 Tools
建议做命名空间隔离，避免冲突：
- MCP tool `search`（来自 server `repo`）映射为：`mcp.repo.search`
- MCP tool `readFile`（来自 server `repo`）映射为：`mcp.repo.readFile`

映射后的 tool 仍需满足本项目的约定：
- 有明确的 `input_schema`
- 返回被包装为统一的 `ToolResult`（供 UI/模型做恢复与下一步）
- 记录 `trace_id`、耗时、错误（Inspector 可展示）

### Tool 设计规范（强烈建议照此做）
- **粒度**：一次调用完成一个明确目标，避免“万能工具”。
- **大操作拆分**：优先拆成 `plan`（生成方案）+ `execute`（执行）+ `status`（查进度/结果）。
- **输入 schema**：
  - 必填尽量少；可选项给默认值
  - 字符串加 `minLength/maxLength/pattern`
  - 枚举加 `enum`
  - 分页/时间范围加上限，避免爆量
- **输出结构**：
  - 避免“只有自然语言一大段”作为唯一输出
  - 优先：结构化 `data` + `meta`（来源/分页/耗时）+ `warnings`（如有）
- **幂等与重试**：写操作尽量支持 `idempotencyKey`；明确哪些错误可重试、是否建议退避。

### 错误模型（建议）
MCP server 与 `agent-api` connector 都应做错误分类与脱敏，建议错误码集合：
`INVALID_ARGUMENT` / `UNAUTHORIZED` / `FORBIDDEN` / `NOT_FOUND` / `RATE_LIMITED` / `UPSTREAM_ERROR` / `INTERNAL`

### 可观测性（建议）
- **日志**：身份、tool 名、参数摘要（脱敏）、响应摘要（脱敏）、耗时、错误码
- **指标**：QPS、P95/P99、错误率、上游失败率、限流命中率
- **追踪**：贯穿 `trace_id`/`request_id`，支持跨服务定位

### 安全与合规（建议）
- **身份与鉴权**：明确调用者身份（用户/服务）；HTTP 场景走 token/签名（按你体系落地）
- **最小权限与分级**：按 tool/resource 粒度授权；区分只读/写/高危
- **数据保护**：传输加密；日志脱敏；敏感字段白名单输出
- **提示注入防护**：对 resources/上游返回做“数据/指令分离”，不要把外部文本当系统指令执行
- **审计**：写操作、导出操作必须审计；高危可二次确认/审批（由 Host/业务侧实现）

### 怎么搞（实现步骤）
1. **实现 MCP server**：schema-first 定义 tools/resources（Node/TS 推荐 `@modelcontextprotocol/sdk` + Zod）
2. **在 `agent-api` 加 MCP connector**：
   - 连接/启动 MCP server（stdio 或 Streamable HTTP）
   - 拉取工具清单（工具名、描述、输入 schema）
   - 注册到 Skills/Tools registry（带 `mcp.<server>.` 前缀）
3. **统一执行链**：
   - `invoke_tool()` 发现目标 tool 来自 MCP，则走 connector
   - 将 MCP 输出转换为本项目的 `ToolResult`，并做输出 schema 校验（如果你为该 tool 定义了 output schema）
4. **安全与隔离**：
   - MCP server 默认低权限运行（最小 env、最小文件访问范围）
   - `agent-api` 仍做二次策略校验（deny by default、allowlist、超时、速率限制）

### MCP Server 的开发流程（建议）
对齐 `mcp.md` 的推荐顺序：
- **需求澄清**：能力边界、风险评估、成功标准
- **先设计再编码**：tools/resources/prompts 列表 + schema + 错误码 + 权限矩阵 + 限流/配额
- **实现顺序**：骨架（鉴权/日志）→ 只读能力 → 写能力（幂等/审计/确认）
- **测试分层**：单测（schema/权限/脱敏）+ 集成（mock/sandbox）+ 契约（golden）+ 安全（注入/越权/超大输入）
- **发布与回滚**：灰度、可回滚、变更记录（tools/prompts 变更都要记录）

### 常见反模式（避坑）
- 一个 tool = 万能网关（如 `http.request(...)`、`sql.query(...)` 不设约束）
- 不做 schema 或 schema 太宽（后期全靠补丁）
- 返回全是自然语言（不可解析、不可回归测试）
- 把 token/PII/内部地址写日志
- 不做版本化（导致下游集成频繁破坏）

---

## 记忆与上下文（Memory）

### Memory 类型（建议分层）
- **短期**：当前 session 的消息历史
- **中期**：session summary（每 N 轮摘要一次）
- **长期**：用户偏好、常用项目、常用技能集（可选）

### 载入策略
- 默认只注入：系统指令 + 最近 K 条消息 + session summary + 允许的 tools
- 避免把全部历史塞进 prompt（成本与噪音）

---

## 安全与权限（必须先定规则）

### 风险分类
高风险 tool（需要确认/限制）示例：
- 写文件、删除文件、执行 shell、发网络请求、调用第三方 API

### 建议策略
- tool 分级：`read-only` / `write` / `exec` / `network`
- 允许路径与工作目录沙盒
- 网络默认 deny，按 allowlist 开放
- 每次 tool 调用带 `trace_id` 与审计日志

---

## 存储、日志与可观测性

### 最小可用（Phase 1）
- SQLite（sessions/messages/tool_calls/traces）
- 文件系统存 trace artifact（jsonl）
- 结构化日志（JSON），包含 `trace_id`、`session_id`

### 建议最小数据库表（概念模型）
- `sessions(id, created_at, title, pinned, tags_json, config_json)`
- `messages(id, session_id, role, content_json, created_at)`
- `tool_calls(id, session_id, trace_id, tool_name, input_json, result_json, started_at, finished_at, status)`
- `runs(id, session_id, trace_id, status, created_at, finished_at, error_json, result_message_id)`

### Trace artifacts（建议）
`artifacts/traces/<trace_id>.jsonl`：
- 每行一个事件（与 SSE 事件同结构），用于回放与 debug bundle

### 可选增强（Phase 2）
- OpenTelemetry traces + 可视化
- 向量索引（用于检索记忆/文档）
- 任务队列（长任务异步）

---

## 迭代路线（建议）

### Phase 1：跑通端到端（1-2 天）
- `agent-api`：session + message + SSE streaming
- `agent-core`：最小工具循环（tool_use -> tool_result -> continue）
- 2-3 个内置 skills：`echo`、`time`、`http_get`（可选）/`file_read`（谨慎）
- Web chat：发送消息 + 流式展示 + 工具折叠面板
- CLI：`agent chat` + `agent run`

### Phase 2：技能生态（2-5 天）
- `skills`：声明式注册、schema 校验、`skills test`
- 自动技能选择（tag/规则）
- 基础记忆（session summary）

### Phase 3：生产化（持续）
- 权限更细、审计更强、可插拔模型与成本控制
- 异步任务与队列、并发限制、重试与断点续跑

---

## 你需要做的技术选择（我建议的默认值）

### 需要几个应用？
最小可用可以 **1 个应用** 跑通（后端同时提供 API + 简易网页，CLI 调用后端 API），但为了可维护与体验，推荐拆成 **3 个应用**：
- `apps/web`：对话网站（独立前端工程）
- `services/agent-api`：Agent 后端（统一模型调用、tool 执行、session/run、SSE/WS）
- `apps/cli`：命令行（脚本化入口，调用 agent-api）

这样拆分的好处：
- Web/CLI 共享同一套后端协议与技能系统，不会出现“两个 agent 逻辑”
- 后端可以独立做权限、审计、预算、工具沙盒与存储
- 前端可以专注对话体验与调试面板，不被后端实现细节绑死

为了尽快落地，推荐组合：
- Web：TypeScript（Next.js + SSE）
- 后端：Python（FastAPI + SSE，或 WebSocket）
- 核心：Python（便于快速做工具与文件/系统集成）
- CLI：优先 Python（Typer）；如果你更偏 Node，也可用 TypeScript（Node CLI）——关键是都只调用 `agent-api`

如果你更偏 Node/TS，也可以把 `agent-core` 与 `agent-api` 改成 TS（Fastify/Express + WS/SSE），文档里的协议仍然适用。

---

## 开发与部署工作流（建议）

### 本地开发（推荐）
- **后端**：`services/agent-api` 启动在 `http://localhost:8080`
- **前端**：`apps/web` 启动在 `http://localhost:3000`，通过环境变量指向后端
- **CLI**：默认指向 `http://localhost:8080`，可通过 config/flag 覆盖

建议环境变量（示意）：
- `AGENT_API_BASE_URL`：后端地址（Web/CLI 都可用）
- `ANTHROPIC_API_KEY`：模型密钥（仅后端需要；前端不要持有真实 key）
- `AGENT_DB_URL`：SQLite 路径或数据库 URL
- `AGENT_TRACE_DIR`：trace artifacts 输出目录

### 部署形态（先简单后增强）
- Phase 1：单容器/单进程（agent-api 同时提供 SSE）
- Phase 2：拆分（web 静态站点 + agent-api 服务），接入反向代理（Nginx/Caddy）

### 反向代理与流式注意事项
- SSE 需要关闭代理缓存与压缩干扰：
  - `Cache-Control: no-cache`
  - 代理层禁用 buffer（避免事件积压）
- WebSocket 需要正确的 upgrade 头与超时配置

### 安全基线（上线前必须满足）
- 前端不直接接触模型密钥；所有模型调用只在后端发生
- 后端对高风险 tools 默认禁用或需要确认（见“安全与权限”）
- 日志与 trace 不记录敏感信息（key、token、cookie、私密文件内容）

