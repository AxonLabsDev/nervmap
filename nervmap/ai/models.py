"""Data models for AI agent chain mapping."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field


@dataclass
class SessionNode:
    """Terminal + session multiplexer entry point."""
    terminal_type: str | None = None    # ttyd | ssh | direct
    terminal_pid: int | None = None
    terminal_port: int | None = None
    terminal_bind: str | None = None    # bind address
    mux_type: str | None = None         # tmux | screen
    mux_session: str | None = None      # "claude", "codex-session"
    mux_pid: int | None = None

    def to_dict(self) -> dict:
        d = {}
        if self.terminal_type:
            d["terminal_type"] = self.terminal_type
        if self.terminal_pid:
            d["terminal_pid"] = self.terminal_pid
        if self.terminal_port:
            d["terminal_port"] = self.terminal_port
        if self.mux_type:
            d["mux_type"] = self.mux_type
        if self.mux_session:
            d["mux_session"] = self.mux_session
        return d


@dataclass
class AgentNode:
    """The AI agent process."""
    agent_type: str         # claude-code | codex-cli | gemini-cli | custom
    pid: int
    cwd: str
    cmdline: str
    display_name: str = ""

    def to_dict(self) -> dict:
        return {
            "agent_type": self.agent_type,
            "pid": self.pid,
            "cwd": self.cwd,
            "display_name": self.display_name,
        }


@dataclass
class ConfigNode:
    """A config file that controls agent behavior."""
    path: str
    config_type: str        # instruction | settings | memory | model | flag
    role: str = ""          # what this file controls (e.g. "project rules", "hooks + permissions")
    detection: str = ""     # known_path | proc_fd | cmdline_arg | referenced
    confidence: float = 0.9
    exists: bool = True
    content_hash: str | None = None     # sha256 for drift detection
    children: list["ConfigNode"] = field(default_factory=list)  # files referenced by this one

    def to_dict(self) -> dict:
        d = {
            "path": self.path,
            "config_type": self.config_type,
            "confidence": self.confidence,
            "exists": self.exists,
        }
        if self.role:
            d["role"] = self.role
        if self.detection:
            d["detection"] = self.detection
        if self.content_hash:
            d["content_hash"] = self.content_hash
        if self.children:
            d["children"] = [c.to_dict() for c in self.children]
        return d

    @staticmethod
    def hash_file(path: str) -> str | None:
        """Compute sha256 of a file for drift detection."""
        try:
            h = hashlib.sha256()
            with open(path, "rb") as f:
                for chunk in iter(lambda: f.read(8192), b""):
                    h.update(chunk)
            return h.hexdigest()[:16]
        except Exception:
            return None


@dataclass
class BackendNode:
    """LLM inference backend (local or cloud)."""
    backend_type: str       # local | cloud | proxy
    provider: str           # llama_cpp | ollama | anthropic | openai | google
    endpoint: str           # "127.0.0.1:8123" or "api.anthropic.com"
    auth_method: str = ""   # api_key | oauth | none
    pid: int | None = None
    model_name: str | None = None       # "Qwen3.5-35B" or "claude-opus-4-6"
    model_path: str | None = None       # "/opt/models/..."
    gpu_layers: int | None = None
    context_size: int | None = None
    ports: list[int] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = {
            "backend_type": self.backend_type,
            "provider": self.provider,
            "endpoint": self.endpoint,
        }
        if self.auth_method:
            d["auth_method"] = self.auth_method
        if self.pid:
            d["pid"] = self.pid
        if self.model_name:
            d["model_name"] = self.model_name
        if self.model_path:
            d["model_path"] = self.model_path
        if self.gpu_layers is not None:
            d["gpu_layers"] = self.gpu_layers
        if self.context_size is not None:
            d["context_size"] = self.context_size
        if self.ports:
            d["ports"] = self.ports
        return d


@dataclass
class ProxyNode:
    """A proxy/forwarder between agent and backend (socat, nginx, etc.)."""
    proxy_type: str             # socat | nginx | haproxy
    pid: int | None = None
    listen_port: int | None = None
    listen_bind: str | None = None
    target_port: int | None = None
    target_host: str = "127.0.0.1"

    def to_dict(self) -> dict:
        d = {"proxy_type": self.proxy_type}
        if self.pid:
            d["pid"] = self.pid
        if self.listen_port is not None:
            d["listen_port"] = self.listen_port
        if self.listen_bind:
            d["listen_bind"] = self.listen_bind
        if self.target_port is not None:
            d["target_port"] = self.target_port
        if self.target_host:
            d["target_host"] = self.target_host
        return d


@dataclass
class AIChain:
    """Complete execution chain: terminal -> session -> agent -> configs -> backend."""
    id: str                                 # "ai:claude-code:34688"
    status: str = "running"                 # running | stopped | degraded
    session: SessionNode | None = None
    agent: AgentNode | None = None
    configs: list[ConfigNode] = field(default_factory=list)
    backend: BackendNode | None = None
    proxy: ProxyNode | None = None          # proxy between consumer and backend
    consumers: list[str] = field(default_factory=list)  # apps consuming this backend
    linked_services: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = {
            "id": self.id,
            "status": self.status,
        }
        if self.session:
            d["session"] = self.session.to_dict()
        if self.agent:
            d["agent"] = self.agent.to_dict()
        if self.configs:
            d["configs"] = [c.to_dict() for c in self.configs]
        if self.backend:
            d["backend"] = self.backend.to_dict()
        if self.proxy:
            d["proxy"] = self.proxy.to_dict()
        if self.consumers:
            d["consumers"] = self.consumers
        if self.linked_services:
            d["linked_services"] = self.linked_services
        return d
