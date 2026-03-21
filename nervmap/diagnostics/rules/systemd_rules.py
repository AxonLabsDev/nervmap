"""Systemd-specific diagnostic rules."""

from __future__ import annotations

from nervmap.models import SystemState, Issue


def check_service_failed(state: SystemState, cfg: dict) -> list[Issue]:
    """Detect systemd services in failed state."""
    issues: list[Issue] = []

    for svc in state.services:
        if svc.type != "systemd":
            continue
        active = svc.metadata.get("active", "")
        if active == "failed":
            unit = svc.metadata.get("unit", svc.name)
            issues.append(Issue(
                rule_id="service-failed",
                severity="critical",
                service=svc.id,
                message=f"Systemd service {svc.name} is in failed state.",
                hint=f"Check logs: journalctl -u {unit} --no-pager -n 30",
                impact=[svc.id],
            ))

    return issues


def check_service_activating_stuck(state: SystemState, cfg: dict) -> list[Issue]:
    """Detect systemd services stuck in activating state."""
    issues: list[Issue] = []

    for svc in state.services:
        if svc.type != "systemd":
            continue
        active = svc.metadata.get("active", "")
        sub = svc.metadata.get("sub", "")
        if active == "activating" or (active == "active" and sub == "activating"):
            unit = svc.metadata.get("unit", svc.name)
            issues.append(Issue(
                rule_id="service-activating-stuck",
                severity="warning",
                service=svc.id,
                message=f"Systemd service {svc.name} is stuck activating.",
                hint=f"Check: systemctl status {unit} && journalctl -u {unit} -n 20",
                impact=[svc.id],
            ))

    return issues
