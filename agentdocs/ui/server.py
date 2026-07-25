"""A small, dependency-free local web server for the AgentDocs UI.

Binds to 127.0.0.1 only. It exposes a handful of JSON endpoints plus two
Server-Sent-Events streams (blueprint generation and the mini-terminal).
"""

from __future__ import annotations

import codecs
import json
import os
import subprocess
import sys
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import blueprint as bp
from . import ollama_client

STATIC_DIR = Path(__file__).parent / "static"
PROJECT_ROOT = Path(__file__).resolve().parents[2]

_CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".ico": "image/x-icon",
    ".svg": "image/svg+xml",
}


def _md_count(folder: Path, cap: int = 100000) -> int:
    n = 0
    try:
        for _ in folder.rglob("*.md"):
            n += 1
            if n >= cap:
                break
    except OSError:
        pass
    return n


def command_shortcuts() -> list[dict]:
    """The copy-paste command palette shown in the UI."""
    py = "python"
    return [
        {
            "title": "Scrape a documentation site",
            "desc": "Discover every page, confirm, then download as Markdown.",
            "cmd": f"{py} -m agentdocs https://help.obsidian.md/",
        },
        {
            "title": "Preview pages without downloading",
            "desc": "List everything the scraper found; writes nothing.",
            "cmd": f"{py} -m agentdocs https://help.obsidian.md/ --list-only",
        },
        {
            "title": "Scrape into a chosen folder, no prompt",
            "desc": "Pick the output directory and skip the confirmation.",
            "cmd": f"{py} -m agentdocs <URL> --out ./docs --yes",
        },
        {
            "title": "Limit to a sub-section",
            "desc": "Only include pages under a URL prefix.",
            "cmd": f"{py} -m agentdocs <URL> --prefix <URL>/guide/",
        },
        {
            "title": "Cap the number of pages",
            "desc": "Useful for a quick sample of a large site.",
            "cmd": f"{py} -m agentdocs <URL> --max 25",
        },
        {
            "title": "Launch this UI",
            "desc": "Starts the local server and opens the browser.",
            "cmd": f"{py} -m agentdocs.ui",
        },
        {
            "title": "Install dependencies",
            "desc": "One-time setup of the Python requirements.",
            "cmd": f"{py} -m pip install -r requirements.txt",
        },
    ]


