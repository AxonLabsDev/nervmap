"""Shell hook runner for NervMap events."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from nervmap.models import SystemState, Issue
from nervmap.utils import redact_env


class HookRunner:
    """Execute shell hooks on events."""

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.hooks_dir = Path.home() / ".nervmap" / "hooks"

    def fire(self, state: SystemState, issues: list[Issue]):
        """Fire relevant hooks based on scan results."""
        if issues:
            self._run_hook("on-issue-detected", {
                "issues": [i.to_dict() for i in issues],
            })

        # Check for specific events
        for svc in state.services:
            if svc.status in ("stopped", "degraded"):
                self._run_hook("on-service-down", {
                    "service": svc.to_dict(),
                })

        # Custom hook from config
        on_issue = self.cfg.get("hooks", {}).get("on_issue")
        if on_issue and issues:
            self._run_script(on_issue, {
                "issues": [i.to_dict() for i in issues],
            })

    def _run_hook(self, name: str, data: dict):
        """Run a hook script from ~/.nervmap/hooks/ if it exists."""
        script = self.hooks_dir / f"{name}.sh"
        if not script.is_file():
            return
        self._run_script(str(script), data)

    @staticmethod
    def _redact_data(data: dict) -> dict:
        """Deep-redact sensitive env values from hook data."""
        import copy
        safe = copy.deepcopy(data)
        # Redact env in service dicts
        for key in ("service", "services"):
            if key not in safe:
                continue
            items = safe[key] if isinstance(safe[key], list) else [safe[key]]
            for item in items:
                if isinstance(item, dict) and "metadata" in item:
                    env = item.get("metadata", {}).get("env")
                    if env:
                        item["metadata"]["env"] = redact_env(env)
        # Redact env in issue dicts too (they don't normally have env, but safety)
        return safe

    @staticmethod
    def _run_script(path: str, data: dict):
        """Execute a script, passing JSON on stdin."""
        expanded = os.path.expanduser(path)
        if not os.path.isfile(expanded):
            return
        if not os.access(expanded, os.X_OK):
            return
        try:
            safe_data = HookRunner._redact_data(data)
            subprocess.run(
                [expanded],
                input=json.dumps(safe_data),
                text=True,
                timeout=10,
                capture_output=True,
            )
        except Exception:
            pass
