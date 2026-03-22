"""AI-specific diagnostic rules."""

from __future__ import annotations

import os

from nervmap.models import SystemState, Issue


def check_ai_backend_down(state: SystemState, cfg: dict) -> list[Issue]:
    """Detect AI agent whose backend is not reachable."""
    issues: list[Issue] = []
    chains = getattr(state, "ai_chains", [])
    if not chains:
        return issues

    for chain in chains:
        if not chain.backend or chain.backend.backend_type != "local":
            continue
        # Check if backend port is listening
        for port in chain.backend.ports:
            if port and port not in state.listening_ports:
                agent_name = chain.agent.display_name if chain.agent else chain.id
                issues.append(Issue(
                    rule_id="ai-backend-down",
                    severity="critical",
                    service=chain.id,
                    message=f"{agent_name} backend {chain.backend.provider} "
                            f"on port {port} is not listening.",
                    hint=f"Start the LLM server on port {port}.",
                    impact=[chain.id],
                ))
    return issues


def check_ai_model_missing(state: SystemState, cfg: dict) -> list[Issue]:
    """Detect model file referenced in cmdline but not on disk."""
    issues: list[Issue] = []
    chains = getattr(state, "ai_chains", [])
    if not chains:
        return issues

    for chain in chains:
        if not chain.backend or not chain.backend.model_path:
            continue
        if not os.path.isfile(chain.backend.model_path):
            issues.append(Issue(
                rule_id="ai-model-missing",
                severity="critical",
                service=chain.id,
                message=f"Model file not found: {chain.backend.model_path}",
                hint="Check the --model path in the LLM server command.",
                impact=[chain.id],
            ))
    return issues


def check_ai_config_missing(state: SystemState, cfg: dict) -> list[Issue]:
    """Detect expected config files that don't exist."""
    issues: list[Issue] = []
    chains = getattr(state, "ai_chains", [])
    if not chains:
        return issues

    for chain in chains:
        if not chain.agent:
            continue
        for conf in chain.configs:
            if not conf.exists and conf.confidence > 0:
                issues.append(Issue(
                    rule_id="ai-config-missing",
                    severity="info",
                    service=chain.id,
                    message=f"Expected config {conf.path} not found for "
                            f"{chain.agent.display_name}.",
                    hint=f"Create {os.path.basename(conf.path)} to configure "
                         f"the agent.",
                    impact=[chain.id],
                ))
    return issues


def check_ai_orphan_backend(state: SystemState, cfg: dict) -> list[Issue]:
    """Detect LLM backends running with no agent connecting to them."""
    issues: list[Issue] = []
    chains = getattr(state, "ai_chains", [])
    if not chains:
        return issues

    # Separate agent chains (claude, codex, gemini, etc.) from standalone backends.
    # A standalone backend is one created by the collector when an LLM server
    # (llama-server, ollama, etc.) has no agent pointing to it.
    agent_chains = []
    standalone_chains = []

    for chain in chains:
        if chain.agent and chain.agent.display_name.endswith("(standalone)"):
            standalone_chains.append(chain)
        else:
            agent_chains.append(chain)

    # Collect all backend PIDs referenced by real agent chains
    referenced_pids: set[int] = set()
    for chain in agent_chains:
        if chain.backend and chain.backend.pid:
            referenced_pids.add(chain.backend.pid)

    # A standalone backend whose PID is not referenced by any agent is orphaned
    for chain in standalone_chains:
        if chain.backend and chain.backend.pid and \
           chain.backend.pid not in referenced_pids:
            issues.append(Issue(
                rule_id="ai-orphan-backend",
                severity="info",
                service=chain.id,
                message=f"LLM backend {chain.backend.provider} on "
                        f"{chain.backend.endpoint} has no connected agent.",
                hint="This backend is running but no agent is using it.",
                impact=[chain.id],
            ))
    return issues


def check_ai_gpu_overcommit(state: SystemState, cfg: dict) -> list[Issue]:
    """Detect when GPU memory is critically full with multiple LLM backends."""
    issues: list[Issue] = []
    chains = getattr(state, "ai_chains", [])
    if not chains:
        return issues

    # Collect all local backends with GPU layers
    gpu_backends = []
    for chain in chains:
        if chain.backend and chain.backend.backend_type == "local" and \
           chain.backend.gpu_layers and chain.backend.gpu_layers > 0:
            gpu_backends.append(chain)

    if len(gpu_backends) <= 1:
        return issues

    # Check GPU memory usage via nvidia-smi
    try:
        import subprocess
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.total,memory.used",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0:
            return issues

        for line in result.stdout.strip().splitlines():
            parts = line.split(",")
            if len(parts) == 2:
                total_mb = int(parts[0].strip())
                used_mb = int(parts[1].strip())
                usage_pct = (used_mb / total_mb * 100) if total_mb > 0 else 0

                if usage_pct > 90:
                    backend_names = [c.backend.model_name or c.backend.provider
                                     for c in gpu_backends]
                    issues.append(Issue(
                        rule_id="ai-gpu-overcommit",
                        severity="warning",
                        service="gpu:0",
                        message=f"GPU memory {usage_pct:.0f}% used with "
                                f"{len(gpu_backends)} active backends: "
                                f"{', '.join(backend_names)}.",
                        hint="Consider reducing GPU layers or stopping unused backends.",
                        impact=[c.id for c in gpu_backends],
                    ))
    except (FileNotFoundError, subprocess.TimeoutExpired, ValueError):
        pass

    return issues
