"""Core data models for NervMap."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Service:
    """A discovered service (Docker container, systemd unit, or bare process)."""

    id: str
    name: str
    type: str               # docker | systemd | process
    status: str             # running | stopped | degraded | unknown
    ports: list[int] = field(default_factory=list)
    pid: int | None = None
    health: str = "no_check"
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "type": self.type,
            "status": self.status,
            "ports": self.ports,
            "pid": self.pid,
            "health": self.health,
            "metadata": self.metadata,
        }


@dataclass
class Connection:
    """A dependency link between two services."""

    source: str
    target: str
    type: str               # tcp | unix | declared | inferred
    source_port: int | None = None
    target_port: int | None = None
    confidence: float = 0.5

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "target": self.target,
            "type": self.type,
            "source_port": self.source_port,
            "target_port": self.target_port,
            "confidence": self.confidence,
        }


@dataclass
class Issue:
    """A diagnosed problem with suggested fix."""

    rule_id: str            # "port-conflict", "dependency-down"
    severity: str           # critical | warning | info
    service: str            # affected service id
    message: str
    hint: str
    impact: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "rule_id": self.rule_id,
            "severity": self.severity,
            "service": self.service,
            "message": self.message,
            "hint": self.hint,
            "impact": self.impact,
        }


@dataclass
class SystemState:
    """Aggregate state from all collectors."""

    services: list[Service] = field(default_factory=list)
    connections: list[Connection] = field(default_factory=list)
    listening_ports: dict[int, str] = field(default_factory=dict)
    established: list[dict] = field(default_factory=list)
    disk_usage: dict[str, float] = field(default_factory=dict)
    memory: dict = field(default_factory=dict)
    projects: list = field(default_factory=list)
    ai_chains: list = field(default_factory=list)

    def service_by_id(self, sid: str) -> Service | None:
        for s in self.services:
            if s.id == sid:
                return s
        return None

    def to_dict(self) -> dict:
        result = {
            "services": [s.to_dict() for s in self.services],
            "connections": [c.to_dict() for c in self.connections],
            "listening_ports": {str(k): v for k, v in self.listening_ports.items()},
            "disk_usage": self.disk_usage,
            "memory": self.memory,
        }
        if self.projects:
            result["projects"] = [p.to_dict() for p in self.projects]
        if self.ai_chains:
            result["ai_chains"] = [c.to_dict() for c in self.ai_chains]
        return result
