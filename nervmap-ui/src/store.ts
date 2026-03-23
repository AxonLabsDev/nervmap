/** Zustand store — single source of truth for all 3 panels */

import { create } from "zustand";
import type { NervMapState, FileEntry } from "./types";

export type PanelId = "graph" | "tree" | "editor";

interface Store {
  // Data from backend
  state: NervMapState | null;
  loading: boolean;
  error: string | null;

  // Selection (drives cross-panel sync)
  selectedNodeId: string | null;
  selectedFilePath: string | null;
  activeChainId: string | null;
  highlightedIds: Set<string>;

  // Editor
  editorContent: string | null;
  editorPath: string | null;
  editorLanguage: string;

  // UI
  activePanel: PanelId;
  layoutMode: "topology" | "hierarchy";
  scopePath: string | null;

  // Actions
  setState: (s: NervMapState) => void;
  setLoading: (v: boolean) => void;
  setScopePath: (p: string | null) => void;
  setError: (e: string | null) => void;
  selectNode: (id: string) => void;
  selectFile: (path: string) => void;
  clearSelection: () => void;
  setActivePanel: (p: PanelId) => void;
  setLayoutMode: (m: "topology" | "hierarchy") => void;
  openFile: (path: string, content: string) => void;
}

export const useStore = create<Store>((set, get) => ({
  state: null,
  loading: true,
  error: null,
  selectedNodeId: null,
  selectedFilePath: null,
  activeChainId: null,
  highlightedIds: new Set(),
  editorContent: null,
  editorPath: null,
  editorLanguage: "plaintext",
  activePanel: "graph",
  layoutMode: "topology",
  scopePath: null,

  setState: (s) => set({ state: s, loading: false, error: null }),
  setLoading: (v) => set({ loading: v }),
  setError: (e) => set({ error: e, loading: false }),
  setScopePath: (p) => set({ scopePath: p }),

  selectNode: (id) => {
    const s = get().state;
    if (!s) return;

    // Find chain containing this service (exact match only)
    const chain = s.ai_chains?.find(
      (c) => c.id === id || c.linked_services?.includes(id)
    );

    set({
      selectedNodeId: id,
      activeChainId: chain?.id ?? null,
      highlightedIds: chain
        ? new Set([chain.id, ...(chain.consumers ?? [])])
        : new Set([id]),
    });
  },

  selectFile: (path) => {
    set({ selectedFilePath: path });
    // Fetch file content
    fetch(`/api/file?path=${encodeURIComponent(path)}`)
      .then((r) => {
        if (!r.ok) throw new Error("Cannot read file");
        return r.json();
      })
      .then((data) => {
        const lang = detectLanguage(path);
        set({
          editorContent: data.content,
          editorPath: path,
          editorLanguage: lang,
        });
      })
      .catch(() => {
        set({ editorContent: null, editorPath: path });
      });
  },

  clearSelection: () =>
    set({
      selectedNodeId: null,
      selectedFilePath: null,
      activeChainId: null,
      highlightedIds: new Set(),
    }),

  setActivePanel: (p) => set({ activePanel: p }),
  setLayoutMode: (m) => set({ layoutMode: m }),
  openFile: (path, content) =>
    set({
      editorContent: content,
      editorPath: path,
      editorLanguage: detectLanguage(path),
      activePanel: "editor",
    }),
}));

function detectLanguage(path: string): string {
  const ext = path.split(".").pop()?.toLowerCase() ?? "";
  const map: Record<string, string> = {
    py: "python",
    js: "javascript",
    ts: "typescript",
    tsx: "typescript",
    jsx: "javascript",
    json: "json",
    yml: "yaml",
    yaml: "yaml",
    md: "markdown",
    css: "css",
    html: "html",
    sh: "shell",
  };
  return map[ext] ?? "plaintext";
}
