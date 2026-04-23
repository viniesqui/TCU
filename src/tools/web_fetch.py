import ipaddress
import json
import logging
import time
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

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
                "description": "Maximum characters to return. Default 4000, maximum 8000.",
                "default": 4000
            }
        },
        "required": ["url"]
    }
}

# Hard upper bound — the agent cannot exceed this regardless of what it requests.
_MAX_CHARS_HARD_LIMIT = 8000

_ALLOWED_SCHEMES = {"http", "https"}

# RFC 1918 + loopback + link-local (AWS IMDS lives at 169.254.169.254)
_PRIVATE_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
]

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}


def _validate_url(url: str) -> str | None:
    """
    Return an error message string if the URL is disallowed, None if it is safe.

    Blocks non-http/https schemes and literal private/loopback IP addresses.
    Hostnames are allowed through — DNS-based SSRF is out of scope for a CLI tool.
    """
    try:
        parsed = urlparse(url)
    except Exception:
        return "URL con formato inválido"

    if parsed.scheme not in _ALLOWED_SCHEMES:
        return f"Esquema '{parsed.scheme}' no permitido. Solo http y https son aceptados."

    hostname = parsed.hostname or ""
    if not hostname:
        return "URL sin hostname"

    try:
        addr = ipaddress.ip_address(hostname)
        if any(addr in net for net in _PRIVATE_NETWORKS):
            return f"Acceso a dirección IP privada/interna '{hostname}' no permitido."
    except ValueError:
        pass  # hostname is a domain name, not a bare IP — allow it

    return None


def web_fetch(url: str, max_chars: int = 4000) -> str:
    """
    Fetch a URL and return its plain-text content (HTML stripped).
    Returns truncated text up to max_chars, or a JSON error object on failure.
    """
    # Enforce the hard cap regardless of what the agent requested
    max_chars = min(max_chars, _MAX_CHARS_HARD_LIMIT)

    # SSRF guard: reject private IPs and non-http schemes before touching the network
    url_error = _validate_url(url)
    if url_error:
        logger.warning(f"[web_fetch] Blocked URL '{url}': {url_error}")
        return json.dumps({
            "error": url_error,
            "error_code": "invalid_url",
            "url": url,
            "suggestion": "Usa una URL pública válida con http o https."
        })

    logger.debug(f"[web_fetch] fetching url={url}")

    try:
        response = httpx.get(url, headers=_HEADERS, timeout=15, follow_redirects=True)
    except httpx.TimeoutException:
        logger.warning(f"[web_fetch] timeout for {url}")
        return json.dumps({
            "error": "La solicitud excedió el tiempo límite (15s)",
            "error_code": "timeout",
            "url": url,
            "suggestion": "Intenta buscar el contenido en otro sitio o usa una búsqueda más específica."
        })
    except httpx.ConnectError as e:
        err_str = str(e).lower()
        if "ssl" in err_str or "certificate" in err_str or "tls" in err_str:
            logger.warning(f"[web_fetch] SSL error for {url}: {e}")
            return json.dumps({
                "error": f"Error de certificado SSL: {e}",
                "error_code": "ssl",
                "url": url,
                "suggestion": "El sitio tiene un certificado inválido. Busca el mismo contenido en otro dominio."
            })
        logger.warning(f"[web_fetch] connection error for {url}: {e}")
        return json.dumps({
            "error": f"Error de conexión: {e}",
            "error_code": "connection",
            "url": url,
            "suggestion": "Verifica la URL o intenta con un sitio alternativo."
        })
    except Exception as e:
        logger.warning(f"[web_fetch] unexpected network error for {url}: {e}")
        return json.dumps({
            "error": f"Error de conexión inesperado: {e}",
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
            response = httpx.get(url, headers=_HEADERS, timeout=15, follow_redirects=True)
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

    # Reject binary content types that BeautifulSoup cannot meaningfully parse
    content_type = response.headers.get("content-type", "").lower()
    if any(ct in content_type for ct in ("application/pdf", "application/octet", "image/", "video/", "audio/")):
        logger.warning(f"[web_fetch] binary content-type '{content_type}' for {url}")
        return json.dumps({
            "error": f"El recurso es contenido binario ({content_type}) y no puede leerse como texto.",
            "error_code": "binary_content",
            "url": url,
            "suggestion": "Busca la versión HTML del mismo contenido, o usa una búsqueda para encontrar una página de texto alternativa."
        })

    try:
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
        logger.warning(f"[web_fetch] parse error for {url}: {e}")
        return json.dumps({
            "error": f"Error al procesar el contenido HTML: {e}",
            "error_code": "parse_error",
            "url": url,
            "suggestion": "Intenta con una URL diferente."
        })
