# app/services/agent/tools_tavily.py
from __future__ import annotations
from typing import Dict, Any, Optional
from pydantic import BaseModel
from langchain_core.tools import tool
from app.core.config import settings
from tavily import TavilyClient  # pip install tavily-python

class TavilyInput(BaseModel):
    query: str
    k: int = 3

def make_tavily_tools():
    if not settings.ENABLE_WEB_SEARCH or settings.WEBCTX_PROVIDER != "tavily" or not settings.TAVILY_API_KEY:
        return []
    client = TavilyClient(api_key=settings.TAVILY_API_KEY)

    @tool("web.tavily_search", args_schema=TavilyInput)
    def tavily_search(query: str, k: int = 3) -> Dict[str, Any]:
        res = client.search(query=query, max_results=k)
        return res

    return [tavily_search]
