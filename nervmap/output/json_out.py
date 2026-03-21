"""JSON output renderer for NervMap."""

from __future__ import annotations

import json
import sys

from nervmap.models import SystemState, Issue


class JsonRenderer:
    """Machine-readable JSON output."""

    def render(self, state: SystemState, issues: list[Issue], elapsed: float):
        """Write full scan result as JSON to stdout."""
        output = {
            "version": "0.1.0",
            "elapsed_seconds": round(elapsed, 2),
            "services": [s.to_dict() for s in state.services],
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
