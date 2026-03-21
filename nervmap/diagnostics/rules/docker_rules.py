"""Docker-specific diagnostic rules."""

from __future__ import annotations

from nervmap.models import SystemState, Issue


def check_container_restart_loop(state: SystemState, cfg: dict) -> list[Issue]:
    """Detect containers in restart loops (restart count > 3)."""
    issues: list[Issue] = []

    for svc in state.services:
        if svc.type != "docker":
            continue
        restart_count = svc.metadata.get("restart_count", 0)
        if restart_count and restart_count > 3:
            issues.append(Issue(
                rule_id="container-restart-loop",
                severity="critical",
                service=svc.id,
                message=f"Container {svc.name} has restarted {restart_count} times.",
                hint=f"Check logs: docker logs {svc.name} --tail 50",
                impact=[svc.id],
            ))

    return issues


def check_container_unhealthy(state: SystemState, cfg: dict) -> list[Issue]:
    """Detect containers with failing health checks."""
    issues: list[Issue] = []

    for svc in state.services:
        if svc.type != "docker":
            continue
        if svc.health == "unhealthy":
            issues.append(Issue(
                rule_id="container-unhealthy",
                severity="warning",
                service=svc.id,
                message=f"Container {svc.name} healthcheck is failing.",
                hint=f"Inspect: docker inspect {svc.name} | jq '.[0].State.Health'",
                impact=[svc.id],
            ))

    return issues


def check_container_oom_killed(state: SystemState, cfg: dict) -> list[Issue]:
    """Detect containers killed by OOM (exit code 137)."""
    issues: list[Issue] = []

    for svc in state.services:
        if svc.type != "docker":
            continue
        exit_code = svc.metadata.get("exit_code")
        if svc.status == "stopped" and exit_code == 137:
            issues.append(Issue(
                rule_id="container-oom-killed",
                severity="critical",
                service=svc.id,
                message=f"Container {svc.name} was OOM-killed (exit 137).",
                hint=f"Increase memory limit or optimize the application. Check: docker stats {svc.name}",
                impact=[svc.id],
            ))

    return issues


def check_container_orphan(state: SystemState, cfg: dict) -> list[Issue]:
    """Detect running containers not associated with any compose project."""
    issues: list[Issue] = []

    for svc in state.services:
        if svc.type != "docker":
            continue
        if svc.status != "running":
            continue
        labels = svc.metadata.get("labels", {})
        has_compose = any(
            k.startswith("com.docker.compose") for k in labels
        )
        if not has_compose:
            issues.append(Issue(
                rule_id="container-orphan",
                severity="info",
                service=svc.id,
                message=f"Container {svc.name} is not part of any Docker Compose project.",
                hint="Consider managing this container with docker-compose for consistency.",
                impact=[svc.id],
            ))

    return issues
