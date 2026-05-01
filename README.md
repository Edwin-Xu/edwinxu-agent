# edwinxu-agent

一个按 `DESIGN.md` 实现的 Agent 应用（Web 对话 + CLI + Agent 后端 + Skills/Tools + 可选 MCP 集成）。

## 目录
- `services/agent-api/`：Agent 后端（FastAPI + SSE）
- `apps/web/`：前端对话网站（Next.js）
- `apps/cli/`：命令行客户端（Typer）
- `packages/skills/`：内置 skills（`time` / `echo`）

## 本地运行（MVP）

### 一键启动（推荐）
```bash
./scripts/bootstrap.sh
./scripts/dev-all.sh
```

### 1）后端
```bash
cd services/agent-api
# 使用 conda 的 p310 环境
conda activate p310
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload --port 8080
```

### 2）前端
```bash
cd apps/web
npm install
npm run dev
```

打开 `http://localhost:3000`。
（默认脚本会尝试用 `http://localhost:80` 启动；若端口权限不足可用 `PORT=3000 ./scripts/dev-web.sh`）

### 3）CLI
```bash
cd apps/cli
# 使用 conda 的 p310 环境
conda activate p310
pip install -r requirements.txt
# 安装命令：eag
pip install -e .
eag --help
eag run "你好" --api http://localhost:8080
```

## 模型配置（可选）
如果你设置了 `ANTHROPIC_API_KEY`（放在 `services/agent-api/.env`），后端会启用 Anthropic；否则走 mock provider（依然可用于联调与 UI 验证）。

