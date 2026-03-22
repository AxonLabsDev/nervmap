"""FastAPI web server for NervMap dashboard."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import time
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse

from nervmap.scanner import full_scan
from nervmap.config import load_config
from nervmap.web.security import PathGuard

logger = logging.getLogger("nervmap.web")


def create_app(cfg: dict | None = None) -> FastAPI:
    """Create the FastAPI application."""
    cfg = cfg or load_config(None)

    app = FastAPI(
        title="NervMap Dashboard",
        description="Infrastructure cartography — services, dependencies, AI chains",
        version="0.4.0",
    )

    # Compute allowed paths for file API
    allowed_roots = _compute_allowed_roots(cfg)
    guard = PathGuard(allowed_roots)

    # Shared state (updated by scan loop)
    app.state.scan_data = None
    app.state.scan_hash = None
    app.state.cfg = cfg
    app.state.guard = guard
    app.state.ws_clients: set[WebSocket] = set()

    # ── REST endpoints ────────────────────────────────────────────

    @app.get("/api/state")
    async def get_state():
        """Full scan result as JSON."""
        if app.state.scan_data is None:
            # First request triggers a scan
            await _run_scan(app)
        return JSONResponse(content=app.state.scan_data)

    @app.post("/api/rescan")
    async def rescan():
        """Force a rescan."""
        await _run_scan(app)
        return {"status": "ok", "services": len(app.state.scan_data.get("services", []))}

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
        await ws.accept()
        app.state.ws_clients.add(ws)
        try:
            # Send full state on connect
            if app.state.scan_data:
                await ws.send_json({"type": "full_state", "data": app.state.scan_data})

            # Keep alive loop
            while True:
                try:
                    msg = await asyncio.wait_for(ws.receive_text(), timeout=60)
                    data = json.loads(msg)
                    if data.get("type") == "ping":
                        await ws.send_json({"type": "pong"})
                    elif data.get("type") == "rescan":
                        await _run_scan(app)
                        await ws.send_json({"type": "full_state", "data": app.state.scan_data})
                except asyncio.TimeoutError:
                    # Send keepalive
                    await ws.send_json({"type": "pong"})
        except WebSocketDisconnect:
            pass
        finally:
            app.state.ws_clients.discard(ws)

    # ── Background scan loop ──────────────────────────────────────

    @app.on_event("startup")
    async def startup():
        """Run initial scan and start background loop."""
        await _run_scan(app)
        asyncio.create_task(_scan_loop(app))

    # ── Static files (frontend) ───────────────────────────────────

    static_dir = Path(__file__).parent / "static"
    if static_dir.is_dir() and (static_dir / "index.html").exists():
        app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")
    else:
        @app.get("/")
        async def root():
            return HTMLResponse(content=_placeholder_html())

    return app


async def _run_scan(app: FastAPI):
    """Run a full scan in a thread pool and update state."""
    loop = asyncio.get_event_loop()
    cfg = app.state.cfg

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

    if new_hash != app.state.scan_hash:
        app.state.scan_data = scan_dict
        app.state.scan_hash = new_hash

        # Push to WebSocket clients
        msg = json.dumps({"type": "state_update", "data": scan_dict}, default=str)
        for ws in list(app.state.ws_clients):
            try:
                await ws.send_text(msg)
            except Exception:
                app.state.ws_clients.discard(ws)


async def _scan_loop(app: FastAPI, interval: int = 10):
    """Background loop: rescan every N seconds, push diffs."""
    while True:
        await asyncio.sleep(interval)
        try:
            await _run_scan(app)
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
