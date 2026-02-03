#!/usr/bin/env python3
"""Dashboard entry point for the PGA Golf Betting System.

Usage:
    python3 dashboard.py          # Terminal mode
    python3 dashboard.py --web    # Browser mode (http://localhost:8000)
"""

import logging
import sys
from pathlib import Path

# Route all logging to file instead of stdout (would clutter TUI)
log_path = Path(__file__).parent / "dashboard.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    filename=str(log_path),
    filemode="a",
    force=True,
)

from tui.app import GolfDashboard


def main():
    if "--web" in sys.argv:
        from textual_serve.server import Server
        server = Server("python3 dashboard.py", host="localhost", port=8000)
        print("Serving dashboard at http://localhost:8000")
        server.serve()
    else:
        app = GolfDashboard()
        app.run()


if __name__ == "__main__":
    main()
