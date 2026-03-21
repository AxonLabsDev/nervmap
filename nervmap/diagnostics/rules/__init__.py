"""Register all diagnostic rules."""

from __future__ import annotations

from typing import Callable
from nervmap.models import SystemState, Issue


RuleFunc = Callable[[SystemState, dict], list[Issue]]


def get_all_rules() -> list[RuleFunc]:
    """Return all registered rule functions."""
    from nervmap.diagnostics.rules.network import (
        check_port_conflict,
        check_port_unreachable,
        check_port_exposed_wildcard,
        check_connection_refused,
    )
    from nervmap.diagnostics.rules.docker_rules import (
        check_container_restart_loop,
        check_container_unhealthy,
        check_container_oom_killed,
        check_container_orphan,
    )
    from nervmap.diagnostics.rules.systemd_rules import (
        check_service_failed,
        check_service_activating_stuck,
    )
    from nervmap.diagnostics.rules.dependencies import (
        check_dependency_down,
        check_env_port_mismatch,
    )
    from nervmap.diagnostics.rules.resources import (
        check_disk_pressure,
        check_memory_oom_risk,
    )

    return [
        check_port_conflict,
        check_port_unreachable,
        check_port_exposed_wildcard,
        check_connection_refused,
        check_container_restart_loop,
        check_container_unhealthy,
        check_container_oom_killed,
        check_container_orphan,
        check_service_failed,
        check_service_activating_stuck,
        check_dependency_down,
        check_env_port_mismatch,
        check_disk_pressure,
        check_memory_oom_risk,
    ]
