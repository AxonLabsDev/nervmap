"""Tests for output renderers."""

import json
import pytest
from io import StringIO
from unittest.mock import patch

from nervmap.models import Service, Connection, Issue, SystemState
from nervmap.output.console import ConsoleRenderer
from nervmap.output.json_out import JsonRenderer


class TestJsonRenderer:
    """Tests for JSON output."""

    def test_json_output_structure(self):
        """JSON output has required fields."""
        svc = Service(id="docker:test", name="test", type="docker",
                      status="running", ports=[8080])
        issue = Issue(
            rule_id="test-rule", severity="warning",
            service="docker:test", message="Test issue",
            hint="Fix it", impact=["docker:test"],
        )
        state = SystemState(services=[svc])

        renderer = JsonRenderer()
        buf = StringIO()
        with patch("sys.stdout", buf):
            renderer.render(state, [issue], 1.5)

        output = json.loads(buf.getvalue())
        assert output["version"] == "0.1.0"
        assert output["elapsed_seconds"] == 1.5
        assert len(output["services"]) == 1
        assert len(output["issues"]) == 1
        assert output["summary"]["total_services"] == 1
        assert output["summary"]["warnings"] == 1

    def test_empty_state_json(self):
        """Empty state produces valid JSON."""
        state = SystemState()
        renderer = JsonRenderer()
        buf = StringIO()
        with patch("sys.stdout", buf):
            renderer.render(state, [], 0.1)

        output = json.loads(buf.getvalue())
        assert output["summary"]["total_services"] == 0
        assert output["summary"]["total_issues"] == 0


class TestConsoleRenderer:
    """Tests for Rich console output."""

    def test_render_no_crash(self):
        """Console renderer does not crash on valid input."""
        svc = Service(id="docker:test", name="test", type="docker",
                      status="running", ports=[8080])
        issue = Issue(
            rule_id="test-rule", severity="warning",
            service="docker:test", message="Test issue",
            hint="Fix it",
        )
        state = SystemState(services=[svc])

        renderer = ConsoleRenderer()
        # Should not raise
        renderer.render(state, [issue], 1.0)

    def test_render_quiet_mode(self):
        """Quiet mode does not crash."""
        state = SystemState(services=[
            Service(id="docker:test", name="test", type="docker",
                    status="running"),
        ])
        renderer = ConsoleRenderer()
        renderer.render(state, [], 0.5, quiet=True)

    def test_render_empty_state(self):
        """Empty state renders without crash."""
        state = SystemState()
        renderer = ConsoleRenderer()
        renderer.render(state, [], 0.1)

    def test_render_deps(self):
        """Dependency rendering does not crash."""
        svc_a = Service(id="docker:web", name="web", type="docker", status="running")
        svc_b = Service(id="docker:db", name="db", type="docker", status="running")
        conn = Connection(source="docker:web", target="docker:db",
                          type="tcp", target_port=5432, confidence=0.85)
        state = SystemState(services=[svc_a, svc_b], connections=[conn])
        renderer = ConsoleRenderer()
        renderer.render_deps(state)

    def test_render_issues(self):
        """Issue rendering does not crash."""
        issues = [
            Issue(rule_id="test", severity="critical", service="a",
                  message="Bad", hint="Fix"),
            Issue(rule_id="test2", severity="warning", service="b",
                  message="Warn", hint="Check"),
            Issue(rule_id="test3", severity="info", service="c",
                  message="Info", hint="Note"),
        ]
        renderer = ConsoleRenderer()
        renderer.render_issues(issues)
