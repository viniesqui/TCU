#!/usr/bin/env python3
"""
TCU web UI launcher.

Starts the FastAPI server on a local port. The browser drives the pipeline
end-to-end: sector selection, live stage progress, inline gap review, and
the rendered HTML report — all in one place.

Usage:
    ./run web
    ./run web --port 9000
"""
from __future__ import annotations

import argparse
import logging
import sys
import webbrowser

import uvicorn


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="TCU web UI server")
    parser.add_argument("--host", default="127.0.0.1", help="Bind address (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8765, help="Bind port (default: 8765)")
    parser.add_argument("--no-browser", action="store_true", help="Don't auto-open the browser")
    parser.add_argument("--verbose", action="store_true", help="Verbose logging")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout)],
    )
    for noisy in ("httpx", "httpcore", "urllib3", "duckduckgo_search", "uvicorn.access"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    # Validate config early so we fail before binding the port.
    try:
        from src.config import settings
        _ = settings.anthropic_api_key
    except Exception as e:
        print(f"\n✗ Error de configuración: {e}", file=sys.stderr)
        print("  Asegúrate de que .env existe con ANTHROPIC_API_KEY definido.", file=sys.stderr)
        sys.exit(1)

    url = f"http://{args.host}:{args.port}"
    print(f"\n→ TCU web UI: {url}")
    if not args.no_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass

    uvicorn.run(
        "src.web.server:app",
        host=args.host,
        port=args.port,
        log_level="info" if not args.verbose else "debug",
    )


if __name__ == "__main__":
    main()
