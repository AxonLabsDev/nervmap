"""Systemd service discovery via systemctl."""

from __future__ import annotations
import logging
logger = logging.getLogger("nervmap.systemd")

import json as json_mod
import subprocess
import re

from nervmap.models import Service


class SystemdCollector:
    """Discover running systemd services."""

    def collect(self) -> list[Service]:
        units = self._list_units()
        services: list[Service] = []
        for u in units:
            try:
                services.append(self._to_service(u))
            except Exception:
                continue
        return services

    def _list_units(self) -> list[dict]:
        """Get list of service units from systemctl."""
        # Try JSON output first (systemd 248+)
        try:
            result = subprocess.run(
                ["systemctl", "list-units", "--type=service", "--all",
                 "--no-pager", "--output=json"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0 and result.stdout.strip().startswith("["):
                return json_mod.loads(result.stdout)
        except Exception:
            logger.debug("Systemd parse error", exc_info=True)

        # Fallback: text parsing
        try:
            result = subprocess.run(
                ["systemctl", "list-units", "--type=service", "--all",
                 "--no-pager", "--plain", "--no-legend"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode != 0:
                return []
            return self._parse_text(result.stdout)
        except Exception:
            return []

    @staticmethod
    def _parse_text(output: str) -> list[dict]:
        """Parse plain-text systemctl output into list of dicts."""
        units: list[dict] = []
        for line in output.strip().splitlines():
            parts = line.split(None, 4)
            if len(parts) < 4:
                continue
            unit_name = parts[0].strip()
            # Skip non-service entries
            if not unit_name.endswith(".service"):
                continue
            load = parts[1] if len(parts) > 1 else "unknown"
            active = parts[2] if len(parts) > 2 else "unknown"
            sub = parts[3] if len(parts) > 3 else "unknown"
            desc = parts[4] if len(parts) > 4 else ""
            units.append({
                "unit": unit_name,
                "load": load,
                "active": active,
                "sub": sub,
                "description": desc,
            })
        return units

    def _to_service(self, u: dict) -> Service:
        unit_name = u.get("unit", "unknown")
        # Strip .service suffix for display
        display_name = re.sub(r"\.service$", "", unit_name)
        active = u.get("active", "unknown")
        sub = u.get("sub", "unknown")

        status = self._map_status(active, sub)

        # Try to get MainPID
        pid = self._get_pid(unit_name)

        meta: dict = {
            "unit": unit_name,
            "active": active,
            "sub": sub,
            "description": u.get("description", ""),
            "load": u.get("load", ""),
        }

        return Service(
            id=f"systemd:{display_name}",
            name=display_name,
            type="systemd",
            status=status,
            ports=[],
            pid=pid,
            health="no_check",
            metadata=meta,
        )

    @staticmethod
    def _map_status(active: str, sub: str) -> str:
        if active == "active" and sub == "running":
            return "running"
        elif active == "active":
            return "running"
        elif active == "failed":
            return "stopped"
        elif active == "activating":
            return "degraded"
        elif active == "inactive":
            return "stopped"
        return "unknown"

    @staticmethod
    def _get_pid(unit_name: str) -> int | None:
        try:
            result = subprocess.run(
                ["systemctl", "show", unit_name, "--property=MainPID", "--value"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                pid = int(result.stdout.strip())
                return pid if pid > 0 else None
        except Exception:
            logger.debug("Systemd PID lookup error", exc_info=True)
        return None
