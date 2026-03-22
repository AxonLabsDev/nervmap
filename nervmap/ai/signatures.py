"""AI agent and LLM engine signature registry."""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class AgentSignature:
    """Pattern for detecting a known AI agent type."""
    agent_type: str
    display_name: str
    cmdline_patterns: list[str]     # regex patterns against cmdline
    provider: str                   # anthropic | openai | google | local
    backend_type: str               # cloud | local
    config_paths: list[str]         # paths relative to {cwd} or {home}
    env_signatures: list[str] = field(default_factory=list)


@dataclass
class BackendSignature:
    """Pattern for detecting a local LLM backend."""
    backend_type: str               # llama_cpp | ollama | vllm | tgi | embedding
    display_name: str
    cmdline_patterns: list[str]
    port_flag: str = "--port"
    host_flag: str = "--host"
    model_flag: str = "--model"
    extra_flags: dict[str, str] = field(default_factory=dict)


# ── Agent signatures ──────────────────────────────────────────────

AGENT_SIGNATURES: list[AgentSignature] = [
    AgentSignature(
        agent_type="claude-code",
        display_name="Claude Code",
        cmdline_patterns=[r"(?:^|\s|/)claude(?:\s|$)"],
        provider="anthropic",
        backend_type="cloud",
        config_paths=[
            "{cwd}/CLAUDE.md",
            "{home}/.claude/settings.json",
            "{home}/.claude/projects/{project_slug}/memory/MEMORY.md",
        ],
        env_signatures=["ANTHROPIC_API_KEY", "CLAUDE_CODE_ENTRYPOINT"],
    ),
    AgentSignature(
        agent_type="codex-cli",
        display_name="Codex CLI",
        cmdline_patterns=[r"(?:^|\s|/)codex(?:\s|$)"],
        provider="openai",
        backend_type="cloud",
        config_paths=[
            "{cwd}/AGENTS.md",
            "{home}/.codex/instructions.md",
        ],
        env_signatures=["OPENAI_API_KEY"],
    ),
    AgentSignature(
        agent_type="gemini-cli",
        display_name="Gemini CLI",
        cmdline_patterns=[r"(?:^|\s|/)gemini(?:\s|$)"],
        provider="google",
        backend_type="cloud",
        config_paths=[
            "{home}/.gemini/settings.json",
            "{cwd}/GEMINI.md",
        ],
        env_signatures=["GOOGLE_API_KEY", "GEMINI_API_KEY"],
    ),
]


# ── Backend signatures ────────────────────────────────────────────

BACKEND_SIGNATURES: list[BackendSignature] = [
    BackendSignature(
        backend_type="llama_cpp",
        display_name="llama.cpp Server",
        cmdline_patterns=[r"llama-server", r"llama\.cpp"],
        port_flag="--port",
        host_flag="--host",
        model_flag="--model",
        extra_flags={
            "--n-gpu-layers": "gpu_layers",
            "-ngl": "gpu_layers",
            "--ctx-size": "context_size",
            "-c": "context_size",
        },
    ),
    BackendSignature(
        backend_type="ollama",
        display_name="Ollama",
        cmdline_patterns=[r"ollama\s+serve"],
        port_flag="--port",
        host_flag="--host",
        model_flag="",
    ),
    BackendSignature(
        backend_type="vllm",
        display_name="vLLM",
        cmdline_patterns=[r"vllm\.entrypoints", r"python.*-m\s+vllm"],
        port_flag="--port",
        host_flag="--host",
        model_flag="--model",
    ),
    BackendSignature(
        backend_type="tgi",
        display_name="Text Generation Inference",
        cmdline_patterns=[r"text-generation-launcher"],
        port_flag="--port",
        host_flag="--hostname",
        model_flag="--model-id",
    ),
    BackendSignature(
        backend_type="embedding",
        display_name="Embedding Server",
        cmdline_patterns=[r"embedding-server", r"embedding.*\.py"],
        port_flag="--port",
        host_flag="--host",
        model_flag="--model",
    ),
]


def load_custom_profiles(cfg: dict) -> tuple[list[AgentSignature], list[BackendSignature]]:
    """Load custom agent/backend profiles from .nervmap.yml ai section.

    Example config:
        ai:
          profiles:
            - agent_type: my-agent
              display_name: My Custom Agent
              cmdline_patterns: ["my-agent-server"]
              provider: openai
              backend_type: cloud
              config_paths: ["{cwd}/my-agent.yml"]
    """
    extra_agents: list[AgentSignature] = []
    extra_backends: list[BackendSignature] = []

    profiles = cfg.get("ai", {}).get("profiles", [])
    for p in profiles:
        if not isinstance(p, dict):
            continue
        if "agent_type" in p:
            extra_agents.append(AgentSignature(
                agent_type=p["agent_type"],
                display_name=p.get("display_name", p["agent_type"]),
                cmdline_patterns=p.get("cmdline_patterns", []),
                provider=p.get("provider", "custom"),
                backend_type=p.get("backend_type", "cloud"),
                config_paths=p.get("config_paths", []),
                env_signatures=p.get("env_signatures", []),
            ))
        elif "backend_type" in p:
            extra_backends.append(BackendSignature(
                backend_type=p["backend_type"],
                display_name=p.get("display_name", p["backend_type"]),
                cmdline_patterns=p.get("cmdline_patterns", []),
                port_flag=p.get("port_flag", "--port"),
                host_flag=p.get("host_flag", "--host"),
                model_flag=p.get("model_flag", "--model"),
            ))

    return extra_agents, extra_backends


def match_agent(cmdline: str, extra: list[AgentSignature] | None = None) -> AgentSignature | None:
    """Match a process cmdline against known agent signatures."""
    all_sigs = AGENT_SIGNATURES + (extra or [])
    for sig in all_sigs:
        for pattern in sig.cmdline_patterns:
            if re.search(pattern, cmdline):
                return sig
    return None


def match_backend(cmdline: str, extra: list[BackendSignature] | None = None) -> BackendSignature | None:
    """Match a process cmdline against known backend signatures."""
    all_sigs = BACKEND_SIGNATURES + (extra or [])
    for sig in all_sigs:
        for pattern in sig.cmdline_patterns:
            if re.search(pattern, cmdline):
                return sig
    return None
