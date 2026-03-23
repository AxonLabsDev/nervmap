/** 3D Force Graph panel using 3d-force-graph + Three.js */

import { useRef, useEffect } from "preact/hooks";
import ForceGraph3D from "3d-force-graph";
import * as THREE from "three";
import { useStore } from "../store";
import { scanToGraphData, getServiceTypes } from "../graph/transform3d";
import type { GraphNode } from "../graph/transform3d";

// Node geometry by type
function createNodeObject(node: GraphNode): THREE.Object3D {
  const size = Math.max(3, node.val * 2);
  let geometry: THREE.BufferGeometry;

  switch (node.type) {
    case "docker":
      geometry = new THREE.BoxGeometry(size, size, size);
      break;
    case "systemd":
      geometry = new THREE.SphereGeometry(size / 2, 16, 16);
      break;
    case "process":
      geometry = new THREE.ConeGeometry(size / 2, size, 8);
      break;
    case "ai":
      geometry = new THREE.DodecahedronGeometry(size / 2);
      break;
    case "ai-backend":
      geometry = new THREE.OctahedronGeometry(size / 2);
      break;
    default:
      geometry = new THREE.SphereGeometry(size / 2, 12, 12);
  }

  const material = new THREE.MeshLambertMaterial({
    color: node.color,
    transparent: true,
    opacity: 0.85,
  });

  return new THREE.Mesh(geometry, material);
}

export function Graph3DPanel() {
  const containerRef = useRef<HTMLDivElement>(null);
  const graphRef = useRef<any>(null);
  const state = useStore((s) => s.state);
  const highlightedIds = useStore((s) => s.highlightedIds);
  const selectNode = useStore((s) => s.selectNode);
  const clearSelection = useStore((s) => s.clearSelection);
  const scopePath = useStore((s) => s.scopePath);
  const setScopePath = useStore((s) => s.setScopePath);

  // Initialize 3D graph
  useEffect(() => {
    if (!containerRef.current) return;

    const graph = ForceGraph3D()(containerRef.current)
      .backgroundColor("#0f172a")
      .nodeLabel((node: any) => {
        const n = node as GraphNode;
        let label = `<b>${n.name}</b><br/>Type: ${n.type}<br/>Status: ${n.status}`;
        if (n.ports) label += `<br/>Ports: ${n.ports}`;
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
      .onNodeClick((node: any) => {
        if (node) {
          selectNode(node.id);
          // Animate camera to focus on clicked node
          const distance = 120;
          const distRatio =
            1 + distance / Math.hypot(node.x || 0, node.y || 0, node.z || 0);
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
      graph._destructor?.();
    };
  }, []);

  // Update data when state or scope changes
  useEffect(() => {
    const graph = graphRef.current;
    if (!graph || !state) return;

    const data = scanToGraphData(state, scopePath ?? undefined);
    graph.graphData(data);
  }, [state, scopePath]);

  // Highlight on selection
  useEffect(() => {
    const graph = graphRef.current;
    if (!graph) return;

    // Re-render node objects with highlight
    graph.nodeThreeObject((node: any) => {
      const n = node as GraphNode;
      const highlighted =
        highlightedIds.size === 0 || highlightedIds.has(n.id);
      const obj = createNodeObject(n);
      if (!highlighted && highlightedIds.size > 0) {
        (obj as THREE.Mesh).material = new THREE.MeshLambertMaterial({
          color: n.color,
          transparent: true,
          opacity: 0.1,
        });
      }
      return obj;
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
                  (s) => s.type === scopePath || s.id.includes(scopePath),
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
