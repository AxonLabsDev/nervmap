"""Data models for source code analysis."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class CodeProject:
    """A discovered source code project."""

    path: str
    name: str
    language: str           # python | javascript | typescript | go | unknown
    framework: str | None   # fastapi | express | nextjs | gin | None
    entry_point: str | None
    deps_file: str | None
    file_count: int
    dependencies: list[str] = field(default_factory=list)
    env_refs: list[str] = field(default_factory=list)
    port_bindings: list[int] = field(default_factory=list)
    linked_services: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "name": self.name,
            "language": self.language,
            "framework": self.framework,
            "entry_point": self.entry_point,
            "deps_file": self.deps_file,
            "file_count": self.file_count,
            "dependencies": self.dependencies,
            "env_refs": self.env_refs,
            "port_bindings": self.port_bindings,
            "linked_services": self.linked_services,
            "metadata": self.metadata,
        }
