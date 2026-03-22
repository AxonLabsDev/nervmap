/** Transform NervMap JSON data into Cytoscape.js elements */

import type { NervMapState } from "../types";
import type { ElementDefinition } from "cytoscape";

export function scanToElements(data: NervMapState): ElementDefinition[] {
  const elements: ElementDefinition[] = [];
  const typeGroups = new Set<string>();

  // Compound parent nodes by service type
  for (const svc of data.services) {
    typeGroups.add(svc.type);
  }
  for (const t of typeGroups) {
    elements.push({
      group: "nodes",
      data: { id: `group:${t}`, label: t.toUpperCase(), isGroup: true },
    });
  }

  // Service nodes
  for (const svc of data.services) {
    elements.push({
      group: "nodes",
      data: {
        id: svc.id,
        label: svc.name,
        type: svc.type,
        status: svc.status,
        health: svc.health,
        ports: svc.ports.join(", "),
        parent: `group:${svc.type}`,
      },
    });
  }

  // AI chain nodes
  if (data.ai_chains) {
    for (const chain of data.ai_chains) {
      if (!chain.agent) continue;
      const nodeId = chain.id;

      // Only add if not already a service
      const exists = data.services.some((s) => s.id === nodeId);
      if (!exists) {
        elements.push({
          group: "nodes",
          data: {
            id: nodeId,
            label: chain.agent.display_name || chain.agent.agent_type,
            type: "ai",
            status: chain.status,
            health: "no_check",
          },
        });
      }

      // Backend node
      if (chain.backend && chain.backend.backend_type === "local") {
        const bkId = `${chain.id}:backend`;
        elements.push({
          group: "nodes",
          data: {
            id: bkId,
            label: chain.backend.model_name || chain.backend.provider,
            type: "ai-backend",
            status: "running",
          },
        });
        elements.push({
          group: "edges",
          data: {
            id: `e:${nodeId}->${bkId}`,
            source: nodeId,
            target: bkId,
            type: "ai",
          },
        });
      }
    }
  }

  // Connection edges
  for (const conn of data.connections) {
    elements.push({
      group: "edges",
      data: {
        id: `e:${conn.source}->${conn.target}:${conn.target_port ?? ""}`,
        source: conn.source,
        target: conn.target,
        type: conn.type,
        confidence: conn.confidence,
        label: conn.target_port ? `:${conn.target_port}` : "",
      },
    });
  }

  return elements;
}
