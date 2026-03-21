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
        """Services on same custom Docker network get association connections (low confidence)."""
        svc_a = Service(id="docker:web", name="web", type="docker",
                        status="running", metadata={"networks": ["mynet"]})
        svc_b = Service(id="docker:api", name="api", type="docker",
                        status="running", metadata={"networks": ["mynet"]})

        state = SystemState(services=[svc_a, svc_b])

        mapper = DependencyMapper(state, DEFAULTS)
        conns = mapper.map()

        associations = [c for c in conns if c.type == "association"]
        assert len(associations) >= 1
        assert associations[0].confidence == 0.3

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

    def test_compose_depends_on(self, tmp_path):
        """depends_on in docker-compose.yml creates declared connections."""
        # Create a fake compose file
        compose_dir = tmp_path / "myproject"
        compose_dir.mkdir()
        (compose_dir / "docker-compose.yml").write_text("""
services:
  backend:
    depends_on:
      - redis
      - postgres
  frontend:
    depends_on:
      - backend
""")
        svc_backend = Service(
            id="docker:myproject-backend", name="myproject-backend", type="docker",
            status="running",
            metadata={"labels": {"com.docker.compose.project.working_dir": str(compose_dir)}}
        )
        svc_frontend = Service(
            id="docker:myproject-frontend", name="myproject-frontend", type="docker",
            status="running",
            metadata={"labels": {"com.docker.compose.project.working_dir": str(compose_dir)}}
        )
        svc_redis = Service(
            id="docker:myproject-redis", name="myproject-redis", type="docker",
            status="running",
            metadata={"labels": {"com.docker.compose.project.working_dir": str(compose_dir)}}
        )
        svc_postgres = Service(
            id="docker:myproject-postgres", name="myproject-postgres", type="docker",
            status="running",
            metadata={"labels": {"com.docker.compose.project.working_dir": str(compose_dir)}}
        )

        state = SystemState(services=[svc_backend, svc_frontend, svc_redis, svc_postgres])
        mapper = DependencyMapper(state, DEFAULTS)
        conns = mapper.map()

        declared = [c for c in conns if c.type == "declared"]
        assert len(declared) == 3  # backend->redis, backend->postgres, frontend->backend
        assert all(c.confidence == 1.0 for c in declared)

        # Check specific connections
        targets_from_backend = {c.target for c in declared if c.source == "docker:myproject-backend"}
        assert "docker:myproject-redis" in targets_from_backend
        assert "docker:myproject-postgres" in targets_from_backend

        targets_from_frontend = {c.target for c in declared if c.source == "docker:myproject-frontend"}
        assert "docker:myproject-backend" in targets_from_frontend

    def test_compose_depends_on_dict_format(self, tmp_path):
        """depends_on as dict (with condition) also works."""
        compose_dir = tmp_path / "proj"
        compose_dir.mkdir()
        (compose_dir / "docker-compose.yml").write_text("""
services:
  app:
    depends_on:
      db:
        condition: service_healthy
      cache:
        condition: service_started
""")
        svc_app = Service(id="docker:proj-app", name="proj-app", type="docker",
                          status="running",
                          metadata={"labels": {"com.docker.compose.project.working_dir": str(compose_dir)}})
        svc_db = Service(id="docker:proj-db", name="proj-db", type="docker",
                         status="running",
                         metadata={"labels": {"com.docker.compose.project.working_dir": str(compose_dir)}})
        svc_cache = Service(id="docker:proj-cache", name="proj-cache", type="docker",
                            status="running",
                            metadata={"labels": {"com.docker.compose.project.working_dir": str(compose_dir)}})

        state = SystemState(services=[svc_app, svc_db, svc_cache])
        mapper = DependencyMapper(state, DEFAULTS)
        conns = mapper.map()

        declared = [c for c in conns if c.type == "declared"]
        assert len(declared) == 2
        targets = {c.target for c in declared}
        assert "docker:proj-db" in targets
        assert "docker:proj-cache" in targets

    def test_deduplication(self):
        """Duplicate connections keep highest confidence."""
        conns = [
            Connection(source="a", target="b", type="tcp", target_port=5432, confidence=0.85),
            Connection(source="a", target="b", type="inferred", target_port=5432, confidence=0.60),
        ]
        deduped = DependencyMapper._deduplicate(conns)
        assert len(deduped) == 1
        assert deduped[0].confidence == 0.85
