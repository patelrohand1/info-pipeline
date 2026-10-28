"""Native Mac window for the triage UI. Launched by "Reading Triage.app" (build it with mac/build_app.sh).

Starts Ollama if it isn't up, runs Streamlit on a free local port, and shows it in a WebKit window.
Closing the window stops Streamlit.
"""
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import webview

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
LOG = ROOT / "logs" / "app.log"
# Finder-launched apps get a bare PATH, so look where Homebrew and the Ollama app put things.
os.environ["PATH"] = "/opt/homebrew/bin:/usr/local/bin:/Applications/Ollama.app/Contents/Resources:" + os.environ.get("PATH", "")


def ollama_up() -> bool:
    try:
        urllib.request.urlopen("http://localhost:11434/api/tags", timeout=1)
        return True
    except Exception:
        return False


def start_ollama() -> None:
    if ollama_up():
        return
    if Path("/Applications/Ollama.app").exists():
        subprocess.Popen(["open", "-g", "-a", "Ollama"])
    elif shutil.which("ollama"):
        subprocess.Popen(["ollama", "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    # Not fatal either way: the UI works without it, only scoring needs it.


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_for(url: str, timeout: float = 40) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(url, timeout=1)
            return True
        except Exception:
            time.sleep(0.25)
    return False


def brand_process() -> None:
    """Menu bar name and Dock icon, since the running binary is the venv's python."""
    try:
        from AppKit import NSApplication, NSImage
        from Foundation import NSBundle
        info = NSBundle.mainBundle().localizedInfoDictionary() or NSBundle.mainBundle().infoDictionary()
        info["CFBundleName"] = "Reading Triage"
        icon = ROOT / "mac" / "build" / "AppIcon.png"
        if icon.exists():
            NSApplication.sharedApplication().setApplicationIconImage_(NSImage.alloc().initWithContentsOfFile_(str(icon)))
    except Exception:
        pass


def main() -> None:
    from pipeline.config import load_config
    try:
        local_model = load_config().get("model", {}).get("provider", "ollama") != "gemini"
    except Exception:
        local_model = True
    if local_model:
        start_ollama()
    port = free_port()
    LOG.parent.mkdir(exist_ok=True)
    server = subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", str(ROOT / "app.py"),
         "--server.port", str(port), "--server.address", "127.0.0.1", "--server.headless", "true"],
        cwd=ROOT, stdout=LOG.open("a"), stderr=subprocess.STDOUT,
    )
    url = f"http://127.0.0.1:{port}"
    try:
        if not wait_for(f"{url}/_stcore/health"):
            raise SystemExit(f"Streamlit didn't start; see {LOG}")
        brand_process()
        webview.settings["ALLOW_DOWNLOADS"] = True  # Anki .apkg export
        webview.create_window("Reading Triage", url, width=1200, height=880, min_size=(760, 560),
                              background_color="#0D1016", text_select=True)
        webview.start()
    finally:
        server.terminate()
        try:
            server.wait(5)
        except subprocess.TimeoutExpired:
            server.kill()


if __name__ == "__main__":
    main()
