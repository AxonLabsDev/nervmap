/** Cytoscape.js stylesheet */

import type { Stylesheet } from "cytoscape";

export const GRAPH_STYLES: Stylesheet[] = [
  // Nodes
  {
    selector: "node",
    style: {
      label: "data(label)",
      "text-valign": "bottom",
      "text-halign": "center",
      "font-size": "10px",
      "font-family": "system-ui, sans-serif",
      color: "#e2e8f0",
      "text-margin-y": 5,
      width: 32,
      height: 32,
      "border-width": 2,
      "background-opacity": 0.9,
    },
  },
  // Docker
  {
    selector: 'node[type="docker"]',
    style: {
      "background-color": "#2496ED",
      "border-color": "#1a6fb5",
      shape: "round-rectangle",
    },
  },
  // Systemd
  {
    selector: 'node[type="systemd"]',
    style: {
      "background-color": "#4CAF50",
      "border-color": "#357a38",
      shape: "ellipse",
    },
  },
  // Process
  {
    selector: 'node[type="process"]',
    style: {
      "background-color": "#FF9800",
      "border-color": "#c77700",
      shape: "diamond",
    },
  },
  // AI
  {
    selector: 'node[type="ai"]',
    style: {
      "background-color": "#9C27B0",
      "border-color": "#7b1fa2",
      shape: "star",
    },
  },
  // AI Backend
  {
    selector: 'node[type="ai-backend"]',
    style: {
      "background-color": "#00BCD4",
      "border-color": "#00838f",
      shape: "hexagon",
    },
  },
  // Status: stopped/failed
  {
    selector: 'node[status="stopped"], node[status="failed"]',
    style: {
      "background-color": "#EF4444",
      "border-color": "#dc2626",
    },
  },
  // Status: degraded
  {
    selector: 'node[status="degraded"]',
    style: {
      "background-color": "#F59E0B",
      "border-color": "#d97706",
    },
  },
  // Group/compound
  {
    selector: ":parent",
    style: {
      "background-opacity": 0.05,
      "border-width": 1,
      "border-color": "#334155",
      "border-style": "dashed",
      label: "data(label)",
      "text-valign": "top",
      "font-size": "12px",
      color: "#64748b",
      padding: "16px",
    },
  },
  // Edges
  {
    selector: "edge",
    style: {
      width: 1.5,
      "line-color": "#475569",
      "target-arrow-color": "#475569",
      "target-arrow-shape": "triangle",
      "curve-style": "bezier",
      "arrow-scale": 0.7,
    },
  },
  // Declared (depends_on)
  {
    selector: 'edge[type="declared"]',
    style: { "line-color": "#3b82f6", "target-arrow-color": "#3b82f6" },
  },
  // TCP
  {
    selector: 'edge[type="tcp"]',
    style: { "line-color": "#22c55e", "target-arrow-color": "#22c55e" },
  },
  // Inferred
  {
    selector: 'edge[type="inferred"]',
    style: {
      "line-color": "#94a3b8",
      "target-arrow-color": "#94a3b8",
      "line-style": "dashed",
    },
  },
  // Association
  {
    selector: 'edge[type="association"]',
    style: {
      "line-color": "#334155",
      "target-arrow-color": "#334155",
      "line-style": "dotted",
      opacity: 0.4,
    },
  },
  // Symlink
  {
    selector: 'edge[type="symlink"]',
    style: {
      "line-style": "dotted",
      "line-color": "#ce93d8",
      "target-arrow-color": "#ce93d8",
      "target-arrow-shape": "diamond",
    },
  },
  // Highlight classes
  {
    selector: ".faded",
    style: { opacity: 0.12 },
  },
  {
    selector: ".highlighted",
    style: { opacity: 1, "z-index": 10 },
  },
];
