"""Tests for diagnostic rules."""

import pytest

from nervmap.models import Service, Connection, Issue, SystemState
from nervmap.config import DEFAULTS
from nervmap.diagnostics.engine import RuleRunner
from nervmap.diagnostics.rules.network import (
    check_port_conflict,
    check_port_unreachable,
    check_port_exposed_wildcard,
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


class TestNetworkRules:
    """Network diagnostic rules."""

    def test_port_conflict_detected(self):
        """Two services on same port triggers critical issue."""
        svc_a = Service(id="docker:web", name="web", type="docker",
                        status="running", ports=[8080])
        svc_b = Service(id="process:api:8080", name="api", type="process",
                        status="running", ports=[8080])
        state = SystemState(services=[svc_a, svc_b])
        issues = check_port_conflict(state, DEFAULTS)
        assert len(issues) == 1
        assert issues[0].rule_id == "port-conflict"
        assert issues[0].severity == "critical"

    def test_port_conflict_ignored_port(self):
        """Ignored ports are not flagged."""
        svc_a = Service(id="a", name="a", type="docker", status="running", ports=[22])
        svc_b = Service(id="b", name="b", type="process", status="running", ports=[22])
        cfg = {**DEFAULTS, "ignore": {"ports": [22], "services": []}}
        issues = check_port_conflict(state=SystemState(services=[svc_a, svc_b]), cfg=cfg)
        assert len(issues) == 0

    def test_port_unreachable(self):
        """Running service with port not in listening set triggers warning."""
        svc = Service(id="docker:api", name="api", type="docker",
                      status="running", ports=[9999])
        state = SystemState(services=[svc], listening_ports={})
        issues = check_port_unreachable(state, DEFAULTS)
        assert len(issues) == 1
        assert issues[0].rule_id == "port-unreachable"

    def test_wildcard_exposure(self):
        """Listening on 0.0.0.0 triggers info issue."""
        svc = Service(id="docker:web", name="web", type="docker",
                      status="running", ports=[8080])
        state = SystemState(
            services=[svc],
            listening_ports={8080: "0.0.0.0"},
        )
        issues = check_port_exposed_wildcard(state, DEFAULTS)
        assert len(issues) == 1
        assert issues[0].severity == "info"


class TestDockerRules:
    """Docker diagnostic rules."""

    def test_restart_loop(self):
        """Container with high restart count triggers critical."""
        svc = Service(id="docker:crasher", name="crasher", type="docker",
                      status="running", metadata={"restart_count": 10})
        state = SystemState(services=[svc])
        issues = check_container_restart_loop(state, DEFAULTS)
        assert len(issues) == 1
        assert issues[0].rule_id == "container-restart-loop"

    def test_unhealthy_container(self):
        """Unhealthy container triggers warning."""
        svc = Service(id="docker:sick", name="sick", type="docker",
                      status="running", health="unhealthy")
        state = SystemState(services=[svc])
        issues = check_container_unhealthy(state, DEFAULTS)
        assert len(issues) == 1

    def test_oom_killed(self):
        """Container with exit code 137 triggers critical."""
        svc = Service(id="docker:dead", name="dead", type="docker",
                      status="stopped", metadata={"exit_code": 137})
        state = SystemState(services=[svc])
        issues = check_container_oom_killed(state, DEFAULTS)
        assert len(issues) == 1
        assert issues[0].severity == "critical"

    def test_orphan_container(self):
        """Running container without compose labels triggers info."""
        svc = Service(id="docker:lonely", name="lonely", type="docker",
                      status="running", metadata={"labels": {}})
        state = SystemState(services=[svc])
        issues = check_container_orphan(state, DEFAULTS)
        assert len(issues) == 1
        assert issues[0].severity == "info"

    def test_compose_container_not_orphan(self):
        """Container with compose labels is not flagged."""
        svc = Service(id="docker:managed", name="managed", type="docker",
                      status="running",
                      metadata={"labels": {"com.docker.compose.project": "myapp"}})
        state = SystemState(services=[svc])
        issues = check_container_orphan(state, DEFAULTS)
        assert len(issues) == 0


class TestSystemdRules:
    """Systemd diagnostic rules."""

    def test_failed_service(self):
        """Failed systemd service triggers critical."""
        svc = Service(id="systemd:broken", name="broken", type="systemd",
                      status="stopped", metadata={"active": "failed", "unit": "broken.service"})
        state = SystemState(services=[svc])
        issues = check_service_failed(state, DEFAULTS)
        assert len(issues) == 1
        assert issues[0].severity == "critical"

    def test_activating_stuck(self):
        """Activating service triggers warning."""
        svc = Service(id="systemd:slow", name="slow", type="systemd",
                      status="degraded", metadata={"active": "activating", "sub": "start"})
        state = SystemState(services=[svc])
        issues = check_service_activating_stuck(state, DEFAULTS)
        assert len(issues) == 1


class TestDependencyRules:
    """Dependency diagnostic rules."""

    def test_dependency_down(self):
        """Service depending on stopped service triggers critical."""
        svc_a = Service(id="docker:app", name="app", type="docker", status="running")
        svc_b = Service(id="docker:db", name="db", type="docker", status="stopped")
        conn = Connection(source="docker:app", target="docker:db", type="tcp")
        state = SystemState(services=[svc_a, svc_b], connections=[conn])
        issues = check_dependency_down(state, DEFAULTS)
        assert len(issues) == 1
        assert issues[0].rule_id == "dependency-down"

    def test_env_port_mismatch(self):
        """Env var pointing to non-listening port triggers warning."""
        svc = Service(id="docker:app", name="app", type="docker",
                      status="running",
                      metadata={"env": {"DATABASE_URL": "postgres://localhost:5432/db"}})
        state = SystemState(services=[svc], listening_ports={3000: "docker:app"})
        issues = check_env_port_mismatch(state, DEFAULTS)
        assert len(issues) == 1
        assert issues[0].rule_id == "env-port-mismatch"


class TestResourceRules:
    """Resource diagnostic rules."""

    def test_disk_pressure_warning(self):
        """Filesystem at 92% triggers warning."""
        state = SystemState(disk_usage={"/": 92.0})
        issues = check_disk_pressure(state, DEFAULTS)
        assert len(issues) == 1
        assert issues[0].severity == "warning"

    def test_disk_pressure_critical(self):
        """Filesystem at 96% triggers critical."""
        state = SystemState(disk_usage={"/": 96.0})
        issues = check_disk_pressure(state, DEFAULTS)
        assert len(issues) == 1
        assert issues[0].severity == "critical"

    def test_disk_ok(self):
        """Filesystem at 50% triggers nothing."""
        state = SystemState(disk_usage={"/": 50.0})
        issues = check_disk_pressure(state, DEFAULTS)
        assert len(issues) == 0

    def test_memory_oom_risk(self):
        """Memory at 85% triggers warning."""
        state = SystemState(memory={
            "total": 16 * 1024**3,
            "available": 2.4 * 1024**3,
            "percent": 85.0,
        })
        issues = check_memory_oom_risk(state, DEFAULTS)
        assert len(issues) == 1
        assert issues[0].severity == "warning"

    def test_memory_ok(self):
        """Memory at 60% triggers nothing."""
        state = SystemState(memory={
            "total": 16 * 1024**3,
            "available": 6.4 * 1024**3,
            "percent": 60.0,
        })
        issues = check_memory_oom_risk(state, DEFAULTS)
        assert len(issues) == 0


class TestRuleRunner:
    """Tests for the rule runner engine."""

    def test_runner_returns_sorted_issues(self):
        """Issues are sorted by severity: critical first."""
        svc_a = Service(id="docker:crash", name="crash", type="docker",
                        status="running", metadata={"restart_count": 10})
        svc_b = Service(id="docker:web", name="web", type="docker",
                        status="running", ports=[8080],
                        metadata={"labels": {}})
        state = SystemState(
            services=[svc_a, svc_b],
            listening_ports={8080: "0.0.0.0"},
        )
        runner = RuleRunner()
        issues = runner.evaluate(state, DEFAULTS)
        if len(issues) >= 2:
            severity_order = {"critical": 0, "warning": 1, "info": 2}
            for i in range(len(issues) - 1):
                assert severity_order.get(issues[i].severity, 3) <= \
                       severity_order.get(issues[i+1].severity, 3)
