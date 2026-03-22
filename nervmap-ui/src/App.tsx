/** Main application component */

import { useEffect } from "preact/hooks";
import { useStore } from "./store";
import { GraphPanel } from "./panels/GraphPanel";
import { FileTreePanel } from "./panels/FileTreePanel";
import { EditorPanel } from "./panels/EditorPanel";
import type { PanelId } from "./store";

export function App() {
  const loading = useStore((s) => s.loading);
  const error = useStore((s) => s.error);
  const state = useStore((s) => s.state);
  const setState = useStore((s) => s.setState);
  const setError = useStore((s) => s.setError);
  const activePanel = useStore((s) => s.activePanel);
  const setActivePanel = useStore((s) => s.setActivePanel);

  // Initial fetch
  useEffect(() => {
    fetch("/api/state")
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then(setState)
      .catch((e) => setError(e.message));
  }, []);

  // WebSocket for live updates with auto-reconnect
  useEffect(() => {
    let ws: WebSocket | null = null;
    let reconnectDelay = 2000;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let closed = false;

    function connect() {
      if (closed) return;
      const proto = location.protocol === "https:" ? "wss:" : "ws:";
      ws = new WebSocket(`${proto}//${location.host}/ws`);

      ws.onmessage = (e) => {
        try {
          const msg = JSON.parse(e.data);
          if (msg.type === "full_state" || msg.type === "state_update") {
            setState(msg.data);
          }
        } catch (err) {
          console.warn("WS parse error:", err);
        }
      };

      ws.onopen = () => {
        reconnectDelay = 2000; // reset backoff on successful connect
      };

      ws.onclose = () => {
        if (closed) return;
        // Exponential backoff: 2s, 4s, 8s, max 30s
        reconnectTimer = setTimeout(() => {
          connect();
        }, reconnectDelay);
        reconnectDelay = Math.min(reconnectDelay * 2, 30000);
      };
    }

    connect();

    return () => {
      closed = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      ws?.close();
    };
  }, []);

  if (loading) {
    return (
      <div class="loading">
        <div class="spinner" />
        <span>Scanning infrastructure...</span>
      </div>
    );
  }

  if (error) {
    return (
      <div class="error">
        <h2>Connection Error</h2>
        <p>{error}</p>
        <button onClick={() => location.reload()}>Retry</button>
      </div>
    );
  }

  return (
    <div class="app">
      {/* Status bar */}
      <header class="status-bar">
        <span class="logo">NervMap</span>
        {state && (
          <>
            <span class="stat">{state.summary.total_services} services</span>
            <span class="stat">{state.summary.total_connections} connections</span>
            {state.summary.critical > 0 && (
              <span class="stat critical">
                {state.summary.critical} critical
              </span>
            )}
            {state.summary.warnings > 0 && (
              <span class="stat warning">
                {state.summary.warnings} warnings
              </span>
            )}
            {state.ai_chains && (
              <span class="stat">{state.ai_chains.length} AI chains</span>
            )}
          </>
        )}
      </header>

      {/* Desktop: 3 panels */}
      <div class="panels desktop-only">
        <FileTreePanel />
        <GraphPanel />
        <EditorPanel />
      </div>

      {/* Mobile: single panel + tabs */}
      <div class="mobile-only">
        <div class="mobile-panel">
          {activePanel === "graph" && <GraphPanel />}
          {activePanel === "tree" && <FileTreePanel />}
          {activePanel === "editor" && <EditorPanel />}
        </div>
        <nav class="tab-bar" role="tablist" aria-label="Dashboard panels">
          {(["graph", "tree", "editor"] as PanelId[]).map((p) => (
            <button
              key={p}
              class={`tab ${activePanel === p ? "active" : ""}`}
              onClick={() => setActivePanel(p)}
              role="tab"
              aria-selected={activePanel === p}
              aria-label={p === "graph" ? "Infrastructure map" : p === "tree" ? "File explorer" : "Code editor"}
            >
              {p === "graph" ? "Map" : p === "tree" ? "Files" : "Editor"}
            </button>
          ))}
        </nav>
      </div>
    </div>
  );
}
