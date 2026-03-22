"""FastAPI web server for NervMap dashboard."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse

from nervmap.scanner import full_scan
from nervmap.config import load_config
from nervmap.web.security import PathGuard

logger = logging.getLogger("nervmap.web")

MAX_WS_CLIENTS = 50


def create_app(cfg: dict | None = None) -> FastAPI:
    """Create the FastAPI application."""
    cfg = cfg or load_config(None)

    # Shared state container
    class AppState:
        scan_data: dict | None = None
        scan_hash: str | None = None
        scan_lock = asyncio.Lock()
        ws_clients: set[WebSocket] = set()
        scan_task: asyncio.Task | None = None

    app_state = AppState()

    # Compute allowed paths for file API
    allowed_roots = _compute_allowed_roots(cfg)
    guard = PathGuard(allowed_roots)

    # ── Lifespan ──────────────────────────────────────────────────

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """Startup: initial scan + background loop. Shutdown: cancel task."""
        await _run_scan(cfg, app_state)
        app_state.scan_task = asyncio.create_task(_scan_loop(cfg, app_state))
        yield
        if app_state.scan_task:
            app_state.scan_task.cancel()

    app = FastAPI(
        title="NervMap Dashboard",
        description="Infrastructure cartography — services, dependencies, AI chains",
        version="0.4.0",
        lifespan=lifespan,
    )

    # ── REST endpoints ────────────────────────────────────────────

    @app.get("/api/state")
    async def get_state():
        """Full scan result as JSON."""
        if app_state.scan_data is None:
            await _run_scan(cfg, app_state)
        return JSONResponse(content=app_state.scan_data)

    @app.post("/api/rescan")
    async def rescan():
        """Force a rescan."""
        await _run_scan(cfg, app_state)
        return {"status": "ok", "services": len(app_state.scan_data.get("services", []))}

    @app.get("/api/tree")
    async def get_tree(root: str = Query(..., description="Directory path")):
        """List directory contents."""
        try:
            entries = guard.list_dir(root)
            return JSONResponse(content={"path": root, "entries": entries})
        except ValueError as e:
            raise HTTPException(status_code=403, detail=str(e))

    @app.get("/api/file")
    async def get_file(path: str = Query(..., description="File path")):
        """Read file content."""
        try:
            content = guard.read_file(path)
            return JSONResponse(content={
                "path": path,
                "content": content,
                "size": len(content),
            })
        except ValueError as e:
            raise HTTPException(status_code=403, detail=str(e))

    @app.get("/health")
    async def health():
        """Liveness check."""
        return {"status": "ok", "version": "0.4.0"}

    # ── WebSocket ─────────────────────────────────────────────────

    @app.websocket("/ws")
    async def websocket_endpoint(ws: WebSocket):
        # Connection limit
        if len(app_state.ws_clients) >= MAX_WS_CLIENTS:
            await ws.close(code=1013)
            return

        await ws.accept()
        app_state.ws_clients.add(ws)
        try:
            # Send full state on connect
            if app_state.scan_data:
                await ws.send_json({"type": "full_state", "data": app_state.scan_data})

            # Keep alive loop
            while True:
                try:
                    msg = await asyncio.wait_for(ws.receive_text(), timeout=60)
                    try:
                        data = json.loads(msg)
                    except json.JSONDecodeError:
                        await ws.send_json({"type": "error", "message": "Invalid JSON"})
                        continue

                    if data.get("type") == "ping":
                        await ws.send_json({"type": "pong"})
                    elif data.get("type") == "rescan":
                        await _run_scan(cfg, app_state)
                        await ws.send_json({"type": "full_state", "data": app_state.scan_data})
                except asyncio.TimeoutError:
                    await ws.send_json({"type": "pong"})
        except WebSocketDisconnect:
            pass
        except Exception:
            logger.debug("WebSocket error", exc_info=True)
        finally:
            app_state.ws_clients.discard(ws)

    # ── Static files (frontend) ───────────────────────────────────

    static_dir = Path(__file__).parent / "static"
    if static_dir.is_dir() and (static_dir / "index.html").exists():
        app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")
    else:
        @app.get("/")
        async def root():
            return HTMLResponse(content=_placeholder_html())

    return app


async def _run_scan(cfg: dict, app_state):
    """Run a full scan in a thread pool and update state. Thread-safe via lock."""
    async with app_state.scan_lock:
        loop = asyncio.get_event_loop()
        state, issues = await loop.run_in_executor(None, full_scan, cfg)

        scan_dict = state.to_dict()
        from nervmap import __version__
        scan_dict["version"] = __version__
        scan_dict["issues"] = [i.to_dict() for i in issues]
        scan_dict["summary"] = {
            "total_services": len(state.services),
            "total_connections": len(state.connections),
            "total_issues": len(issues),
            "critical": sum(1 for i in issues if i.severity == "critical"),
            "warnings": sum(1 for i in issues if i.severity == "warning"),
            "info": sum(1 for i in issues if i.severity == "info"),
        }
        scan_dict["scanned_at"] = int(time.time())

        # Check if state changed
        new_hash = hashlib.md5(
            json.dumps(scan_dict, sort_keys=True, default=str).encode()
        ).hexdigest()

        if new_hash != app_state.scan_hash:
            app_state.scan_data = scan_dict
            app_state.scan_hash = new_hash

            # Push to WebSocket clients
            msg = json.dumps({"type": "state_update", "data": scan_dict}, default=str)
            for ws in list(app_state.ws_clients):
                try:
                    await ws.send_text(msg)
                except Exception:
                    app_state.ws_clients.discard(ws)


async def _scan_loop(cfg: dict, app_state, interval: int = 10):
    """Background loop: rescan every N seconds, push diffs."""
    while True:
        await asyncio.sleep(interval)
        try:
            await _run_scan(cfg, app_state)
        except asyncio.CancelledError:
            break
        except Exception:
            logger.debug("Background scan failed", exc_info=True)


def _compute_allowed_roots(cfg: dict) -> list[str]:
    """Compute allowed filesystem roots from config and scan results."""
    roots = []

    # From .nervmap.yml source.paths
    source_paths = cfg.get("source", {}).get("paths", [])
    for p in source_paths:
        expanded = os.path.expanduser(p)
        if os.path.isdir(expanded):
            roots.append(expanded)

    # From web config
    web_paths = cfg.get("web", {}).get("allowed_paths", [])
    for p in web_paths:
        expanded = os.path.expanduser(p)
        if os.path.isdir(expanded):
            roots.append(expanded)

    # Default: cwd
    cwd = os.getcwd()
    if cwd not in roots:
        roots.append(cwd)

    return roots


def _placeholder_html() -> str:
    """Placeholder page when frontend is not built yet."""
    return """<!DOCTYPE html>
<html>
<head><title>NervMap Dashboard</title>
<style>
body { background: #0f172a; color: #e2e8f0; font-family: system-ui;
       display: flex; justify-content: center; align-items: center;
       height: 100vh; margin: 0; }
.card { text-align: center; max-width: 500px; }
h1 { color: #38bdf8; }
code { background: #1e293b; padding: 4px 8px; border-radius: 4px; }
a { color: #38bdf8; }
</style>
</head>
<body>
<div class="card">
<h1>NervMap Dashboard</h1>
<p>Backend is running. Frontend not built yet.</p>
<p>API available at <a href="/docs">/docs</a></p>
<p>State: <a href="/api/state">/api/state</a></p>
<p>Health: <a href="/health">/health</a></p>
</div>
</body>
</html>"""


def run_server(cfg: dict, host: str = "127.0.0.1", port: int = 9000,
               auto_open: bool = False):
    """Start the dashboard server."""
    import uvicorn

    app = create_app(cfg)

    if auto_open:
        import webbrowser
        webbrowser.open(f"http://{host}:{port}")

    uvicorn.run(app, host=host, port=port, log_level="warning")
