# SPDX-FileCopyrightText: Copyright 2026 Arm Limited and/or its affiliates <open-source-office@arm.com>
# SPDX-License-Identifier: Apache-2.0

"""Serve a profiling report on localhost so Perfetto can load its local trace."""

import argparse
import webbrowser
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument(
        "--port", type=int, default=0, help="Local port (default: choose a free port)"
    )
    parser.add_argument(
        "--no-open", action="store_true", help="Print the URL without opening a browser"
    )
    args = parser.parse_args()
    root = args.run_dir.resolve()
    if not (root / "index.html").is_file():
        parser.exit(1, f"report server failed: no index.html in {root}\n")
    handler = partial(SimpleHTTPRequestHandler, directory=str(root))
    with ThreadingHTTPServer(("127.0.0.1", args.port), handler) as server:
        address = f"http://127.0.0.1:{server.server_port}/index.html"
        print(f"Report: {address}", flush=True)
        print("Press Ctrl-C to stop the local report server.", flush=True)
        if not args.no_open:
            webbrowser.open(address)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
