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


class TestRedactEnv:
    """Tests for secret redaction in output."""

    def test_redact_password_key(self):
        """Keys containing PASSWORD are redacted."""
        from nervmap.utils import redact_env, REDACTED
        env = {"DB_PASSWORD": "s3cret", "APP_NAME": "myapp"}
        result = redact_env(env)
        assert result["DB_PASSWORD"] == REDACTED
        assert result["APP_NAME"] == "myapp"

    def test_redact_token_key(self):
        """Keys containing TOKEN are redacted."""
        from nervmap.utils import redact_env, REDACTED
        env = {"AUTH_TOKEN": "abc123", "PORT": "8080"}
        result = redact_env(env)
        assert result["AUTH_TOKEN"] == REDACTED
        assert result["PORT"] == "8080"

    def test_redact_credential_url(self):
        """URLs with embedded credentials are redacted."""
        from nervmap.utils import redact_env, REDACTED
        env = {"DATABASE_URL": "postgres://user:pass@host:5432/db", "HOME": "/root"}
        result = redact_env(env)
        assert result["DATABASE_URL"] == REDACTED
        assert result["HOME"] == "/root"

    def test_redact_empty_env(self):
        """Empty env dict is returned as-is."""
        from nervmap.utils import redact_env
        assert redact_env({}) == {}

    def test_json_output_no_secrets(self):
        """JSON output redacts secrets by default."""
        svc = Service(id="docker:test", name="test", type="docker",
                      status="running", ports=[8080],
                      metadata={"env": {"SECRET_KEY": "hidden", "APP": "ok"}})
        state = SystemState(services=[svc])

        renderer = JsonRenderer()
        buf = StringIO()
        with patch("sys.stdout", buf):
            renderer.render(state, [], 1.0)

        output = json.loads(buf.getvalue())
        env = output["services"][0]["metadata"]["env"]
        assert env["SECRET_KEY"] == "***REDACTED***"
        assert env["APP"] == "ok"

    def test_json_output_show_secrets(self):
        """JSON output shows secrets when --show-secrets is passed."""
        svc = Service(id="docker:test", name="test", type="docker",
                      status="running", ports=[8080],
                      metadata={"env": {"SECRET_KEY": "visible"}})
        state = SystemState(services=[svc])

        renderer = JsonRenderer()
        buf = StringIO()
        with patch("sys.stdout", buf):
            renderer.render(state, [], 1.0, show_secrets=True)

        output = json.loads(buf.getvalue())
        env = output["services"][0]["metadata"]["env"]
        assert env["SECRET_KEY"] == "visible"
