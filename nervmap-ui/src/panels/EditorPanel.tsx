/** CodeMirror 6 editor panel */

import { useRef, useEffect } from "preact/hooks";
import { EditorView, basicSetup } from "codemirror";
import { EditorState, Compartment } from "@codemirror/state";
import { oneDark } from "@codemirror/theme-one-dark";
import { useStore } from "../store";

// Language compartment for dynamic reconfiguration
const languageConf = new Compartment();

// Language loaders (lazy)
const LANGS: Record<string, () => Promise<any>> = {
  python: () => import("@codemirror/lang-python").then((m) => m.python()),
  javascript: () =>
    import("@codemirror/lang-javascript").then((m) => m.javascript()),
  typescript: () =>
    import("@codemirror/lang-javascript").then((m) =>
      m.javascript({ typescript: true })
    ),
  json: () => import("@codemirror/lang-json").then((m) => m.json()),
  yaml: () => import("@codemirror/lang-yaml").then((m) => m.yaml()),
  markdown: () =>
    import("@codemirror/lang-markdown").then((m) => m.markdown()),
};

export function EditorPanel() {
  const containerRef = useRef<HTMLDivElement>(null);
  const viewRef = useRef<EditorView | null>(null);
  const content = useStore((s) => s.editorContent);
  const path = useStore((s) => s.editorPath);
  const language = useStore((s) => s.editorLanguage);

  useEffect(() => {
    if (!containerRef.current) return;

    // Destroy previous
    viewRef.current?.destroy();

    if (content === null) return;

    const extensions = [
      basicSetup,
      oneDark,
      EditorView.lineWrapping,
      EditorState.readOnly.of(true),
      languageConf.of([]),  // empty, filled async
    ];

    const state = EditorState.create({ doc: content, extensions });
    const view = new EditorView({ state, parent: containerRef.current });

    // Load language grammar async via Compartment
    const loader = LANGS[language];
    if (loader) {
      loader()
        .then((ext) => {
          view.dispatch({
            effects: languageConf.reconfigure(ext),
          });
        })
        .catch((e) => console.warn("Language load failed:", e));
    }

    viewRef.current = view;
    return () => view.destroy();
  }, [content, path]);

  const filename = path?.split("/").pop() ?? "";

  return (
    <div class="panel editor-panel">
      <div class="panel-header">
        <span>{filename || "Editor"}</span>
        {path && <span class="badge">{language}</span>}
      </div>
      {content !== null ? (
        <div ref={containerRef} class="editor-container" />
      ) : (
        <div class="editor-empty">
          Select a file from the tree or click a node in the graph
        </div>
      )}
    </div>
  );
}
