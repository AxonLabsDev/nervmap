"""Rich console renderer for NervMap."""

from __future__ import annotations

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich import box

from nervmap.models import SystemState, Issue
from nervmap.topology.fingerprints import ServiceFingerprinter


SEVERITY_COLORS = {
    "critical": "bold red",
    "warning": "yellow",
    "info": "blue",
}

STATUS_COLORS = {
    "running": "green",
    "stopped": "red",
    "degraded": "yellow",
    "unknown": "dim",
}

TYPE_ICONS = {
    "docker": "[cyan]D[/cyan]",
    "systemd": "[magenta]S[/magenta]",
    "process": "[blue]P[/blue]",
}

HEALTH_DISPLAY = {
    "healthy": "[green]OK[/green]",
    "unhealthy": "[red]FAIL[/red]",
    "no_check": "[dim]-[/dim]",
}


class ConsoleRenderer:
    """Beautiful Rich CLI output."""

    def __init__(self):
        self.console = Console()
        self.fp = ServiceFingerprinter()

    def render(self, state: SystemState, issues: list[Issue], elapsed: float, quiet: bool = False):
        """Full scan output."""
        self.console.print()

        # Header
        header = Text()
        header.append("  NervMap", style="bold cyan")
        header.append(" v0.1.0", style="dim")
        header.append(f"  |  scanned in {elapsed:.1f}s", style="dim")
        self.console.print(Panel(header, border_style="cyan", box=box.ROUNDED))

        if not quiet:
            self._render_services(state)
            self.console.print()

            if state.connections:
                self.render_deps(state)
                self.console.print()

        if issues:
            self.render_issues(issues)
        else:
            self.console.print("[green]  No issues detected.[/green]")

        # Summary line
        self.console.print()
        n_svc = len(state.services)
        n_conn = len(state.connections)
        n_issues = len(issues)
        n_crit = sum(1 for i in issues if i.severity == "critical")
        n_warn = sum(1 for i in issues if i.severity == "warning")

        summary = Text()
        summary.append(f"  {n_svc} services", style="bold")
        summary.append(f"  |  {n_conn} connections", style="dim")
        summary.append("  |  ", style="dim")
        if n_crit:
            summary.append(f"{n_crit} critical", style="bold red")
            summary.append("  ", style="dim")
        if n_warn:
            summary.append(f"{n_warn} warnings", style="yellow")
            summary.append("  ", style="dim")
        if n_issues == 0:
            summary.append("all clear", style="bold green")
        self.console.print(summary)
        self.console.print()

    def _render_services(self, state: SystemState):
        """Render service table."""
        table = Table(
            title="Services",
            box=box.SIMPLE_HEAVY,
            title_style="bold",
            show_lines=False,
            padding=(0, 1),
        )
        table.add_column("", width=1, justify="center")  # type icon
        table.add_column("Service", style="bold", min_width=12)
        table.add_column("Type", min_width=8)
        table.add_column("Status", min_width=8)
        table.add_column("Ports", min_width=6)
        table.add_column("Health", min_width=6)
        table.add_column("PID", min_width=5, justify="right")

        for svc in sorted(state.services, key=lambda s: (s.type, s.name)):
            icon = TYPE_ICONS.get(svc.type, " ")
            status_style = STATUS_COLORS.get(svc.status, "dim")
            ports_str = ", ".join(str(p) for p in svc.ports[:5])
            if len(svc.ports) > 5:
                ports_str += f" +{len(svc.ports) - 5}"
            health = HEALTH_DISPLAY.get(svc.health, svc.health)
            pid_str = str(svc.pid) if svc.pid else "-"

            table.add_row(
                icon,
                svc.name,
                self.fp.fingerprint_service(svc),
                Text(svc.status, style=status_style),
                ports_str or "-",
                health,
                pid_str,
            )

        self.console.print(table)

    def render_deps(self, state: SystemState):
        """Render dependency graph with ASCII arrows."""
        if not state.connections:
            self.console.print("[dim]  No dependencies detected.[/dim]")
            return

        self.console.print("[bold]  Dependencies[/bold]")
        self.console.print()

        for conn in state.connections:
            port_info = f":{conn.target_port}" if conn.target_port else ""
            conf = f"{conn.confidence:.0%}"
            style = "green" if conn.confidence >= 0.8 else "yellow" if conn.confidence >= 0.6 else "dim"

            line = Text()
            line.append(f"  {conn.source}", style="bold")
            line.append(f" --[{conn.type}{port_info}]--> ", style=style)
            line.append(f"{conn.target}", style="bold")
            line.append(f"  ({conf})", style="dim")
            self.console.print(line)

    def render_issues(self, issues: list[Issue]):
        """Render issues with severity coloring."""
        if not issues:
            self.console.print("[green]  No issues detected.[/green]")
            return

        table = Table(
            title="Issues",
            box=box.SIMPLE_HEAVY,
            title_style="bold red" if any(i.severity == "critical" for i in issues) else "bold yellow",
            show_lines=True,
            padding=(0, 1),
        )
        table.add_column("Sev", width=4, justify="center")
        table.add_column("Rule", min_width=10)
        table.add_column("Service", min_width=10)
        table.add_column("Message", min_width=20)
        table.add_column("Hint", min_width=15, style="dim")

        severity_icons = {
            "critical": "[bold red]CRIT[/bold red]",
            "warning": "[yellow]WARN[/yellow]",
            "info": "[blue]INFO[/blue]",
        }

        for issue in issues:
            sev_display = severity_icons.get(issue.severity, issue.severity)
            sev_color = SEVERITY_COLORS.get(issue.severity, "white")

            table.add_row(
                sev_display,
                issue.rule_id,
                issue.service,
                Text(issue.message, style=sev_color),
                issue.hint,
            )

        self.console.print(table)
