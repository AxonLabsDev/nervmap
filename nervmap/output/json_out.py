"""JSON output renderer for NervMap."""

from __future__ import annotations

import json
import sys

from nervmap import __version__
from nervmap.models import SystemState, Issue
from nervmap.utils import redact_env


class JsonRenderer:
    """Machine-readable JSON output."""

    def render(self, state: SystemState, issues: list[Issue], elapsed: float,
               show_secrets: bool = False):
        """Write full scan result as JSON to stdout."""
        services_data = []
        for s in state.services:
            d = s.to_dict()
            if not show_secrets and "env" in d.get("metadata", {}):
                d["metadata"]["env"] = redact_env(d["metadata"]["env"])
            services_data.append(d)
        output = {
            "version": __version__,
            "elapsed_seconds": round(elapsed, 2),
            "services": services_data,
            "connections": [c.to_dict() for c in state.connections],
            "issues": [i.to_dict() for i in issues],
            "summary": {
                "total_services": len(state.services),
                "total_connections": len(state.connections),
                "total_issues": len(issues),
                "critical": sum(1 for i in issues if i.severity == "critical"),
                "warnings": sum(1 for i in issues if i.severity == "warning"),
                "info": sum(1 for i in issues if i.severity == "info"),
            },
            "disk_usage": state.disk_usage,
            "memory": state.memory,
        }
        if state.projects:
            output["projects"] = [p.to_dict() for p in state.projects]
            # Cross-references: code -> infra connections
            connections_to_infra = []
            for proj in state.projects:
                for env_ref in proj.env_refs:
                    for svc_id in proj.linked_services:
                        connections_to_infra.append({
                            "from": proj.path,
                            "to": svc_id,
                            "via": env_ref,
                        })
            if connections_to_infra:
                output["connections_to_infra"] = connections_to_infra
        if state.ai_chains:
            output["ai_chains"] = [c.to_dict() for c in state.ai_chains]
        json.dump(output, sys.stdout, indent=2, default=str)
        sys.stdout.write("\n")
