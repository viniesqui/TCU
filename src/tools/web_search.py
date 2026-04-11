import json
import logging

logger = logging.getLogger(__name__)

# Claude tool schema for web_search
WEB_SEARCH_TOOL: dict = {
    "name": "web_search",
    "description": (
        "Search the web for current information. Use this to find job postings, "
        "university course catalogs, industry reports, and skill demand data in Costa Rica. "
        "Prefer Spanish queries for Costa Rica-specific content."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query. Use Spanish for Costa Rica-specific searches."
            },
            "max_results": {
                "type": "integer",
                "description": "Number of results to return (1-10). Default 5.",
                "default": 5
            }
        },
        "required": ["query"]
    }
}


def web_search(query: str, max_results: int = 5) -> str:
    """
    Search the web using DuckDuckGo. Returns JSON string with results.
    Each result has: title, href, body.
    """
    try:
        from duckduckgo_search import DDGS
        logger.debug(f"[web_search] query='{query}' max_results={max_results}")
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
        logger.debug(f"[web_search] returned {len(results)} results")
        return json.dumps(results, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(f"[web_search] failed: {e}")
        return json.dumps({"error": str(e), "query": query})
