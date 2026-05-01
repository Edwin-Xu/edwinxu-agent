# MCP Stocks Server (Fake Data)

一个示例 MCP server：提供股票基本信息查询工具（数据为内置构造，非真实行情）。

## Tool
- `stocks.lookup`
  - 输入：`query`（股票代码或简称），可选 `market`
  - 输出：结构化基本信息（代码、简称、交易所、币种、行业、价格等）

## 本地运行（stdio）
```bash
cd services/mcp-servers/stocks
npm install
npm run build
npm run start
```

> 注意：stdio MCP server 不要用 `console.log` 输出到 stdout；请用 `console.error` 打日志。

