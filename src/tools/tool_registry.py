from typing import Callable
from src.tools.web_search import web_search, WEB_SEARCH_TOOL
from src.tools.web_fetch import web_fetch, WEB_FETCH_TOOL

# Maps tool name -> callable implementation
TOOL_REGISTRY: dict[str, Callable] = {
    "web_search": web_search,
    "web_fetch": web_fetch,
}

# Maps tool name -> Claude API tool schema
TOOL_SCHEMAS: dict[str, dict] = {
    "web_search": WEB_SEARCH_TOOL,
    "web_fetch": WEB_FETCH_TOOL,
}

# Convenience list for agents that use both research tools
RESEARCH_TOOLS: list[dict] = [WEB_SEARCH_TOOL, WEB_FETCH_TOOL]
