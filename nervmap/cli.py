"""NervMap CLI — Click-based command interface."""

from __future__ import annotations

import json as json_mod
import logging
import sys
import time

import click

logger = logging.getLogger("nervmap")

from nervmap import __version__
from nervmap.config import load_config, is_collector_enabled
from nervmap.models import SystemState


def _collect(cfg: dict, deep: bool = False) -> SystemState:
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


def _get_flag(ctx, name: str, local_value):
    """Get flag value: prefer local (subcommand) if explicitly set, else parent context."""
    if local_value is not None and local_value is not False and local_value != 0:
        return local_value
    return ctx.obj.get(name, False)


@click.group(invoke_without_command=True)
@click.option("--json", "as_json", is_flag=True, help="Machine-readable JSON output.")
@click.option("--quiet", is_flag=True, help="Show only issues, no service list.")
@click.option("--deep", is_flag=True, help="Deep scan (parse config files).")
@click.option("--config", "config_path", default=None, help="Path to .nervmap.yml.")
@click.option("--show-secrets", is_flag=True, help="Include raw secrets in output (dangerous).")
@click.option("--verbose", "-v", is_flag=True, help="Enable debug logging.")
@click.option("--no-hooks", is_flag=True, help="Skip shell hook execution.")
@click.pass_context
def main(ctx, as_json, quiet, deep, config_path, show_secrets, verbose, no_hooks):
    """NervMap -- Infrastructure cartography CLI."""
    import logging
    if verbose:
        logging.basicConfig(level=logging.DEBUG, format="%(name)s %(levelname)s: %(message)s")
    ctx.ensure_object(dict)
    ctx.obj["json"] = as_json
    ctx.obj["quiet"] = quiet
    ctx.obj["deep"] = deep
    ctx.obj["config_path"] = config_path
    ctx.obj["show_secrets"] = show_secrets
    ctx.obj["no_hooks"] = no_hooks

    if ctx.invoked_subcommand is None:
        ctx.invoke(scan)


@main.command()
@click.option("--json", "as_json", is_flag=True, help="Machine-readable JSON output.")
@click.option("--quiet", is_flag=True, help="Show only issues, no service list.")
@click.option("--deep", is_flag=True, help="Deep scan (parse config files).")
@click.pass_context
def scan(ctx, as_json, quiet, deep):
    """Full infrastructure scan (default)."""
    import logging
    logger = logging.getLogger("nervmap.cli")

    from nervmap.diagnostics.engine import RuleRunner
    from nervmap.output.console import ConsoleRenderer
    from nervmap.output.json_out import JsonRenderer
    from nervmap.output.hooks import HookRunner

    cfg = load_config(ctx.obj.get("config_path"))
    as_json = _get_flag(ctx, "json", as_json)
    quiet = _get_flag(ctx, "quiet", quiet)
    deep = _get_flag(ctx, "deep", deep)
    show_secrets = ctx.obj.get("show_secrets", False)
    no_hooks = ctx.obj.get("no_hooks", False)

    logger.debug("Starting scan (deep=%s, json=%s, quiet=%s)", deep, as_json, quiet)

    t0 = time.monotonic()
    state = _collect(cfg, deep=deep)
    logger.debug("Discovery complete: %d services, %d listening ports", len(state.services), len(state.listening_ports))

    runner = RuleRunner()
    issues = runner.evaluate(state, cfg)
    logger.debug("Diagnostics complete: %d issues found", len(issues))

    elapsed = time.monotonic() - t0

    if as_json:
        renderer = JsonRenderer()
        renderer.render(state, issues, elapsed, show_secrets=show_secrets)
    else:
        renderer = ConsoleRenderer()
        renderer.render(state, issues, elapsed, quiet=quiet)

    # Fire hooks
    if not no_hooks:
        try:
            hooks = HookRunner(cfg)
            hooks.fire(state, issues)
        except Exception:
            logger.debug("Hook execution failed", exc_info=True)


@main.command()
@click.option("--dot", is_flag=True, help="Output in Graphviz DOT format.")
@click.option("--mermaid", is_flag=True, help="Output in Mermaid format.")
@click.pass_context
def deps(ctx, dot, mermaid):
    """Show dependency graph."""
    cfg = load_config(ctx.obj.get("config_path"))
    state = _collect(cfg)

    if ctx.obj.get("json"):
        click.echo(json_mod.dumps([c.to_dict() for c in state.connections], indent=2))
        return

    if dot:
        click.echo("digraph nervmap {")
        click.echo('  rankdir=LR;')
        for c in state.connections:
            label = f"{c.type} :{c.target_port}" if c.target_port else c.type
            click.echo(f'  "{c.source}" -> "{c.target}" [label="{label}"];')
        click.echo("}")
        return

    if mermaid:
        click.echo("graph LR")
        for c in state.connections:
            label = f"{c.type} :{c.target_port}" if c.target_port else c.type
            safe_src = c.source.replace(":", "_")
            safe_tgt = c.target.replace(":", "_")
            click.echo(f"  {safe_src}[{c.source}] -->|{label}| {safe_tgt}[{c.target}]")
        return

    # Pretty print
    from nervmap.output.console import ConsoleRenderer
    renderer = ConsoleRenderer()
    renderer.render_deps(state)


@main.command()
@click.option("--critical", is_flag=True, help="Only critical issues.")
@click.pass_context
def issues(ctx, critical):
    """Show only diagnosed issues."""
    from nervmap.diagnostics.engine import RuleRunner
    from nervmap.output.console import ConsoleRenderer
    from nervmap.output.json_out import JsonRenderer

    cfg = load_config(ctx.obj.get("config_path"))
    state = _collect(cfg)

    runner = RuleRunner()
    all_issues = runner.evaluate(state, cfg)

    if critical:
        all_issues = [i for i in all_issues if i.severity == "critical"]

    if ctx.obj.get("json"):
        click.echo(json_mod.dumps([i.to_dict() for i in all_issues], indent=2))
    else:
        renderer = ConsoleRenderer()
        renderer.render_issues(all_issues)


@main.command("version")
def version_cmd():
    """Show NervMap version."""
    click.echo(f"nervmap {__version__}")
