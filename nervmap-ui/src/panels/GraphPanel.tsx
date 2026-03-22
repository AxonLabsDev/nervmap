/** Cytoscape.js graph panel */

import { useRef, useEffect } from "preact/hooks";
import cytoscape from "cytoscape";
import fcose from "cytoscape-fcose";
import { useStore } from "../store";
import { GRAPH_STYLES } from "../graph/styles";
import { scanToElements } from "../graph/transform";

cytoscape.use(fcose);

const FCOSE_LAYOUT = {
  name: "fcose",
  animate: true,
  animationDuration: 400,
  fit: true,
  padding: 40,
  nodeSeparation: 100,
  nodeRepulsion: () => 5000,
  idealEdgeLength: () => 100,
  gravity: 0.3,
  nestingFactor: 0.15,
  quality: "default" as const,
};

export function GraphPanel() {
  const containerRef = useRef<HTMLDivElement>(null);
  const cyRef = useRef<cytoscape.Core | null>(null);
  const state = useStore((s) => s.state);
  const highlightedIds = useStore((s) => s.highlightedIds);
  const selectNode = useStore((s) => s.selectNode);
  const clearSelection = useStore((s) => s.clearSelection);

  // Init Cytoscape
  useEffect(() => {
    if (!containerRef.current) return;
    const cy = cytoscape({
      container: containerRef.current,
      style: GRAPH_STYLES,
      minZoom: 0.1,
      maxZoom: 4,
      wheelSensitivity: 0.3,
    });

    cy.on("tap", "node[!isGroup]", (e) => selectNode(e.target.id()));
    cy.on("tap", (e) => {
      if (e.target === cy) clearSelection();
    });

    cyRef.current = cy;
    return () => cy.destroy();
  }, []);

  // Update elements when data changes
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy || !state) return;

    const elements = scanToElements(state);
    cy.batch(() => {
      cy.elements().remove();
      cy.add(elements);
    });
    cy.layout(FCOSE_LAYOUT).run();
  }, [state]);

  // Highlight chain
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;

    cy.batch(() => {
      if (highlightedIds.size === 0) {
        cy.elements().removeClass("faded highlighted");
        return;
      }
      cy.elements().addClass("faded").removeClass("highlighted");
      const nodes = cy.nodes().filter((n) => highlightedIds.has(n.id()));
      const edges = nodes.edgesWith(nodes);
      nodes.removeClass("faded").addClass("highlighted");
      edges.removeClass("faded").addClass("highlighted");
    });
  }, [highlightedIds]);

  return (
    <div class="panel graph-panel">
      <div class="panel-header">
        <span>Infrastructure Graph</span>
        {state && (
          <span class="badge">
            {state.summary.total_services} services
          </span>
        )}
      </div>
      <div ref={containerRef} class="graph-canvas" />
    </div>
  );
}
