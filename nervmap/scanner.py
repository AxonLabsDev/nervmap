"""Shared scan logic used by both CLI and web server."""

from __future__ import annotations

import logging

from nervmap.models import SystemState
from nervmap.config import is_collector_enabled

logger = logging.getLogger("nervmap.scanner")


def collect(cfg: dict, deep: bool = False) -> SystemState:
    """Run all collectors and return aggregated SystemState."""
    from nervmap.discovery.docker import DockerCollector
    from nervmap.discovery.systemd import SystemdCollector
    from nervmap.discovery.ports import PortCollector
    from nervmap.discovery.process import ProcessCollector
    from nervmap.topology.mapper import DependencyMapper

    state = SystemState()

    # -- Discovery --
    if is_collector_enabled(cfg, "docker"):
        try:
            dc = DockerCollector()
            for svc in dc.collect():
                state.services.append(svc)
        except Exception:
            logger.debug("Docker collector failed", exc_info=True)

    if is_collector_enabled(cfg, "systemd"):
        try:
            sc = SystemdCollector()
            for svc in sc.collect():
                state.services.append(svc)
        except Exception:
            logger.debug("Systemd collector failed", exc_info=True)

    if is_collector_enabled(cfg, "ports"):
        try:
            pc = PortCollector()
            port_info = pc.collect()
            state.listening_ports = port_info.get("listening", {})
            state.established = port_info.get("established", [])
        except Exception:
            logger.debug("Port collector failed", exc_info=True)

    try:
        proc = ProcessCollector()
        for svc in proc.collect(state.services, state.listening_ports):
            state.services.append(svc)
    except Exception:
        logger.debug("Process collector failed", exc_info=True)

    # -- Resource info --
    try:
        import psutil
        for part in psutil.disk_partitions():
            try:
                usage = psutil.disk_usage(part.mountpoint)
                state.disk_usage[part.mountpoint] = usage.percent
            except Exception:
                logger.debug("Disk usage failed for %s", part.mountpoint)
        mem = psutil.virtual_memory()
        state.memory = {
            "total": mem.total,
            "available": mem.available,
            "percent": mem.percent,
        }
    except Exception:
        logger.debug("Resource info collection failed", exc_info=True)

    # -- Topology --
    try:
        mapper = DependencyMapper(state, cfg)
        state.connections = mapper.map()
    except Exception:
        logger.debug("Topology mapper failed", exc_info=True)

    return state


def full_scan(cfg: dict, no_code: bool = False) -> tuple[SystemState, list]:
    """Run full scan including source analysis and AI discovery. Returns (state, issues)."""
    from nervmap.diagnostics.engine import RuleRunner

    state = collect(cfg)

    # Source code analysis
    if not no_code:
        try:
            from nervmap.source.locator import ProjectLocator
            from nervmap.source.linker import CodeLinker
            locator = ProjectLocator(state, cfg)
            projects = locator.locate()
            if projects:
                linker = CodeLinker()
                linker.link(state.services, projects)
                state.projects = projects
        except Exception:
            logger.debug("Source code analysis failed", exc_info=True)

    # AI agent discovery
    if not no_code:
        try:
            from nervmap.ai.collector import AICollector
            ai_collector = AICollector(cfg)
            state.ai_chains = ai_collector.collect(state=state)
        except Exception:
            logger.debug("AI collector failed", exc_info=True)

    # Diagnostics
    runner = RuleRunner()
    issues = runner.evaluate(state, cfg)

    return state, issues
