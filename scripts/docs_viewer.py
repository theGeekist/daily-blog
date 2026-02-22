#!/usr/bin/env python3
import argparse
import functools
import os
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a simple local docs viewer")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind")
    parser.add_argument("--port", type=int, default=int(os.getenv("DOCS_VIEWER_PORT", "8765")))
    parser.add_argument("--no-open", action="store_true", help="Do not auto-open browser")
    args = parser.parse_args()

    root = Path(__file__).resolve().parent.parent
    docs_dir = root / "docs" / "viewer"
    if not docs_dir.is_dir():
        print(f"Docs directory not found: {docs_dir}")
        return 1

    handler = functools.partial(SimpleHTTPRequestHandler, directory=str(docs_dir))
    server = ThreadingHTTPServer((args.host, args.port), handler)
    url = f"http://{args.host}:{args.port}/index.html"

    print(f"Serving docs viewer at {url}")
    print("Press Ctrl+C to stop.")

    if not args.no_open:
        webbrowser.open(url)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
