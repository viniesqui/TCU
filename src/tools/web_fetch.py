import json
import logging
import time

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
    Returns truncated text up to max_chars, or a JSON error object on failure.
    """
    try:
        import ssl
        import httpx
        from bs4 import BeautifulSoup

        logger.debug(f"[web_fetch] fetching url={url}")
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
        }

        try:
            response = httpx.get(url, headers=headers, timeout=15, follow_redirects=True)
        except httpx.TimeoutException:
            logger.warning(f"[web_fetch] timeout for {url}")
            return json.dumps({
                "error": "La solicitud excedió el tiempo límite (15s)",
                "error_code": "timeout",
                "url": url,
                "suggestion": "Intenta buscar el contenido en otro sitio o usa una búsqueda más específica."
            })
        except ssl.SSLError as e:
            logger.warning(f"[web_fetch] SSL error for {url}: {e}")
            return json.dumps({
                "error": f"Error de certificado SSL: {e}",
                "error_code": "ssl",
                "url": url,
                "suggestion": "El sitio tiene un certificado inválido. Busca el mismo contenido en otro dominio."
            })
        except Exception as e:
            logger.warning(f"[web_fetch] connection error for {url}: {e}")
            return json.dumps({
                "error": f"Error de conexión: {e}",
                "error_code": "connection",
                "url": url,
                "suggestion": "Verifica la URL o intenta con un sitio alternativo."
            })

        # Handle specific HTTP status codes
        if response.status_code == 403:
            logger.warning(f"[web_fetch] 403 Forbidden: {url}")
            return json.dumps({
                "error": "Acceso denegado (HTTP 403) — el sitio bloquea scraping automático",
                "error_code": 403,
                "url": url,
                "suggestion": "Intenta buscar el mismo contenido en Google Cache o en otro sitio similar."
            })

        if response.status_code == 429:
            logger.warning(f"[web_fetch] 429 Too Many Requests: {url}, retrying after 3s")
            time.sleep(3)
            try:
                response = httpx.get(url, headers=headers, timeout=15, follow_redirects=True)
                if response.status_code == 429:
                    return json.dumps({
                        "error": "Demasiadas solicitudes (HTTP 429) — límite de tasa alcanzado",
                        "error_code": 429,
                        "url": url,
                        "suggestion": "Espera un momento y busca el contenido en otra fuente."
                    })
            except Exception:
                return json.dumps({
                    "error": "Demasiadas solicitudes (HTTP 429) y reintento fallido",
                    "error_code": 429,
                    "url": url,
                    "suggestion": "Busca el contenido en otra fuente."
                })

        if response.status_code == 404:
            logger.warning(f"[web_fetch] 404 Not Found: {url}")
            return json.dumps({
                "error": "Página no encontrada (HTTP 404)",
                "error_code": 404,
                "url": url,
                "suggestion": "La URL no existe. Busca el recurso con una consulta web diferente."
            })

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            logger.warning(f"[web_fetch] HTTP error {e.response.status_code} for {url}")
            return json.dumps({
                "error": f"Error HTTP {e.response.status_code}",
                "error_code": e.response.status_code,
                "url": url,
                "suggestion": "Intenta con una URL alternativa."
            })

        soup = BeautifulSoup(response.text, "lxml")

        # Remove script, style, nav, footer, header tags
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()

        text = soup.get_text(separator="\n", strip=True)

        # Collapse blank lines
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        clean_text = "\n".join(lines)

        truncated = clean_text[:max_chars]
        if len(clean_text) > max_chars:
            truncated += f"\n\n[... contenido truncado en {max_chars} caracteres ...]"

        logger.debug(f"[web_fetch] returned {len(truncated)} chars from {url}")
        return truncated

    except Exception as e:
        logger.warning(f"[web_fetch] unexpected error for {url}: {e}")
        return json.dumps({
            "error": f"Error inesperado: {e}",
            "error_code": "unknown",
            "url": url,
            "suggestion": "Intenta con una URL diferente."
        })