class Handler(BaseHTTPRequestHandler):
    server_version = "AgentDocs"

    # -- plumbing --------------------------------------------------------- #
    def log_message(self, *args):  # quieter console
        pass

    def _json(self, obj, status=200):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0) or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return {}

    def _sse_open(self):
        # The stream is terminated by closing the socket, so the client's
        # reader sees EOF and its promise resolves. Keeping the connection
        # alive here would leave the UI stuck waiting forever.
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True

    def _sse(self, obj) -> bool:
        """Send one SSE message. Returns False if the client has gone away."""
        try:
            self.wfile.write(f"data: {json.dumps(obj)}\n\n".encode("utf-8"))
            self.wfile.flush()
            return True
        except (BrokenPipeError, ConnectionResetError, OSError):
            return False

    # -- routing ---------------------------------------------------------- #
    def do_GET(self):
        parsed = urlparse(self.path)
        route = parsed.path
        query = parse_qs(parsed.query)

        if route == "/":
            return self._serve_static("index.html")
        if route.startswith("/static/"):
            return self._serve_static(route[len("/static/"):])
        if route == "/api/env":
            return self._api_env()
        if route == "/api/models":
            return self._api_models()
        if route == "/api/commands":
            return self._json({"commands": command_shortcuts()})
        if route == "/api/list":
            return self._api_list(query.get("path", [""])[0])
        if route == "/api/docset":
            return self._api_docset(query.get("path", [""])[0])
        if route == "/api/file":
            return self._api_file(query.get("path", [""])[0])
        return self._json({"error": "not found"}, 404)

    def do_POST(self):
        route = urlparse(self.path).path
        if route == "/api/blueprint":
            return self._api_blueprint()
        if route == "/api/run":
            return self._api_run()
        return self._json({"error": "not found"}, 404)

    # -- static ----------------------------------------------------------- #
    def _serve_static(self, rel: str):
        target = (STATIC_DIR / rel).resolve()
        if not str(target).startswith(str(STATIC_DIR.resolve())) or not target.is_file():
            return self._json({"error": "not found"}, 404)
        data = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", _CONTENT_TYPES.get(target.suffix, "application/octet-stream"))
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    # -- api: environment & models --------------------------------------- #
    def _api_env(self):
        default_docs = PROJECT_ROOT / "agentdocs_output"
        self._json(
            {
                "project_root": str(PROJECT_ROOT),
                "default_docs_dir": str(default_docs if default_docs.exists() else PROJECT_ROOT),
                "python": sys.executable,
                "ollama_up": ollama_client.is_up(),
                "platform": sys.platform,
            }
        )

    def _api_models(self):
        try:
            self._json({"models": ollama_client.list_models(), "up": True})
        except ollama_client.OllamaError as exc:
            self._json({"models": [], "up": False, "error": str(exc)})

    # -- api: filesystem -------------------------------------------------- #
    def _api_list(self, path: str):
        p = Path(path).expanduser() if path else PROJECT_ROOT
        try:
            p = p.resolve()
        except OSError:
            return self._json({"error": "bad path"}, 400)
        if not p.is_dir():
            return self._json({"error": "not a folder"}, 400)

        dirs = []
        for child in sorted(p.iterdir(), key=lambda c: c.name.lower()):
            if child.is_dir() and not child.name.startswith((".", "__")):
                dirs.append(
                    {"name": child.name, "path": str(child), "md_count": _md_count(child)}
                )
        parent = str(p.parent) if p.parent != p else None
        self._json({"path": str(p), "parent": parent, "dirs": dirs, "direct_md": _md_count(p, cap=1) > 0})

    def _api_docset(self, path: str):
        root = Path(path).expanduser()
        if not root.is_dir():
            return self._json({"error": "not a folder"}, 400)
        files = []
        for f in sorted(root.rglob("*.md")):
            rel = f.relative_to(root)
            if bp.BLUEPRINT_DIRNAME in rel.parts:
                continue
            files.append({"rel": rel.as_posix(), "path": str(f), "name": f.name})
        blueprint_dir = root / bp.BLUEPRINT_DIRNAME
        blueprint = []
        if blueprint_dir.is_dir():
            for f in sorted(blueprint_dir.glob("*.md")):
                blueprint.append({"rel": f.name, "path": str(f), "name": f.name})
        self._json(
            {
                "path": str(root),
                "name": root.name,
                "files": files,
                "has_blueprint": bool(blueprint),
                "blueprint": blueprint,
            }
        )

    def _api_file(self, path: str):
        f = Path(path).expanduser()
        if not f.is_file():
            return self._json({"error": "not a file"}, 400)
        try:
            content = f.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return self._json({"error": str(exc)}, 400)
        self._json({"path": str(f), "name": f.name, "content": content})

    # -- api: blueprint (SSE) -------------------------------------------- #
    def _api_blueprint(self):
        body = self._read_body()
        path = body.get("path", "")
        model = body.get("model", "")
        self._sse_open()
        if not path or not model:
            self._sse({"type": "error", "message": "Missing folder or model."})
            return
        try:
            for event in bp.build_blueprint(path, model):
                if not self._sse(event):
                    return  # client disconnected
        except Exception as exc:  # noqa: BLE001 — surface anything to the UI
            self._sse({"type": "error", "message": f"{type(exc).__name__}: {exc}"})

    # -- api: mini terminal (SSE) ---------------------------------------- #
    def _api_run(self):
        body = self._read_body()
        cmd = (body.get("cmd") or "").strip()
        cwd = body.get("cwd") or str(PROJECT_ROOT)
        self._sse_open()
        if not cmd:
            self._sse({"type": "done", "code": 0})
            return
        if not Path(cwd).is_dir():
            cwd = str(PROJECT_ROOT)

        # The working directory follows whichever doc folder is loaded, so put
        # the project root on PYTHONPATH — otherwise `python -m agentdocs ...`
        # (the commands we advertise) fails outside the project directory.
        env = os.environ.copy()
        existing = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = str(PROJECT_ROOT) + (os.pathsep + existing if existing else "")
        # Unbuffered, so prompts and progress reach the UI as they are written
        # rather than sitting in the child's block buffer until it exits.
        env["PYTHONUNBUFFERED"] = "1"

        try:
            proc = subprocess.Popen(
                cmd,
                shell=True,
                cwd=cwd,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.PIPE,  # interactive: commands can ask questions
                bufsize=0,              # binary + unbuffered; we decode ourselves
            )
        except OSError as exc:
            self._sse({"type": "text", "text": f"[failed to start] {exc}\n"})
            self._sse({"type": "done", "code": -1})
            return

        run_id = uuid.uuid4().hex
        with _RUNS_LOCK:
            _RUNS[run_id] = proc
        self._sse({"type": "meta", "cwd": cwd, "run_id": run_id})

        # Read raw chunks rather than lines: a prompt like "[y/N]: " has no
        # trailing newline, and line iteration would hide it until the next one.
        decoder = codecs.getincrementaldecoder("utf-8")("replace")
        fd = proc.stdout.fileno()
        try:
            while True:
                try:
                    data = os.read(fd, 4096)
                except OSError:
                    break
                if not data:
                    break
                text = decoder.decode(data)
                if text and not self._sse({"type": "text", "text": text}):
                    proc.terminate()  # client went away
                    return
            tail = decoder.decode(b"", final=True)
            if tail:
                self._sse({"type": "text", "text": tail})
            proc.wait()
            self._sse({"type": "done", "code": proc.returncode})
        finally:
            with _RUNS_LOCK:
                _RUNS.pop(run_id, None)
            try:
                proc.stdin.close()
            except OSError:
                pass

    def _api_stdin(self):
        """Send a line of input to a running command (answers its prompts)."""
        body = self._read_body()
        run_id = body.get("run_id") or ""
        text = body.get("text", "")
        with _RUNS_LOCK:
            proc = _RUNS.get(run_id)
        if proc is None or proc.poll() is not None:
            return self._json({"ok": False, "error": "no running command"}, 409)
        try:
            proc.stdin.write((text + "\n").encode("utf-8"))
            proc.stdin.flush()
        except OSError as exc:
            return self._json({"ok": False, "error": str(exc)}, 400)
        self._json({"ok": True})

    def _api_stop(self):
        """Terminate a running command."""
        body = self._read_body()
        with _RUNS_LOCK:
            proc = _RUNS.get(body.get("run_id") or "")
        if proc is None or proc.poll() is not None:
            return self._json({"ok": False, "error": "no running command"}, 409)
        proc.terminate()
        self._json({"ok": True})


def serve(host: str = "127.0.0.1", port: int = 8765) -> ThreadingHTTPServer:
    httpd = ThreadingHTTPServer((host, port), Handler)
    return httpd


def run(host: str = "127.0.0.1", port: int = 8765, open_browser: bool = True) -> None:
    import webbrowser

    httpd = serve(host, port)
    url = f"http://{host}:{port}/"
    print(f"AgentDocs UI running at {url}")
    print("Press Ctrl+C to stop.")
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        httpd.shutdown()
