"""Dependency mapping — infer connections between services."""

from __future__ import annotations

import re
from nervmap.models import SystemState, Connection
import logging
logger = logging.getLogger("nervmap.mapper")


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

        # 1. Docker Compose depends_on (100% confidence, declared)
        connections.extend(self._from_compose_depends_on())

        # 2. TCP established connections
        connections.extend(self._from_established())

        # 3. Environment variable inference
        connections.extend(self._from_env_vars())

        # 4. Docker network shared membership
        connections.extend(self._from_docker_networks())

        # Deduplicate
        return self._deduplicate(connections)

    def _from_compose_depends_on(self) -> list[Connection]:
        """Extract declared dependencies from docker-compose.yml files.

        Searches for docker-compose.yml in common locations and parses
        depends_on directives. Confidence: 1.0 (declared by developer).
        """
        import os
        import yaml

        conns: list[Connection] = []

        # Collect compose project dirs from container labels
        compose_dirs: set[str] = set()
        for svc in self.state.services:
            if svc.type != "docker":
                continue
            labels = svc.metadata.get("labels", {})
            workdir = labels.get("com.docker.compose.project.working_dir", "")
            if workdir and os.path.isdir(workdir):
                compose_dirs.add(workdir)

        # Build service name -> service ID mapping for this state
        name_to_id: dict[str, str] = {}
        for svc in self.state.services:
            name_to_id[svc.name.lower()] = svc.id
            # Also map without compose project prefix (e.g., "openrag-backend" -> "backend")
            if "-" in svc.name:
                short = svc.name.rsplit("-", 1)[-1].lower()
                if short not in name_to_id:
                    name_to_id[short] = svc.id

        for compose_dir in compose_dirs:
            for filename in ("docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"):
                compose_path = os.path.join(compose_dir, filename)
                if not os.path.isfile(compose_path):
                    continue

                try:
                    with open(compose_path, "r") as f:
                        compose = yaml.safe_load(f) or {}
                except Exception:
                    logger.debug("Failed to parse %s", compose_path, exc_info=True)
                    continue

                services = compose.get("services", {})
                if not isinstance(services, dict):
                    continue

                project_name = os.path.basename(compose_dir).lower()

                for svc_name, svc_def in services.items():
                    if not isinstance(svc_def, dict):
                        continue

                    depends = svc_def.get("depends_on", [])
                    # depends_on can be a list or a dict
                    if isinstance(depends, dict):
                        dep_names = list(depends.keys())
                    elif isinstance(depends, list):
                        dep_names = depends
                    else:
                        continue

                    # Resolve source service ID
                    source_id = (
                        name_to_id.get(f"{project_name}-{svc_name}".lower())
                        or name_to_id.get(svc_name.lower())
                    )
                    if not source_id:
                        continue

                    for dep_name in dep_names:
                        target_id = (
                            name_to_id.get(f"{project_name}-{dep_name}".lower())
                            or name_to_id.get(dep_name.lower())
                        )
                        if target_id and target_id != source_id:
                            conns.append(Connection(
                                source=source_id,
                                target=target_id,
                                type="declared",
                                confidence=1.0,
                            ))

                break  # Only parse the first compose file found per dir

        logger.debug("Compose depends_on: found %d declared connections", len(conns))
        return conns

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
                logger.debug("Env var parse error", exc_info=True)
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
        """Note shared Docker networks as 'association' (not dependency).

        Being on the same Docker network means 'can communicate', NOT
        'depends on'. We use type='association' with low confidence so
        these edges inform the graph but don't trigger dependency-based
        diagnostics like circular-dependency.
        """
        conns: list[Connection] = []
        network_members: dict[str, list[str]] = {}
        for svc in self.state.services:
            if svc.type != "docker":
                continue
            networks = svc.metadata.get("networks", [])
            for net in networks:
                if net in ("bridge", "host", "none"):
                    continue
                network_members.setdefault(net, []).append(svc.id)

        for net, members in network_members.items():
            if len(members) < 2:
                continue
            for i, src in enumerate(members):
                for tgt in members[i+1:]:
                    conns.append(Connection(
                        source=src,
                        target=tgt,
                        type="association",
                        confidence=0.3,
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
