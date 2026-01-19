# app/services/webctx.py
from __future__ import annotations
from typing import Dict, Any, List
import requests
from app.core.config import settings

def _tavily_search(query: str, n: int = 5) -> List[Dict[str, str]]:
    url = "https://api.tavily.com/search"
    headers = {"Content-Type":"application/json"}
    payload = {
        "api_key": settings.TAVILY_API_KEY,
        "query": query,
        "search_depth": "basic",
        "max_results": n,
        "include_answer": False
    }
    r = requests.post(url, json=payload, headers=headers, timeout=30)
    r.raise_for_status()
    data = r.json()
    results = data.get("results", [])
    out = []
    for x in results[:n]:
        out.append({
            "title": x.get("title") or x.get("url") or "reference",
            "summary": (x.get("content") or x.get("snippet") or "")[:240]
        })
    return out

def fetch_web_context_if_needed(scenario: dict, enabled: bool) -> Dict[str, Any] | None:
    if not enabled: return None
    if settings.WEBCTX_PROVIDER == "none": return None
    # 커스텀 시나리오에서만
    if not scenario.get("is_custom"): return None
    if settings.WEBCTX_PROVIDER == "tavily" and settings.TAVILY_API_KEY:
        q = (scenario.get("title") or scenario.get("purpose")
             or "voice phishing tactics")
        try:
            items = _tavily_search(q, n=5)
            return {"items": items}
        except Exception:
            return None
    return None
