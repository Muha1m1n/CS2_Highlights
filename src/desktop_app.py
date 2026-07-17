"""
ClipperCS2 Native Desktop Application (`src/desktop_app.py`)

Runs ClipperCS2 inside a standalone native Windows GUI application window (using PyWebView / Edge WebView2 or PyQt6).
No web browser required! All data stays 100% local to your machine.

Features:
1. Home Screen with options: 'Generate New Match' and 'View Generated Matches'
2. Connects directly to your local CS2 demo folder to scan & parse .dem files into SQLite
3. Browse generated matches -> Select player -> View ML-ranked highlights -> One-click OBS+CS2 recording with audio fix!
"""

import os
import sys
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass
import time
import threading
import uvicorn
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.web_server import app

import socket

def get_free_port(start_port=8000, max_tries=50):
    for port in range(start_port, start_port + max_tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    return 8765

def start_backend(port):
    """Starts the local-only backend server on a background daemon thread."""
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")

def launch_desktop():
    print("=" * 64)
    print("  ClipperCS2 - Local Desktop Application")
    print("  Initializing local backend server & native window...")
    print("=" * 64)

    # Find an available open port automatically
    port = get_free_port(8000)
    print(f"[DesktopApp] Starting local backend on http://127.0.0.1:{port}")

    # Start local backend thread
    server_thread = threading.Thread(target=start_backend, args=(port,), daemon=True)
    server_thread.start()

    # Give server 1.2s to bind port
    time.sleep(1.2)

    try:
        import webview
        # Create standalone native window
        window = webview.create_window(
            title="ClipperCS2 — Local Desktop Application",
            url=f"http://127.0.0.1:{port}",
            width=1280,
            height=820,
            min_size=(1024, 640),
            resizable=True,
            text_select=True
        )
        print("[DesktopApp] Launching native window via PyWebView...")
        webview.start()
    except Exception as e:
        print(f"[DesktopApp WARNING] PyWebView launch failed ({e}). Auto-launching local app in native default app...")
        import webbrowser
        webbrowser.open(f"http://127.0.0.1:{port}")
        # Keep main thread alive if webview didn't block
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass

if __name__ == "__main__":
    launch_desktop()
