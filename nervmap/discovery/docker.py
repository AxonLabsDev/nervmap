"""Docker container discovery via Docker SDK."""

from __future__ import annotations

import logging

from nervmap.models import Service
from nervmap.utils import redact_env

logger = logging.getLogger("nervmap.docker")


class DockerCollector:
    """Discover services from Docker containers."""

    def __init__(self):
        try:
            import docker as docker_lib
            self._client = docker_lib.from_env(timeout=5)
            self._client.ping()
        except Exception:
            logger.debug("Docker not available", exc_info=True)
            self._client = None

    def collect(self) -> list[Service]:
        if self._client is None:
            return []

        services: list[Service] = []
        try:
            containers = self._client.containers.list(all=True)
        except Exception:
            logger.debug("Failed to list Docker containers", exc_info=True)
            return []

        for ctr in containers:
            try:
                services.append(self._to_service(ctr))
            except Exception:
                continue

        return services

    def _to_service(self, ctr) -> Service:
        name = ctr.name or ctr.short_id
        status = self._map_status(ctr.status)
        ports = self._extract_ports(ctr)
        health = self._extract_health(ctr)
        pid = None
        try:
            info = ctr.attrs
            pid = info.get("State", {}).get("Pid")
        except Exception:
            pass

        # Metadata
        meta: dict = {
            "container_id": ctr.short_id,
            "image": str(ctr.image.tags[0]) if ctr.image.tags else str(ctr.image.id[:12]),
            "status_raw": ctr.status,
        }

        # Networks
        try:
            net_settings = ctr.attrs.get("NetworkSettings", {})
            networks = list(net_settings.get("Networks", {}).keys())
            meta["networks"] = networks
        except Exception:
            pass

        # Restart count
        try:
            meta["restart_count"] = ctr.attrs.get("RestartCount", 0)
        except Exception:
            pass

        # Exit code
        try:
            meta["exit_code"] = ctr.attrs.get("State", {}).get("ExitCode", 0)
        except Exception:
            pass

        # Environment variables (useful for dependency discovery)
        try:
            env_list = ctr.attrs.get("Config", {}).get("Env", [])
            env_dict = {}
            for e in env_list:
                if "=" in e:
                    k, v = e.split("=", 1)
                    env_dict[k] = v
            meta["env"] = redact_env(env_dict)
        except Exception:
            pass

        # Labels
        try:
            meta["labels"] = ctr.labels or {}
        except Exception:
            pass

        return Service(
            id=f"docker:{name}",
            name=name,
            type="docker",
            status=status,
            ports=ports,
            pid=pid,
            health=health,
            metadata=meta,
        )

    @staticmethod
    def _map_status(raw: str) -> str:
        mapping = {
            "running": "running",
            "exited": "stopped",
            "paused": "degraded",
            "restarting": "degraded",
            "created": "stopped",
            "removing": "stopped",
            "dead": "stopped",
        }
        return mapping.get(raw, "unknown")

    @staticmethod
    def _extract_ports(ctr) -> list[int]:
        ports: list[int] = []
        try:
            port_bindings = ctr.attrs.get("NetworkSettings", {}).get("Ports", {}) or {}
            for container_port, bindings in port_bindings.items():
                # container_port is like "8080/tcp"
                try:
                    p = int(container_port.split("/")[0])
                    ports.append(p)
                except (ValueError, IndexError):
                    pass
                if bindings:
                    for b in bindings:
                        try:
                            hp = int(b.get("HostPort", 0))
                            if hp and hp not in ports:
                                ports.append(hp)
                        except (ValueError, TypeError):
                            pass
        except Exception:
            pass
        return sorted(set(ports))

    @staticmethod
    def _extract_health(ctr) -> str:
        try:
            health_data = ctr.attrs.get("State", {}).get("Health", {})
            if not health_data:
                return "no_check"
            status = health_data.get("Status", "")
            if status == "healthy":
                return "healthy"
            elif status == "unhealthy":
                return "unhealthy"
            return "no_check"
        except Exception:
            return "no_check"
