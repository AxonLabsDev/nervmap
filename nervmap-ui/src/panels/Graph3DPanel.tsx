/** 3D Force Graph panel using 3d-force-graph + Three.js */

import { useRef, useEffect } from "preact/hooks";
import ForceGraph3D from "3d-force-graph";
import * as THREE from "three";
import { useStore } from "../store";
import { scanToGraphData, getServiceTypes } from "../graph/transform3d";
import type { GraphNode } from "../graph/transform3d";

// Geometry cache — shared across renders, never recreated
const GEOM_CACHE = new Map<string, THREE.BufferGeometry>();

function getGeometry(type: string, size: number): THREE.BufferGeometry {
  const key = `${type}-${size}`;
  if (!GEOM_CACHE.has(key)) {
    let geom: THREE.BufferGeometry;
    switch (type) {
      case "docker":
        geom = new THREE.BoxGeometry(size, size, size);
        break;
      case "systemd":
        geom = new THREE.SphereGeometry(size / 2, 16, 16);
        break;
      case "process":
        geom = new THREE.ConeGeometry(size / 2, size, 8);
        break;
      case "ai":
        geom = new THREE.DodecahedronGeometry(size / 2);
        break;
      case "ai-backend":
        geom = new THREE.OctahedronGeometry(size / 2);
        break;
      default:
        geom = new THREE.SphereGeometry(size / 2, 12, 12);
    }
    GEOM_CACHE.set(key, geom);
  }
  return GEOM_CACHE.get(key)!;
}

// Material pool for reuse — dispose old on highlight change
let materialPool: THREE.MeshLambertMaterial[] = [];

function createNodeObject(node: GraphNode, opacity: number = 0.85): THREE.Mesh {
  const size = Math.max(3, node.val * 2);
  const geometry = getGeometry(node.type, size);
  const material = new THREE.MeshLambertMaterial({
    color: node.color,
    transparent: true,
    opacity,
  });
  materialPool.push(material);
  return new THREE.Mesh(geometry, material);
}

function disposeMaterials() {
  for (const mat of materialPool) {
    mat.dispose();
  }
  materialPool = [];
}

/** Escape HTML to prevent XSS in node labels */
function escapeHtml(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

export function Graph3DPanel() {
  const containerRef = useRef<HTMLDivElement>(null);
  const graphRef = useRef<any>(null);
  const state = useStore((s) => s.state);
  const highlightedIds = useStore((s) => s.highlightedIds);
  const scopePath = useStore((s) => s.scopePath);

  // Stable store action refs (Zustand guarantees stability)
  const selectNode = useStore.getState().selectNode;
  const clearSelection = useStore.getState().clearSelection;
  const setScopePath = useStore.getState().setScopePath;

  // Initialize 3D graph
  useEffect(() => {
    if (!containerRef.current) return;

    let graph: any;
    try {
      graph = ForceGraph3D()(containerRef.current)
        .backgroundColor("#0f172a")
        .nodeLabel((node: any) => {
          const n = node as GraphNode;
          const name = escapeHtml(n.name);
          const type = escapeHtml(n.type);
          const status = escapeHtml(n.status);
          let label = `<b>${name}</b><br/>Type: ${type}<br/>Status: ${status}`;
          if (n.ports) label += `<br/>Ports: ${escapeHtml(n.ports)}`;
          return label;
        })
        .nodeThreeObject((node: any) => createNodeObject(node as GraphNode))
        .nodeThreeObjectExtend(false)
        .linkColor((link: any) => link.color)
        .linkOpacity(0.5)
        .linkWidth((link: any) => (link.type === "declared" ? 2 : 0.5))
        .linkCurvature((link: any) => link.curvature || 0)
        .linkDirectionalArrowLength(3)
        .linkDirectionalArrowRelPos(1)
        .linkDirectionalArrowColor((link: any) => link.color)
        .linkHoverPrecision(8) // fat-finger tolerance on mobile
        .onNodeClick((node: any) => {
          if (node) {
            selectNode(node.id);
            // Animate camera to focus on clicked node
            const hyp = Math.hypot(node.x || 0, node.y || 0, node.z || 0);
            const distance = 120;
            const distRatio = hyp > 0.01 ? 1 + distance / hyp : 1;
            graph.cameraPosition(
              {
                x: (node.x || 0) * distRatio,
                y: (node.y || 0) * distRatio,
                z: (node.z || 0) * distRatio,
              },
              node,
              1000,
            );
          }
        })
        .onBackgroundClick(() => clearSelection())
        .enableNodeDrag(true)
        .enableNavigationControls(true)
        .showNavInfo(false);
    } catch (err) {
      // WebGL not available
      if (containerRef.current) {
        containerRef.current.innerHTML =
          '<div style="color:#94a3b8;text-align:center;padding:40px">WebGL not available. Use a modern browser.</div>';
      }
      return;
    }

    graphRef.current = graph;

    // Handle container resize
    const observer = new ResizeObserver(() => {
      if (containerRef.current) {
        graph.width(containerRef.current.clientWidth);
        graph.height(containerRef.current.clientHeight);
      }
    });
    observer.observe(containerRef.current);

    return () => {
      observer.disconnect();
      // Proper cleanup: dispose WebGL renderer + remove canvas
      try {
        const renderer = graph.renderer();
        graph._destructor();
        if (renderer) renderer.dispose();
      } catch {}
      disposeMaterials();
      if (containerRef.current) {
        containerRef.current.innerHTML = "";
      }
      graphRef.current = null;
    };
  }, []);

  // Update data when state or scope changes
  useEffect(() => {
    const graph = graphRef.current;
    if (!graph || !state) return;

    disposeMaterials(); // clean old materials before re-render
    const data = scanToGraphData(state, scopePath ?? undefined);
    graph.graphData(data);
  }, [state, scopePath]);

  // Highlight on selection
  useEffect(() => {
    const graph = graphRef.current;
    if (!graph) return;

    disposeMaterials();
    graph.nodeThreeObject((node: any) => {
      const n = node as GraphNode;
      const highlighted =
        highlightedIds.size === 0 || highlightedIds.has(n.id);
      return createNodeObject(n, highlighted ? 0.85 : 0.08);
    });

    graph.linkOpacity((link: any) => {
      if (highlightedIds.size === 0) return 0.5;
      const srcId =
        typeof link.source === "object" ? link.source.id : link.source;
      const tgtId =
        typeof link.target === "object" ? link.target.id : link.target;
      return highlightedIds.has(srcId) || highlightedIds.has(tgtId)
        ? 0.9
        : 0.05;
    });
  }, [highlightedIds]);

  // Scope breadcrumb
  const types = state ? getServiceTypes(state) : [];

  return (
    <div class="panel graph-panel">
      <div class="panel-header">
        <div class="breadcrumb">
          <button
            class={`crumb ${!scopePath ? "active" : ""}`}
            onClick={() => setScopePath(null)}
          >
            All
          </button>
          {types.map((t) => (
            <button
              key={t}
              class={`crumb ${scopePath === t ? "active" : ""}`}
              onClick={() => setScopePath(scopePath === t ? null : t)}
            >
              {t}
            </button>
          ))}
        </div>
        {state && (
          <span class="badge">
            {scopePath
              ? state.services.filter(
                  (s) => s.type === scopePath,
                ).length
              : state.summary.total_services}{" "}
            nodes
          </span>
        )}
      </div>
      <div ref={containerRef} class="graph-canvas" />
    </div>
  );
}
