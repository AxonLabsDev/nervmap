"""Network diagnostic rules."""

from __future__ import annotations

import re
import socket

from nervmap.models import SystemState, Issue
from nervmap.config import get_ignored_ports


def check_port_conflict(state: SystemState, cfg: dict) -> list[Issue]:
    """Detect two services claiming the same port."""
    issues: list[Issue] = []
    ignored = get_ignored_ports(cfg)
    port_owners: dict[int, list[str]] = {}

    for svc in state.services:
        for port in svc.ports:
            if port in ignored:
                continue
            port_owners.setdefault(port, []).append(svc.id)

    for port, owners in port_owners.items():
        if len(owners) > 1:
            issues.append(Issue(
                rule_id="port-conflict",
                severity="critical",
                service=owners[0],
                message=f"Port {port} claimed by multiple services: {', '.join(owners)}",
                hint=f"Check which service should own port {port} and reconfigure the other.",
                impact=owners,
            ))

    return issues


def check_port_unreachable(state: SystemState, cfg: dict) -> list[Issue]:
    """Detect declared ports that are not actually listening."""
    issues: list[Issue] = []
    ignored = get_ignored_ports(cfg)
    listening = set(state.listening_ports.keys())

    for svc in state.services:
        if svc.status != "running":
            continue
        for port in svc.ports:
            if port in ignored:
                continue
            if port not in listening:
                issues.append(Issue(
                    rule_id="port-unreachable",
                    severity="warning",
                    service=svc.id,
                    message=f"Service {svc.name} declares port {port} but nothing is listening.",
                    hint=f"Verify {svc.name} is correctly bound to port {port}.",
                    impact=[svc.id],
                ))

    return issues


def check_port_exposed_wildcard(state: SystemState, cfg: dict) -> list[Issue]:
    """Warn about services listening on 0.0.0.0 (all interfaces)."""
    issues: list[Issue] = []
    ignored = get_ignored_ports(cfg)

    for port, bind_addr in state.listening_ports.items():
        if port in ignored:
            continue
        if bind_addr in ("0.0.0.0", "::", "0000:0000:0000:0000:0000:0000:0000:0000"):
            # Find owning service
            owner = None
            for svc in state.services:
                if port in svc.ports:
                    owner = svc.id
                    break
            if owner is None:
                owner = f"unknown:{port}"

            issues.append(Issue(
                rule_id="port-exposed-wildcard",
                severity="info",
                service=owner,
                message=f"Port {port} is listening on all interfaces (0.0.0.0).",
                hint=f"Consider binding to 127.0.0.1 or a specific interface for security.",
                impact=[owner],
            ))

    return issues


def check_connection_refused(state: SystemState, cfg: dict) -> list[Issue]:
    """Check if known dependency ports accept connections."""
    issues: list[Issue] = []
    timeout = cfg.get("timeouts", {}).get("tcp", 3)
    checked: set[int] = set()

    for conn in state.connections:
        port = conn.target_port
        if port is None or port in checked:
            continue
        checked.add(port)

        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(min(timeout, 2))
            result = s.connect_ex(("127.0.0.1", port))
            s.close()
            if result != 0:
                issues.append(Issue(
                    rule_id="connection-refused",
                    severity="critical",
                    service=conn.target,
                    message=f"Connection refused on port {port} (target: {conn.target}).",
                    hint=f"Ensure {conn.target} is running and listening on port {port}.",
                    impact=[conn.source, conn.target],
                ))
        except Exception:
            pass

    return issues
