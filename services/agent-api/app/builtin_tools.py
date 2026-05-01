from __future__ import annotations

import os
import re
import time
from datetime import datetime
from html import unescape
from typing import Any
from zoneinfo import ZoneInfo

import httpx


def time_now(inp: dict[str, Any]) -> dict[str, Any]:
    tz = inp.get("tz") or "UTC"
    dt = datetime.now(ZoneInfo(tz))
    return {"iso": dt.isoformat()}


def echo_say(inp: dict[str, Any]) -> dict[str, Any]:
    return {"text": str(inp.get("text") or "")}


def _clamp_int(x: Any, lo: int, hi: int, default: int) -> int:
    try:
        v = int(x)
    except Exception:  # noqa: BLE001
        return default
    return max(lo, min(hi, v))


def _normalize_query(query: str, site: str | None = None) -> str:
    q = (query or "").strip()
    if site:
        s = str(site).strip()
        if s:
            q = f"site:{s} {q}".strip()
    return q


def _search_serper(query: str, top_k: int) -> dict[str, Any]:
    api_key = os.getenv("SERPER_API_KEY") or ""
    if not api_key:
        raise ValueError("SERPER_API_KEY is required for serper provider")

    url = "https://google.serper.dev/search"
    headers = {"X-API-KEY": api_key, "Content-Type": "application/json"}
    payload = {"q": query, "num": top_k}

    with httpx.Client(timeout=15.0, headers=headers) as client:
        r = client.post(url, json=payload)
        r.raise_for_status()
        j = r.json()

    results: list[dict[str, Any]] = []
    for i, item in enumerate((j.get("organic") or [])[:top_k], start=1):
        results.append(
            {
                "rank": i,
                "title": str(item.get("title") or ""),
                "url": str(item.get("link") or ""),
                "snippet": str(item.get("snippet") or ""),
            }
        )
    return {"provider": "serper", "query": query, "results": results}


def _search_duckduckgo_html(query: str, top_k: int) -> dict[str, Any]:
    # Lightweight HTML parse without external deps.
    url = "https://duckduckgo.com/html/"
    params = {"q": query}
    headers = {
        "User-Agent": "edwinxu-agent/0.1 (+https://github.com/Edwin-Xu/edwinxu-agent)",
        "Accept": "text/html",
    }

    with httpx.Client(timeout=15.0, headers=headers, follow_redirects=True) as client:
        r = client.get(url, params=params)
        r.raise_for_status()
        html = r.text

    # Extract titles/urls. Snippets are best-effort.
    # Title anchor often: <a rel="nofollow" class="result__a" href="...">Title</a>
    link_re = re.compile(r'<a[^>]*class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', re.IGNORECASE | re.DOTALL)
    snip_re = re.compile(r'<a[^>]*class="result__snippet"[^>]*>(.*?)</a>|<div[^>]*class="result__snippet"[^>]*>(.*?)</div>', re.IGNORECASE | re.DOTALL)

    links = link_re.findall(html)
    snippets = snip_re.findall(html)

    def clean_text(s: str) -> str:
        t = re.sub(r"<[^>]+>", "", s or "")
        t = unescape(t)
        return re.sub(r"\s+", " ", t).strip()

    results: list[dict[str, Any]] = []
    for i, (href, title_html) in enumerate(links[:top_k], start=1):
        sn = ""
        if i - 1 < len(snippets):
            a, b = snippets[i - 1]
            sn = clean_text(a or b or "")
        results.append({"rank": i, "title": clean_text(title_html), "url": unescape(href), "snippet": sn})

    return {"provider": "duckduckgo", "query": query, "results": results}


def web_search(inp: dict[str, Any]) -> dict[str, Any]:
    query = str(inp.get("query") or "")
    site = inp.get("site")
    top_k = _clamp_int(inp.get("top_k"), 1, 10, 5)

    q = _normalize_query(query, site=str(site) if site else None)
    if not q:
        return {"provider": "none", "query": "", "results": [], "error": "query is required"}

    provider = (os.getenv("WEB_SEARCH_PROVIDER") or "duckduckgo").strip().lower()
    started = int(time.time() * 1000)
    try:
        if provider == "serper":
            out = _search_serper(q, top_k)
        else:
            out = _search_duckduckgo_html(q, top_k)
    except Exception as e:  # noqa: BLE001
        # Fallback to duckduckgo when serper isn't configured.
        if provider == "serper":
            out = _search_duckduckgo_html(q, top_k)
            out["provider"] = "duckduckgo"
            out["warning"] = f"serper failed, fallback to duckduckgo: {e}"
        else:
            raise

    out["fetched_at_ms"] = int(time.time() * 1000)
    out["duration_ms"] = out["fetched_at_ms"] - started
    return out


def builtin_handlers() -> dict[str, callable]:
    return {
        "time.now": time_now,
        "echo.say": echo_say,
        "web.search": web_search,
    }

