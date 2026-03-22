"""Code-related diagnostic rules — cross-reference source code and infrastructure."""

from __future__ import annotations

import importlib.util
import json
import logging
import os
import re

from nervmap.models import SystemState, Issue
from nervmap.source.parsers.config_parser import parse_env_file

logger = logging.getLogger("nervmap.rules.code")


def check_code_port_drift(state: SystemState, cfg: dict) -> list[Issue]:
    """Detect when port in source code != port in runtime."""
    issues: list[Issue] = []
    projects = getattr(state, "projects", [])
    if not projects:
        return issues

    for proj in projects:
        if not proj.port_bindings or not proj.linked_services:
            continue

        code_ports = set(proj.port_bindings)
        for svc_id in proj.linked_services:
            svc = state.service_by_id(svc_id)
            if svc is None:
                continue
            runtime_ports = set(svc.ports)
            if not runtime_ports:
                continue

            # Check if code ports and runtime ports have no overlap
            if code_ports and runtime_ports and not code_ports & runtime_ports:
                issues.append(Issue(
                    rule_id="code-port-drift",
                    severity="warning",
                    service=svc_id,
                    message=f"Port mismatch in {proj.name}: code uses {sorted(code_ports)}, runtime has {sorted(runtime_ports)}.",
                    hint=f"Check port configuration in {proj.path} and docker-compose.yml.",
                    impact=[svc_id],
                ))

    return issues


def check_code_env_missing(state: SystemState, cfg: dict) -> list[Issue]:
    """Detect env vars referenced in code but not defined anywhere."""
    issues: list[Issue] = []
    projects = getattr(state, "projects", [])
    if not projects:
        return issues

    for proj in projects:
        if not proj.env_refs:
            continue

        # Collect all known env vars for this project
        known_env: set[str] = set()

        # From .env file
        env_file = proj.metadata.get("env_file", "")
        if not env_file:
            env_file = os.path.join(proj.path, ".env")
        if os.path.isfile(env_file):
            known_env.update(parse_env_file(env_file).keys())

        # From linked service runtime env
        for svc_id in proj.linked_services:
            svc = state.service_by_id(svc_id)
            if svc:
                svc_env = svc.metadata.get("env", {})
                known_env.update(svc_env.keys())

        # Find missing vars
        missing = [v for v in proj.env_refs if v not in known_env]
        if missing:
            issues.append(Issue(
                rule_id="code-env-missing",
                severity="warning",
                service=proj.linked_services[0] if proj.linked_services else proj.name,
                message=f"Code in {proj.name} references undefined env vars: {', '.join(sorted(missing))}.",
                hint=f"Add these to .env or docker-compose environment: {', '.join(sorted(missing))}",
                impact=proj.linked_services or [proj.name],
            ))

    return issues


def check_code_dep_missing(state: SystemState, cfg: dict) -> list[Issue]:
    """Detect declared dependencies that may not be importable."""
    issues: list[Issue] = []
    projects = getattr(state, "projects", [])
    if not projects:
        return issues

    for proj in projects:
        if not proj.dependencies or proj.language != "python":
            continue

        for dep in proj.dependencies:
            # Normalize: pip package names use hyphens, import uses underscores
            import_name = dep.replace("-", "_").lower()
            # Use find_spec instead of __import__ to avoid executing module code
            spec = importlib.util.find_spec(import_name)
            if spec is None:
                spec = importlib.util.find_spec(dep)
            if spec is None:
                issues.append(Issue(
                    rule_id="code-dep-missing",
                    severity="info",
                    service=proj.linked_services[0] if proj.linked_services else proj.name,
                    message=f"Dependency '{dep}' in {proj.name} may not be installed.",
                    hint=f"Install: pip install {dep}",
                    impact=proj.linked_services or [proj.name],
                ))

    return issues


def check_code_entrypoint_mismatch(state: SystemState, cfg: dict) -> list[Issue]:
    """Detect Dockerfile CMD/ENTRYPOINT pointing to a file that doesn't exist."""
    issues: list[Issue] = []
    projects = getattr(state, "projects", [])
    if not projects:
        return issues

    for proj in projects:
        for key in ("dockerfile_cmd", "dockerfile_entrypoint"):
            cmd_str = proj.metadata.get(key, "")
            if not cmd_str:
                continue

            # Extract filename from CMD/ENTRYPOINT
            # Formats: ["python", "main.py"] or "python main.py"
            filenames = _extract_filenames_from_cmd(cmd_str)
            for fname in filenames:
                # Skip interpreters and flags
                if fname in ("python", "python3", "node", "npm", "go", "java",
                             "sh", "bash", "/bin/sh", "/bin/bash", "ruby", "perl"):
                    continue
                if fname.startswith("-"):
                    continue

                filepath = os.path.join(proj.path, fname)
                if not os.path.isfile(filepath):
                    issues.append(Issue(
                        rule_id="code-entrypoint-mismatch",
                        severity="warning",
                        service=proj.linked_services[0] if proj.linked_services else proj.name,
                        message=f"Dockerfile entrypoint '{fname}' not found in {proj.path}.",
                        hint=f"Create {fname} or update Dockerfile CMD/ENTRYPOINT.",
                        impact=proj.linked_services or [proj.name],
                    ))

    return issues


def check_code_env_example_drift(state: SystemState, cfg: dict) -> list[Issue]:
    """Detect .env.example missing vars that code references."""
    issues: list[Issue] = []
    projects = getattr(state, "projects", [])
    if not projects:
        return issues

    for proj in projects:
        if not proj.env_refs:
            continue

        example_path = os.path.join(proj.path, ".env.example")
        if not os.path.isfile(example_path):
            continue

        example_vars = set(parse_env_file(example_path).keys())
        missing = [v for v in proj.env_refs if v not in example_vars]

        if missing:
            issues.append(Issue(
                rule_id="code-env-example-drift",
                severity="info",
                service=proj.linked_services[0] if proj.linked_services else proj.name,
                message=f".env.example in {proj.name} is missing: {', '.join(sorted(missing))}.",
                hint=f"Add {', '.join(sorted(missing))} to .env.example for documentation.",
                impact=proj.linked_services or [proj.name],
            ))

    return issues


def check_code_dockerfile_no_healthcheck(state: SystemState, cfg: dict) -> list[Issue]:
    """Detect Dockerfile without HEALTHCHECK instruction."""
    issues: list[Issue] = []
    projects = getattr(state, "projects", [])
    if not projects:
        return issues

    for proj in projects:
        has_dockerfile = proj.metadata.get("has_dockerfile", False)
        has_healthcheck = proj.metadata.get("dockerfile_has_healthcheck", True)

        if has_dockerfile and not has_healthcheck:
            issues.append(Issue(
                rule_id="code-dockerfile-no-healthcheck",
                severity="info",
                service=proj.linked_services[0] if proj.linked_services else proj.name,
                message=f"Dockerfile in {proj.name} has no HEALTHCHECK instruction.",
                hint="Add HEALTHCHECK to enable container health monitoring.",
                impact=proj.linked_services or [proj.name],
            ))

    return issues


def _extract_filenames_from_cmd(cmd_str: str) -> list[str]:
    """Extract potential filenames from a CMD/ENTRYPOINT string."""
    # Try JSON array format first
    try:
        parts = json.loads(cmd_str)
        if isinstance(parts, list):
            return [str(p) for p in parts]
    except (json.JSONDecodeError, TypeError):
        pass

    # Shell format: "python main.py" or "node server.js"
    return cmd_str.split()
