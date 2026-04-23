import json
import logging
import time

logger = logging.getLogger(__name__)

# Claude tool schema for web_search
WEB_SEARCH_TOOL: dict = {
    "name": "web_search",
    "description": (
        "Search the web for current information. Use this to find job postings, "
        "university course catalogs, industry reports, and skill demand data in Costa Rica. "
        "Prefer Spanish queries for Costa Rica-specific content. "
        "Results are filtered to prioritize Costa Rica (cr-es region)."
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
    Retries up to 2 times on transient failures with 2-second backoff.
    """
    max_retries = 2
    for attempt in range(max_retries + 1):
        try:
            from duckduckgo_search import DDGS
            logger.debug(
                f"[web_search] query='{query}' max_results={max_results} "
                f"attempt={attempt + 1}/{max_retries + 1}"
            )
            with DDGS() as ddgs:
                results = list(ddgs.text(query, max_results=max_results, region="cr-es"))
            logger.debug(f"[web_search] returned {len(results)} results")
            return json.dumps(results, ensure_ascii=False, indent=2)
        except Exception as e:
            if attempt < max_retries:
                logger.warning(
                    f"[web_search] attempt {attempt + 1} failed: {e}. "
                    f"Retrying in 2s..."
                )
                time.sleep(2)
            else:
                logger.warning(f"[web_search] all {max_retries + 1} attempts failed: {e}")
                return json.dumps({"error": str(e), "error_code": "search_failed", "query": query})
