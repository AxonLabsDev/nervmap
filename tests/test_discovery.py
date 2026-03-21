"""Tests for discovery collectors."""

import pytest
from unittest.mock import patch, MagicMock

from nervmap.models import Service
from nervmap.discovery.docker import DockerCollector
from nervmap.discovery.systemd import SystemdCollector
from nervmap.discovery.ports import PortCollector
from nervmap.discovery.process import ProcessCollector


class TestDockerCollector:
    """Tests for DockerCollector."""

    def test_no_docker_returns_empty(self):
        """When Docker is not available, return empty list gracefully."""
        # Simulate Docker unavailable by setting client to None
        dc = DockerCollector()
        dc._client = None
        assert dc.collect() == []

    def test_collect_returns_services(self):
        """Verify Docker containers are converted to Service objects."""
        mock_client = MagicMock()
        mock_container = MagicMock()
        mock_container.name = "test-nginx"
        mock_container.short_id = "abc123"
        mock_container.status = "running"
        mock_container.image.tags = ["nginx:latest"]
        mock_container.labels = {}
        mock_container.attrs = {
            "State": {"Pid": 1234, "Health": {}, "ExitCode": 0},
            "NetworkSettings": {
                "Ports": {"80/tcp": [{"HostPort": "8080"}]},
                "Networks": {"bridge": {}},
            },
            "Config": {"Env": ["NGINX_HOST=localhost"]},
            "RestartCount": 0,
        }
        mock_client.containers.list.return_value = [mock_container]

        dc = DockerCollector()
        dc._client = mock_client
        services = dc.collect()

        assert len(services) == 1
        svc = services[0]
        assert svc.id == "docker:test-nginx"
        assert svc.type == "docker"
        assert svc.status == "running"
        assert 80 in svc.ports or 8080 in svc.ports
        assert svc.pid == 1234

    def test_status_mapping(self):
        """Verify Docker status strings are mapped correctly."""
        assert DockerCollector._map_status("running") == "running"
        assert DockerCollector._map_status("exited") == "stopped"
        assert DockerCollector._map_status("paused") == "degraded"
        assert DockerCollector._map_status("restarting") == "degraded"
        assert DockerCollector._map_status("weird") == "unknown"


class TestSystemdCollector:
    """Tests for SystemdCollector."""

    def test_parse_text_output(self):
        """Parse plain-text systemctl output."""
        text = (
            "  nginx.service  loaded active running  A high performance web server\n"
            "  redis.service  loaded active running  Redis in-memory data store\n"
            "  bad.service    loaded failed failed   Bad service\n"
        )
        units = SystemdCollector._parse_text(text)
        assert len(units) == 3
        assert units[0]["unit"] == "nginx.service"
        assert units[0]["active"] == "active"
        assert units[2]["active"] == "failed"

    def test_status_mapping(self):
        """Verify systemd status mapping."""
        assert SystemdCollector._map_status("active", "running") == "running"
        assert SystemdCollector._map_status("failed", "") == "stopped"
        assert SystemdCollector._map_status("activating", "") == "degraded"
        assert SystemdCollector._map_status("inactive", "") == "stopped"

    @patch("subprocess.run")
    def test_collect_with_json(self, mock_run):
        """Test collection via JSON systemctl output."""
        import json
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps([
                {"unit": "test.service", "load": "loaded", "active": "active",
                 "sub": "running", "description": "Test service"},
            ]),
        )
        sc = SystemdCollector()
        services = sc.collect()
        assert len(services) >= 1
        assert services[0].type == "systemd"


class TestPortCollector:
    """Tests for PortCollector."""

    def test_decode_ipv4_addr(self):
        """Decode IPv4 address from /proc/net/tcp hex format."""
        # 0100007F:1F90 = 127.0.0.1:8080
        addr, port = PortCollector._decode_addr("0100007F:1F90")
        assert addr == "127.0.0.1"
        assert port == 8080

    def test_decode_wildcard_addr(self):
        """Decode 0.0.0.0 address."""
        addr, port = PortCollector._decode_addr("00000000:0050")
        assert addr == "0.0.0.0"
        assert port == 80

    def test_collect_returns_dict(self):
        """Verify collect returns correct structure."""
        pc = PortCollector()
        result = pc.collect()
        assert "listening" in result
        assert "established" in result
        assert isinstance(result["listening"], dict)
        assert isinstance(result["established"], list)


class TestProcessCollector:
    """Tests for ProcessCollector."""

    def test_derive_name_binary(self):
        """Extract name from simple binary path."""
        assert ProcessCollector._derive_name("/usr/bin/nginx") == "nginx"

    def test_derive_name_interpreter(self):
        """Extract script name when run via interpreter."""
        assert ProcessCollector._derive_name("python3 /opt/app/server.py") == "server"
        assert ProcessCollector._derive_name("node /app/index.js") == "index"

    def test_collect_with_empty_state(self):
        """Collect with no existing services or ports."""
        pc = ProcessCollector()
        result = pc.collect([], {})
        assert isinstance(result, list)
