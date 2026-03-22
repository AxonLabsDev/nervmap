"""Rich console renderer for AI chains."""

from __future__ import annotations

from rich.console import Console
from rich.text import Text
from rich import box
from rich.table import Table

from nervmap.ai.models import AIChain


class AIRenderer:
    """Render AI execution chains with Rich."""

    def __init__(self):
        self.console = Console()

    def render(self, chains: list[AIChain]):
        """Render all AI chains."""
        if not chains:
            self.console.print("[dim]  No AI agents detected.[/dim]")
            return

        self.console.print()
        self.console.print("[bold]  AI Execution Chains[/bold]")
        self.console.print()

        for chain in chains:
            self._render_chain(chain)

    def _render_chain(self, chain: AIChain):
        """Render a single chain as a tree."""
        # Header line
        header = Text()
        agent_name = chain.agent.display_name if chain.agent else chain.id
        header.append(f"  {agent_name}", style="bold cyan")
        header.append(f" (PID {chain.agent.pid})", style="dim")
        if chain.backend:
            if chain.backend.backend_type == "cloud":
                header.append(f" -> {chain.backend.provider} cloud", style="yellow")
            else:
                header.append(f" -> {chain.backend.provider} local", style="green")
        self.console.print(header)

        # Chain path line
        path = Text()
        path.append("    ", style="dim")
        parts = []

        if chain.session:
            if chain.session.terminal_port:
                parts.append(f"ttyd :{chain.session.terminal_port}")
            if chain.session.mux_session:
                parts.append(f'tmux "{chain.session.mux_session}"')

        if chain.agent:
            parts.append(f"{chain.agent.agent_type} [{chain.agent.pid}]")

        path.append(" -> ".join(parts), style="bold")
        self.console.print(path)

        # Configs — full chain tree
        if chain.configs:
            import os
            home = os.path.expanduser("~")
            for conf in chain.configs:
                self._render_config_node(conf, home, indent=4)

        # Backend details
        if chain.backend:
            back = Text()
            back.append("    Backend: ", style="dim")
            if chain.backend.backend_type == "cloud":
                back.append(f"{chain.backend.endpoint}", style="yellow")
                if chain.backend.auth_method:
                    back.append(f" ({chain.backend.auth_method})", style="dim")
            else:
                if chain.backend.model_name:
                    back.append(f"{chain.backend.model_name}", style="green")
                back.append(f", {chain.backend.endpoint}", style="dim")
                if chain.backend.gpu_layers is not None:
                    back.append(f", {chain.backend.gpu_layers} GPU layers", style="dim")
                if chain.backend.context_size is not None:
                    back.append(f", ctx {chain.backend.context_size}", style="dim")
            self.console.print(back)

        self.console.print()

    def _render_config_node(self, conf, home: str, indent: int = 4):
        """Render a config node and its children as a tree."""
        prefix = " " * indent

        # Icon based on type
        icons = {
            "instruction": "[cyan]I[/cyan]",
            "settings": "[yellow]S[/yellow]",
            "memory": "[magenta]M[/magenta]",
            "hook": "[red]H[/red]",
            "script": "[red]H[/red]",
            "model": "[green]W[/green]",
        }
        icon = icons.get(conf.config_type, "[dim]?[/dim]")

        # Shorten path
        display_path = conf.path
        if display_path.startswith(home):
            display_path = "~" + display_path[len(home):]

        role_str = f"  [dim]({conf.role})[/dim]" if conf.role else ""
        self.console.print(f"{prefix}{icon} {display_path}{role_str}")

        # Children
        for child in conf.children:
            self._render_config_node(child, home, indent + 3)
