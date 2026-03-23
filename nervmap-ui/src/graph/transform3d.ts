/** Transform NervMap JSON data into 3d-force-graph format */

import type { NervMapState, Service, Connection, AIChain } from "../types";

export interface GraphNode {
  id: string;
  name: string;
  type: string;       // docker | systemd | process | ai | ai-backend | group
  status: string;
  group: string;      // grouping key for clustering
  val: number;        // node size
  color: string;
  ports?: string;
  health?: string;
}

export interface GraphLink {
  source: string;
  target: string;
  type: string;       // declared | tcp | inferred | association | ai
  confidence: number;
  color: string;
  curvature?: number;
}

export interface GraphData {
  nodes: GraphNode[];
  links: GraphLink[];
}

// Color palette by service type
const TYPE_COLORS: Record<string, string> = {
  docker: "#2496ED",
  systemd: "#4CAF50",
  process: "#FF9800",
  ai: "#9C27B0",
  "ai-backend": "#00BCD4",
  group: "#334155",
};

const STATUS_COLORS: Record<string, string> = {
  running: "",         // use type color
  stopped: "#EF4444",
  failed: "#EF4444",
  degraded: "#F59E0B",
};

const EDGE_COLORS: Record<string, string> = {
  declared: "#3B82F6",
  tcp: "#22C55E",
  inferred: "#94A3B8",
  association: "#334155",
  ai: "#A78BFA",
};

export function scanToGraphData(
  data: NervMapState,
  scopePath?: string,
): GraphData {
  const nodes: GraphNode[] = [];
  const links: GraphLink[] = [];
  const nodeIds = new Set<string>();

  // Filter services by scope (strict type match from breadcrumb)
  let services = data.services;
  if (scopePath) {
    services = services.filter((s) => s.type === scopePath);
  }

  // Service nodes
  for (const svc of services) {
    const color = STATUS_COLORS[svc.status] || TYPE_COLORS[svc.type] || "#64748B";
    nodes.push({
      id: svc.id,
      name: svc.name,
      type: svc.type,
      status: svc.status,
      group: svc.type,
      val: svc.status === "running" ? 2 : 1,
      color,
      ports: svc.ports.join(", "),
      health: svc.health,
    });
    nodeIds.add(svc.id);
  }

  // AI chain nodes
  if (data.ai_chains) {
    for (const chain of data.ai_chains) {
      if (!chain.agent) continue;

      // Agent node (if not already a service)
      if (!nodeIds.has(chain.id)) {
        nodes.push({
          id: chain.id,
          name: chain.agent.display_name || chain.agent.agent_type,
          type: "ai",
          status: chain.status,
          group: "ai",
          val: 3,
          color: TYPE_COLORS.ai,
        });
        nodeIds.add(chain.id);
      }

      // Backend node
      if (chain.backend && chain.backend.backend_type === "local") {
        const bkId = `${chain.id}:backend`;
        if (!nodeIds.has(bkId)) {
          nodes.push({
            id: bkId,
            name: chain.backend.model_name || chain.backend.provider,
            type: "ai-backend",
            status: "running",
            group: "ai",
            val: 4,
            color: TYPE_COLORS["ai-backend"],
          });
          nodeIds.add(bkId);
        }
        links.push({
          source: chain.id,
          target: bkId,
          type: "ai",
          confidence: 1.0,
          color: EDGE_COLORS.ai,
        });
      }
    }
  }

  // Connection links (only if both endpoints exist in filtered nodes)
  for (const conn of data.connections) {
    if (nodeIds.has(conn.source) && nodeIds.has(conn.target)) {
      links.push({
        source: conn.source,
        target: conn.target,
        type: conn.type,
        confidence: conn.confidence,
        color: EDGE_COLORS[conn.type] || "#475569",
        curvature: conn.type === "association" ? 0.3 : 0,
      });
    }
  }

  return { nodes, links };
}

/** Get unique service types for scope breadcrumb */
export function getServiceTypes(data: NervMapState): string[] {
  const types = new Set<string>();
  for (const svc of data.services) {
    types.add(svc.type);
  }
  return [...types].sort();
}
