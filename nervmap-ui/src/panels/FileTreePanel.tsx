/** File tree panel — lazy-loaded directory listing */

import { useState, useEffect } from "preact/hooks";
import { useStore } from "../store";
import type { FileEntry } from "../types";

export function FileTreePanel() {
  const state = useStore((s) => s.state);
  const selectFile = useStore((s) => s.selectFile);
  const selectedFilePath = useStore((s) => s.selectedFilePath);

  // Collect root paths from AI chain configs and projects
  const roots = getRoots(state);

  return (
    <div class="panel tree-panel">
      <div class="panel-header">
        <span>Files</span>
      </div>
      <div class="tree-content">
        {roots.length === 0 ? (
          <div class="tree-empty">No project paths found</div>
        ) : (
          roots.map((root) => (
            <TreeNode
              key={root}
              path={root}
              name={root.split("/").pop() || root}
              isDir={true}
              depth={0}
              onSelectFile={selectFile}
              selectedPath={selectedFilePath}
            />
          ))
        )}
      </div>
    </div>
  );
}

function getRoots(state: ReturnType<typeof useStore.getState>["state"]): string[] {
  if (!state) return [];
  const paths = new Set<string>();

  // From AI chains: agent cwd
  for (const chain of state.ai_chains ?? []) {
    if (chain.agent?.cwd && chain.agent.cwd !== "/" && chain.agent.cwd !== "") {
      paths.add(chain.agent.cwd);
    }
  }

  return [...paths].sort().slice(0, 20); // Limit to 20 roots
}

interface TreeNodeProps {
  path: string;
  name: string;
  isDir: boolean;
  depth: number;
  isSymlink?: boolean;
  onSelectFile: (path: string) => void;
  selectedPath: string | null;
}

function TreeNode({
  path,
  name,
  isDir,
  depth,
  isSymlink,
  onSelectFile,
  selectedPath,
}: TreeNodeProps) {
  const [expanded, setExpanded] = useState(false);
  const [children, setChildren] = useState<FileEntry[] | null>(null);
  const [loading, setLoading] = useState(false);

  const toggle = () => {
    if (!isDir) {
      onSelectFile(path);
      return;
    }
    if (!expanded && children === null) {
      setLoading(true);
      fetch(`/api/tree?root=${encodeURIComponent(path)}`)
        .then((r) => r.json())
        .then((data) => {
          setChildren(data.entries || []);
          setExpanded(true);
        })
        .catch(() => setChildren([]))
        .finally(() => setLoading(false));
    } else {
      setExpanded(!expanded);
    }
  };

  const isSelected = selectedPath === path;
  const indent = depth * 16;

  return (
    <div>
      <div
        class={`tree-item ${isSelected ? "selected" : ""} ${
          isSymlink ? "symlink" : ""
        }`}
        style={{ paddingLeft: `${indent + 8}px` }}
        onClick={toggle}
        role={isDir ? "treeitem" : "option"}
        aria-expanded={isDir ? expanded : undefined}
        aria-selected={isSelected}
      >
        <span class="tree-icon">
          {isDir ? (expanded ? "📂" : "📁") : "📄"}
        </span>
        <span class="tree-name">{name}</span>
        {isSymlink && <span class="tree-symlink">→</span>}
        {loading && <span class="tree-loading">...</span>}
      </div>
      {expanded &&
        children?.map((entry) => (
          <TreeNode
            key={entry.path}
            path={entry.path}
            name={entry.name}
            isDir={entry.type === "directory"}
            depth={depth + 1}
            isSymlink={entry.is_symlink}
            onSelectFile={onSelectFile}
            selectedPath={selectedPath}
          />
        ))}
    </div>
  );
}
