"""Dependency mapping — infer connections between services."""

from __future__ import annotations

import re
from nervmap.models import SystemState, Connection, Service


# Env vars that typically point to a dependency
_DEP_ENV_PATTERNS: list[tuple[str, str]] = [
    (r"DATABASE_URL", "postgres"),
    (r"POSTGRES_HOST", "postgres"),
    (r"PGHOST", "postgres"),
    (r"MYSQL_HOST", "mysql"),
    (r"REDIS_HOST", "redis"),
    (r"REDIS_URL", "redis"),
    (r"MONGO_URL", "mongodb"),
    (r"MONGODB_URI", "mongodb"),
    (r"ELASTICSEARCH_URL", "elasticsearch"),
    (r"AMQP_URL", "rabbitmq"),
    (r"RABBITMQ_HOST", "rabbitmq"),
    (r"KAFKA_BOOTSTRAP", "kafka"),
    (r"KAFKA_BROKERS", "kafka"),
    (r"NATS_URL", "nats"),
    (r".*_HOST$", None),
    (r".*_PORT$", None),
    (r".*_URL$", None),
]

# Port -> likely service type (for matching env->service)
_PORT_TYPE_MAP: dict[int, str] = {
    5432: "postgres", 3306: "mysql", 6379: "redis",
    27017: "mongodb", 9200: "elasticsearch", 5672: "rabbitmq",
    9092: "kafka", 4222: "nats",
}


class DependencyMapper:
    """Infer connections between services."""

    def __init__(self, state: SystemState, cfg: dict):
        self.state = state
        self.cfg = cfg

    def map(self) -> list[Connection]:
        connections: list[Connection] = []

        # 1. TCP established connections
        connections.extend(self._from_established())

        # 2. Environment variable inference
        connections.extend(self._from_env_vars())

        # 3. Docker network shared membership
        connections.extend(self._from_docker_networks())

        # Deduplicate
        return self._deduplicate(connections)

    def _from_established(self) -> list[Connection]:
        """Match established connections to known services."""
        conns: list[Connection] = []
        port_to_service: dict[int, str] = {}
        for svc in self.state.services:
            for port in svc.ports:
                port_to_service[port] = svc.id

        for est in self.state.established:
            local_port = est.get("local_port", 0)
            remote_port = est.get("remote_port", 0)

            src_id = port_to_service.get(local_port)
            tgt_id = port_to_service.get(remote_port)

            if src_id and tgt_id and src_id != tgt_id:
                conns.append(Connection(
                    source=src_id,
                    target=tgt_id,
                    type="tcp",
                    source_port=local_port,
                    target_port=remote_port,
                    confidence=0.85,
                ))

        return conns

    def _from_env_vars(self) -> list[Connection]:
        """Infer dependencies from environment variables."""
        conns: list[Connection] = []

        for svc in self.state.services:
            env = svc.metadata.get("env", {})
            if not env:
                continue

            for key, value in env.items():
                target_id = self._match_env_to_service(key, value)
                if target_id and target_id != svc.id:
                    # Extract port from value if possible
                    target_port = self._extract_port_from_url(value)
                    conns.append(Connection(
                        source=svc.id,
                        target=target_id,
                        type="inferred",
                        source_port=None,
                        target_port=target_port,
                        confidence=0.60,
                    ))

        return conns

    def _match_env_to_service(self, key: str, value: str) -> str | None:
        """Try to match an env var to a known service."""
        for pattern, stype in _DEP_ENV_PATTERNS:
            if not re.match(pattern, key, re.IGNORECASE):
                continue

            # Try to extract host:port from value
            port = self._extract_port_from_url(value)
            if port:
                # Find service that owns this port
                for s in self.state.services:
                    if port in s.ports:
                        return s.id

            # Try matching service type
            if stype:
                for s in self.state.services:
                    if stype in s.name.lower() or stype in s.id.lower():
                        return s.id

            # Try hostname matching
            host = self._extract_host(value)
            if host:
                for s in self.state.services:
                    if host in s.name.lower() or host in s.id.lower():
                        return s.id

        return None

    @staticmethod
    def _extract_port_from_url(value: str) -> int | None:
        """Extract port number from a URL or host:port string."""
        # URL format: scheme://host:port/...
        m = re.search(r':(\d{2,5})(?:/|$|\?)', value)
        if m:
            try:
                return int(m.group(1))
            except ValueError:
                pass
        return None

    @staticmethod
    def _extract_host(value: str) -> str | None:
        """Extract hostname from URL or host:port."""
        # scheme://host:port
        m = re.match(r'(?:\w+://)?([^/:]+)', value)
        if m:
            host = m.group(1)
            if host not in ("localhost", "127.0.0.1", "0.0.0.0", "::1"):
                return host.lower()
        return None

    def _from_docker_networks(self) -> list[Connection]:
        """Infer potential connections from shared Docker networks."""
        conns: list[Connection] = []
        # Group docker services by network
        network_members: dict[str, list[str]] = {}
        for svc in self.state.services:
            if svc.type != "docker":
                continue
            networks = svc.metadata.get("networks", [])
            for net in networks:
                if net in ("bridge", "host", "none"):
                    continue
                network_members.setdefault(net, []).append(svc.id)

        # Services on same custom network can communicate
        for net, members in network_members.items():
            if len(members) < 2:
                continue
            for i, src in enumerate(members):
                for tgt in members[i+1:]:
                    conns.append(Connection(
                        source=src,
                        target=tgt,
                        type="declared",
                        confidence=1.0,
                    ))
        return conns

    @staticmethod
    def _deduplicate(conns: list[Connection]) -> list[Connection]:
        """Remove duplicates, keeping highest confidence."""
        best: dict[tuple, Connection] = {}
        for c in conns:
            key = (c.source, c.target, c.target_port)
            existing = best.get(key)
            if existing is None or c.confidence > existing.confidence:
                best[key] = c
        return list(best.values())
