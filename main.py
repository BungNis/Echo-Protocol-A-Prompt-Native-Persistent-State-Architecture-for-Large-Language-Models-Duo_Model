"""Synapse Protocol V1 — Entry Point"""
import sys
import threading
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from web.app import app

PORT = 8080

def open_browser():
    webbrowser.open(f"http://127.0.0.1:{PORT}")

if __name__ == "__main__":
    print(f"Synapse Protocol V1 — http://127.0.0.1:{PORT}")
    threading.Timer(1.0, open_browser).start()
    app.run(host="127.0.0.1", port=PORT, debug=False, threaded=True)
