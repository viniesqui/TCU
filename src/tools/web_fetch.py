import logging

logger = logging.getLogger(__name__)

# Claude tool schema for web_fetch
WEB_FETCH_TOOL: dict = {
    "name": "web_fetch",
    "description": (
        "Fetch and read the text content of a URL. Use after web_search to read "
        "the full content of a promising page such as a job posting, university "
        "catalog, or industry report."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "The URL to fetch."
            },
            "max_chars": {
                "type": "integer",
                "description": "Maximum characters to return. Default 4000.",
                "default": 4000
            }
        },
        "required": ["url"]
    }
}


def web_fetch(url: str, max_chars: int = 4000) -> str:
    """
    Fetch a URL and return its plain-text content (HTML stripped).
    Returns truncated text up to max_chars.
    """
    try:
        import httpx
        from bs4 import BeautifulSoup

        logger.debug(f"[web_fetch] fetching url={url}")
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
        }
        response = httpx.get(url, headers=headers, timeout=15, follow_redirects=True)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "lxml")

        # Remove script and style tags
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()

        text = soup.get_text(separator="\n", strip=True)

        # Collapse blank lines
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        clean_text = "\n".join(lines)

        truncated = clean_text[:max_chars]
        if len(clean_text) > max_chars:
            truncated += f"\n\n[... content truncated at {max_chars} chars ...]"

        logger.debug(f"[web_fetch] returned {len(truncated)} chars from {url}")
        return truncated

    except Exception as e:
        logger.warning(f"[web_fetch] failed for {url}: {e}")
        return f"ERROR fetching {url}: {e}"
