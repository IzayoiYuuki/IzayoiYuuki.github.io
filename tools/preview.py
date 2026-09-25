#!/usr/bin/env python3
"""Start a local-only preview and open the birding page. Ctrl+C stops it."""
import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import webbrowser


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8000)
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    handler = partial(SimpleHTTPRequestHandler, directory=str(root))
    server = None
    for port in range(args.port, min(args.port + 20, 65536)):
        try: server = ThreadingHTTPServer(('127.0.0.1', port), handler); break
        except OSError: continue
    if server is None: raise SystemExit('No free preview port. Try --port 9000.')
    url = f'http://localhost:{server.server_port}/birding/'
    print(f'Preview: {url}\nHomepage: http://localhost:{server.server_port}/\nPress Ctrl+C to stop.', flush=True)
    if not args.no_browser: webbrowser.open(url)
    try: server.serve_forever()
    except KeyboardInterrupt: print('\nPreview stopped.')
    finally: server.server_close()


if __name__ == '__main__': main()
