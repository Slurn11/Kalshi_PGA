"""Entry point for python3 -m tui or python3 -m tui.app."""
# Configure logging BEFORE any other imports to prevent stdout pollution
import logging
import sys
from pathlib import Path

# Redirect all logs to a file instead of stdout
log_file = Path(__file__).parent.parent / "tui.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.FileHandler(log_file, mode="w")],
    force=True,  # Override any existing configuration
)

# Suppress any stray print statements by redirecting stderr
# (Textual handles its own rendering)

from tui.app import GolfDashboard

app = GolfDashboard()
app.run()
