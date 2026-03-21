"""Resource diagnostic rules."""

from __future__ import annotations

from nervmap.models import SystemState, Issue


def check_disk_pressure(state: SystemState, cfg: dict) -> list[Issue]:
    """Detect filesystems over 90% usage."""
    issues: list[Issue] = []

    for mount, percent in state.disk_usage.items():
        if percent >= 95:
            severity = "critical"
        elif percent >= 90:
            severity = "warning"
        else:
            continue

        issues.append(Issue(
            rule_id="disk-pressure",
            severity=severity,
            service="system",
            message=f"Filesystem {mount} is {percent:.1f}% full.",
            hint=f"Free space on {mount}: check large files with `du -sh {mount}/* | sort -rh | head`",
            impact=["system"],
        ))

    return issues


def check_memory_oom_risk(state: SystemState, cfg: dict) -> list[Issue]:
    """Detect system memory usage over 80%."""
    issues: list[Issue] = []

    mem = state.memory
    if not mem:
        return issues

    percent = mem.get("percent", 0)
    if percent >= 95:
        severity = "critical"
    elif percent >= 80:
        severity = "warning"
    else:
        return issues

    total_gb = mem.get("total", 0) / (1024 ** 3)
    avail_gb = mem.get("available", 0) / (1024 ** 3)

    issues.append(Issue(
        rule_id="memory-oom-risk",
        severity=severity,
        service="system",
        message=f"System memory at {percent:.1f}% ({avail_gb:.1f}GB free of {total_gb:.1f}GB).",
        hint="Identify memory hogs: `ps aux --sort=-%mem | head -10`",
        impact=["system"],
    ))

    return issues
