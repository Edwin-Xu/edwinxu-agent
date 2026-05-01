import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";
const FAKE_STOCKS = [
    {
        code: "AAPL",
        name: "Apple Inc.",
        shortName: "Apple",
        exchange: "NASDAQ",
        currency: "USD",
        sector: "Technology",
        price: 196.12,
        changePct: 0.43,
        marketCap: 3.12e12,
        updatedAt: new Date().toISOString(),
    },
    {
        code: "TSLA",
        name: "Tesla, Inc.",
        shortName: "Tesla",
        exchange: "NASDAQ",
        currency: "USD",
        sector: "Automotive",
        price: 182.55,
        changePct: -1.21,
        marketCap: 5.8e11,
        updatedAt: new Date().toISOString(),
    },
    {
        code: "600519",
        name: "贵州茅台股份有限公司",
        shortName: "茅台",
        exchange: "SSE",
        currency: "CNY",
        sector: "Consumer Staples",
        price: 1688.0,
        changePct: 0.18,
        marketCap: 2.12e12,
        updatedAt: new Date().toISOString(),
    },
    {
        code: "0700",
        name: "腾讯控股有限公司",
        shortName: "腾讯",
        exchange: "HKEX",
        currency: "HKD",
        sector: "Communication Services",
        price: 365.4,
        changePct: 0.92,
        marketCap: 3.4e12,
        updatedAt: new Date().toISOString(),
    },
];
function normalize(s) {
    return s.trim().toLowerCase();
}
function lookup(query, market) {
    const q = normalize(query);
    const m = market ? normalize(market) : null;
    const candidates = FAKE_STOCKS.filter((x) => {
        if (m && normalize(x.exchange) !== m)
            return false;
        return normalize(x.code) === q || normalize(x.shortName) === q || normalize(x.name) === q;
    });
    if (candidates.length)
        return candidates[0];
    // Fuzzy: contains match by name/shortName/code
    const fuzzy = FAKE_STOCKS.find((x) => {
        if (m && normalize(x.exchange) !== m)
            return false;
        return normalize(x.code).includes(q) || normalize(x.shortName).includes(q) || normalize(x.name).includes(q);
    });
    return fuzzy ?? null;
}
const server = new McpServer({ name: "stocks", version: "0.1.0" });
server.registerTool("stocks.lookup", {
    description: "Lookup stock basic info by code or short name (fake data).",
    inputSchema: {
        query: z.string().min(1).describe("Stock code or short name, e.g. AAPL / 茅台 / 腾讯"),
        market: z.string().optional().describe("Optional exchange/market filter, e.g. NASDAQ/SSE/HKEX"),
    },
}, async ({ query, market }) => {
    const item = lookup(query, market ?? null);
    if (!item) {
        return {
            content: [
                {
                    type: "text",
                    text: `Not found for query=${query}${market ? ` market=${market}` : ""}. Try AAPL/TSLA/600519/茅台/0700/腾讯.`,
                },
            ],
        };
    }
    const data = {
        ...item,
        market,
    };
    return {
        content: [{ type: "text", text: JSON.stringify({ data, meta: { source: "fake", ts: new Date().toISOString() } }, null, 2) }],
    };
});
async function main() {
    const transport = new StdioServerTransport();
    await server.connect(transport);
}
main().catch((err) => {
    console.error(err);
    process.exit(1);
});
