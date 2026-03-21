"""JSON output renderer for NervMap."""

from __future__ import annotations

import json
import sys

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
            "version": "0.1.0",
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
        json.dump(output, sys.stdout, indent=2, default=str)
        sys.stdout.write("\n")
