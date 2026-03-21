"""Dependency diagnostic rules."""

from __future__ import annotations

import re

from nervmap.models import SystemState, Issue


def check_dependency_down(state: SystemState, cfg: dict) -> list[Issue]:
    """Detect services that depend on a stopped/failed service."""
    issues: list[Issue] = []

    for conn in state.connections:
        target_svc = state.service_by_id(conn.target)
        source_svc = state.service_by_id(conn.source)

        if target_svc is None or source_svc is None:
            continue

        if target_svc.status in ("stopped", "unknown") and source_svc.status == "running":
            issues.append(Issue(
                rule_id="dependency-down",
                severity="critical",
                service=source_svc.id,
                message=f"{source_svc.name} depends on {target_svc.name}, but it is {target_svc.status}.",
                hint=f"Start {target_svc.name}: docker start {target_svc.name} / systemctl start {target_svc.metadata.get('unit', target_svc.name)}",
                impact=[source_svc.id, target_svc.id],
            ))

    return issues


def check_env_port_mismatch(state: SystemState, cfg: dict) -> list[Issue]:
    """Detect env vars pointing to a port where a different service listens."""
    issues: list[Issue] = []

    for svc in state.services:
        env = svc.metadata.get("env", {})
        if not env:
            continue

        for key, value in env.items():
            # Look for port references in env vars
            port_match = re.search(r':(\d{2,5})(?:/|$|\?)', str(value))
            if not port_match:
                continue

            try:
                port = int(port_match.group(1))
            except ValueError:
                continue

            # Check if that port is listening
            if port not in state.listening_ports:
                issues.append(Issue(
                    rule_id="env-port-mismatch",
                    severity="warning",
                    service=svc.id,
                    message=f"{svc.name} env {key} references port {port}, but nothing is listening there.",
                    hint=f"Verify the value of {key} ({value}) or start the expected service on port {port}.",
                    impact=[svc.id],
                ))

    return issues


def check_circular_dependency(state: SystemState, cfg: dict) -> list[Issue]:
    """Detect circular dependencies: A -> B -> ... -> A."""
    issues: list[Issue] = []

    # Build adjacency list from connections
    graph: dict[str, set[str]] = {}
    for conn in state.connections:
        graph.setdefault(conn.source, set()).add(conn.target)

    # DFS cycle detection
    visited: set[str] = set()
    in_stack: set[str] = set()
    cycles_found: set[tuple[str, ...]] = set()

    def _dfs(node: str, path: list[str]):
        if node in in_stack:
            # Found cycle — extract it
            cycle_start = path.index(node)
            cycle = tuple(sorted(path[cycle_start:]))
            if cycle not in cycles_found:
                cycles_found.add(cycle)
                cycle_path = path[cycle_start:] + [node]
                chain = " -> ".join(cycle_path)
                issues.append(Issue(
                    rule_id="circular-dependency",
                    severity="warning",
                    service=node,
                    message=f"Circular dependency detected: {chain}",
                    hint="Break the cycle by removing one dependency or using async communication.",
                    impact=list(path[cycle_start:]),
                ))
            return
        if node in visited:
            return

        visited.add(node)
        in_stack.add(node)
        path.append(node)

        for neighbor in graph.get(node, []):
            _dfs(neighbor, path)

        path.pop()
        in_stack.discard(node)

    for node in graph:
        if node not in visited:
            _dfs(node, [])

    return issues
