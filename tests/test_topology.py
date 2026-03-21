"""Tests for topology mapping."""

import pytest

from nervmap.models import Service, Connection, SystemState
from nervmap.topology.mapper import DependencyMapper
from nervmap.topology.fingerprints import ServiceFingerprinter, PORT_FINGERPRINTS
from nervmap.config import DEFAULTS


class TestServiceFingerprinter:
    """Tests for port-based service fingerprinting."""

    def test_known_ports(self):
        """Well-known ports return correct service type."""
        fp = ServiceFingerprinter()
        assert fp.fingerprint(5432)[0] == "postgres"
        assert fp.fingerprint(6379)[0] == "redis"
        assert fp.fingerprint(3306)[0] == "mysql"
        assert fp.fingerprint(27017)[0] == "mongodb"
        assert fp.fingerprint(9200)[0] == "elasticsearch"
        assert fp.fingerprint(80)[0] == "http"
        assert fp.fingerprint(443)[0] == "https"
        assert fp.fingerprint(22)[0] == "ssh"

    def test_unknown_port_with_name_hint(self):
        """Unknown port falls back to name heuristic."""
        fp = ServiceFingerprinter()
        stype, _ = fp.fingerprint(9999, cmdline="", name="nginx-custom")
        assert stype == "nginx"

    def test_unknown_port_unknown_name(self):
        """Truly unknown port returns 'unknown'."""
        fp = ServiceFingerprinter()
        stype, _ = fp.fingerprint(55555)
        assert stype == "unknown"

    def test_fingerprint_count(self):
        """We have at least 30 fingerprints as specified."""
        assert len(PORT_FINGERPRINTS) >= 30


class TestDependencyMapper:
    """Tests for dependency inference."""

    def test_tcp_established_mapping(self):
        """Established TCP connections are mapped to dependencies."""
        svc_a = Service(id="docker:app", name="app", type="docker",
                        status="running", ports=[3000])
        svc_b = Service(id="docker:postgres", name="postgres", type="docker",
                        status="running", ports=[5432])

        state = SystemState(
            services=[svc_a, svc_b],
            established=[{
                "local_addr": "172.17.0.3",
                "local_port": 3000,
                "remote_addr": "172.17.0.2",
                "remote_port": 5432,
            }],
            listening_ports={3000: "docker:app", 5432: "docker:postgres"},
        )

        mapper = DependencyMapper(state, DEFAULTS)
        conns = mapper.map()

        assert len(conns) >= 1
        tcp_conns = [c for c in conns if c.type == "tcp"]
        assert len(tcp_conns) >= 1
        assert tcp_conns[0].confidence == 0.85

    def test_env_var_inference(self):
        """Env vars pointing to a port create inferred connections."""
        svc_a = Service(id="docker:app", name="app", type="docker",
                        status="running", ports=[3000],
                        metadata={"env": {"DATABASE_URL": "postgres://db:5432/mydb"}})
        svc_b = Service(id="docker:db", name="db", type="docker",
                        status="running", ports=[5432])

        state = SystemState(
            services=[svc_a, svc_b],
            listening_ports={3000: "docker:app", 5432: "docker:db"},
        )

        mapper = DependencyMapper(state, DEFAULTS)
        conns = mapper.map()

        inferred = [c for c in conns if c.type == "inferred"]
        assert len(inferred) >= 1

    def test_docker_network_inference(self):
        """Services on same custom Docker network get declared connections."""
        svc_a = Service(id="docker:web", name="web", type="docker",
                        status="running", metadata={"networks": ["mynet"]})
        svc_b = Service(id="docker:api", name="api", type="docker",
                        status="running", metadata={"networks": ["mynet"]})

        state = SystemState(services=[svc_a, svc_b])

        mapper = DependencyMapper(state, DEFAULTS)
        conns = mapper.map()

        declared = [c for c in conns if c.type == "declared"]
        assert len(declared) >= 1
        assert declared[0].confidence == 1.0

    def test_bridge_network_ignored(self):
        """Default bridge network does not create connections."""
        svc_a = Service(id="docker:web", name="web", type="docker",
                        status="running", metadata={"networks": ["bridge"]})
        svc_b = Service(id="docker:api", name="api", type="docker",
                        status="running", metadata={"networks": ["bridge"]})

        state = SystemState(services=[svc_a, svc_b])
        mapper = DependencyMapper(state, DEFAULTS)
        conns = mapper.map()

        declared = [c for c in conns if c.type == "declared"]
        assert len(declared) == 0

    def test_deduplication(self):
        """Duplicate connections keep highest confidence."""
        conns = [
            Connection(source="a", target="b", type="tcp", target_port=5432, confidence=0.85),
            Connection(source="a", target="b", type="inferred", target_port=5432, confidence=0.60),
        ]
        deduped = DependencyMapper._deduplicate(conns)
        assert len(deduped) == 1
        assert deduped[0].confidence == 0.85
