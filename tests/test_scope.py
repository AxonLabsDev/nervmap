"""Tests for --scope filtering."""

import pytest

from nervmap.models import Service, Connection, SystemState
from nervmap.cli import _apply_scope


class TestApplyScope:
    """Tests for _apply_scope function."""

    def _make_state(self):
        """Create a test state with mixed services."""
        return SystemState(
            services=[
                Service(id="docker:openrag-backend", name="openrag-backend", type="docker",
                        status="running", ports=[8900],
                        metadata={"labels": {"com.docker.compose.project": "openrag"}}),
                Service(id="docker:openrag-frontend", name="openrag-frontend", type="docker",
                        status="running", ports=[3000],
                        metadata={"labels": {"com.docker.compose.project": "openrag"}}),
                Service(id="docker:gitea", name="gitea", type="docker",
                        status="running", ports=[3080]),
                Service(id="systemd:nginx", name="nginx", type="systemd",
                        status="running", ports=[80]),
                Service(id="systemd:openrag-embeddings", name="openrag-embeddings", type="systemd",
                        status="running", ports=[5558]),
            ],
            connections=[
                Connection(source="docker:openrag-frontend", target="docker:openrag-backend", type="inferred"),
                Connection(source="docker:openrag-backend", target="systemd:openrag-embeddings", type="inferred"),
                Connection(source="docker:gitea", target="systemd:nginx", type="inferred"),
            ],
            listening_ports={8900: "127.0.0.1", 3000: "127.0.0.1", 3080: "127.0.0.1", 80: "0.0.0.0", 5558: "127.0.0.1"},
        )

    def test_none_scope_returns_same(self):
        """None scope returns the same state."""
        state = self._make_state()
        result = _apply_scope(state, None)
        assert result is state

    def test_empty_scope_returns_same(self):
        """Empty string scope returns same state."""
        state = self._make_state()
        result = _apply_scope(state, "")
        assert result is state

    def test_substring_match(self):
        """Substring matches service IDs and names."""
        state = self._make_state()
        result = _apply_scope(state, "openrag")
        names = {s.name for s in result.services}
        assert "openrag-backend" in names
        assert "openrag-frontend" in names
        assert "openrag-embeddings" in names
        assert "gitea" not in names
        assert "nginx" not in names

    def test_glob_match(self):
        """Glob pattern matches service IDs."""
        state = self._make_state()
        result = _apply_scope(state, "docker:openrag*")
        assert len(result.services) == 2
        assert all(s.type == "docker" for s in result.services)

    def test_glob_systemd(self):
        """Glob works on systemd services."""
        state = self._make_state()
        result = _apply_scope(state, "systemd:*")
        assert len(result.services) == 2
        assert all(s.type == "systemd" for s in result.services)

    def test_case_insensitive(self):
        """Matching is case insensitive."""
        state = self._make_state()
        result = _apply_scope(state, "OPENRAG")
        assert len(result.services) == 3

    def test_connections_filtered(self):
        """Connections are filtered to scoped services."""
        state = self._make_state()
        result = _apply_scope(state, "openrag")
        # Should include openrag connections but not gitea->nginx
        assert len(result.connections) == 2
        sources = {c.source for c in result.connections}
        assert "docker:openrag-frontend" in sources
        assert "docker:openrag-backend" in sources
        assert "docker:gitea" not in sources

    def test_listening_ports_filtered(self):
        """Listening ports filtered to scoped services only."""
        state = self._make_state()
        result = _apply_scope(state, "gitea")
        assert 3080 in result.listening_ports
        assert 8900 not in result.listening_ports

    def test_established_filtered(self):
        """Established connections filtered to scoped ports."""
        state = self._make_state()
        state.established = [
            {"local_port": 8900, "remote_port": 5558, "pid": 100},
            {"local_port": 3080, "remote_port": 80, "pid": 200},
        ]
        result = _apply_scope(state, "openrag")
        # Only 8900 and 5558 belong to openrag services
        assert len(result.established) == 1
        assert result.established[0]["local_port"] == 8900

    def test_no_match_returns_empty(self):
        """Non-matching scope returns empty services."""
        state = self._make_state()
        result = _apply_scope(state, "nonexistent-xyz")
        assert len(result.services) == 0
        assert len(result.connections) == 0

    def test_trailing_slash_handled(self, tmp_path):
        """Trailing slash on directory path is normalized."""
        # Create a fake docker-compose dir
        compose = tmp_path / "myproject"
        compose.mkdir()
        (compose / "docker-compose.yml").write_text("version: '3'")

        state = SystemState(
            services=[
                Service(id="docker:myproject-web", name="myproject-web", type="docker",
                        status="running",
                        metadata={"labels": {"com.docker.compose.project": "myproject"}}),
                Service(id="docker:other", name="other", type="docker", status="running"),
            ]
        )

        # With trailing slash
        result = _apply_scope(state, str(compose) + "/")
        assert len(result.services) == 1
        assert result.services[0].name == "myproject-web"

        # Without trailing slash — same result
        result2 = _apply_scope(state, str(compose))
        assert len(result2.services) == 1
        assert result2.services[0].name == "myproject-web"
