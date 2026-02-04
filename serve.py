"""Serve the Golf Dashboard on localhost:8000"""
import subprocess
import sys
import os

os.chdir(os.path.dirname(os.path.abspath(__file__)))

if __name__ == "__main__":
    subprocess.run([
        sys.executable, "-m", "textual", "serve",
        "--port", "8000",
        "--host", "0.0.0.0",
        "serve_app.py:app",
    ])
