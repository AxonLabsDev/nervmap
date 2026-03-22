"""Rich console renderer for AI chains."""

from __future__ import annotations

import os
from collections import defaultdict

from rich.console import Console
from rich.text import Text

from nervmap.ai.models import AIChain


class AIRenderer:
    """Render AI execution chains with Rich."""

    def __init__(self):
        self.console = Console()

    def render(self, chains: list[AIChain]):
        """Render all AI chains, grouped by tmux session."""
        if not chains:
            self.console.print("[dim]  No AI agents detected.[/dim]")
            return

        self.console.print()
        self.console.print("[bold]  AI Execution Chains[/bold]")
        self.console.print()

        # Group chains by session
        groups: dict[str, list[AIChain]] = defaultdict(list)
        for chain in chains:
            key = self._group_key(chain)
            groups[key].append(chain)

        # Render each group
        for group_name, group_chains in groups.items():
            self._render_group(group_name, group_chains)

    def _group_key(self, chain: AIChain) -> str:
        """Generate a group key from session info."""
        parts = []
        if chain.session:
            if chain.session.terminal_port:
                parts.append(f"ttyd :{chain.session.terminal_port}")
            if chain.session.mux_session:
                parts.append(f'tmux "{chain.session.mux_session}"')
        if not parts:
            # Standalone backends or agents without session
            if chain.backend and chain.backend.backend_type == "local":
                return f"local: {chain.backend.provider}"
            return "no session"
        return " -> ".join(parts)

    def _render_group(self, group_name: str, chains: list[AIChain]):
        """Render a group of chains under a session header."""
        # Group header
        header = Text()
        header.append(f"  {group_name}", style="bold")
        self.console.print(header)

        for chain in chains:
            self._render_chain(chain)

        self.console.print()

    def _render_chain(self, chain: AIChain):
        """Render a single chain within its group."""
        home = os.path.expanduser("~")

        # Agent line with PID and backend
        line = Text()
        agent_name = chain.agent.display_name if chain.agent else chain.id
        line.append(f"    {agent_name}", style="cyan")
        line.append(f" [{chain.agent.pid}]", style="dim")

        if chain.agent and chain.agent.cwd:
            cwd = chain.agent.cwd
            if cwd.startswith(home):
                cwd = "~" + cwd[len(home):]
            line.append(f" cwd={cwd}", style="dim")

        if chain.backend:
            if chain.backend.backend_type == "cloud":
                line.append(f" -> {chain.backend.provider}", style="yellow")
                if chain.backend.auth_method:
                    line.append(f" ({chain.backend.auth_method})", style="dim")
            elif chain.backend.model_name:
                line.append(f" -> {chain.backend.model_name}", style="green")
                if chain.backend.gpu_layers is not None:
                    line.append(f" ({chain.backend.gpu_layers}L", style="dim")
                    if chain.backend.context_size is not None:
                        line.append(f" ctx={chain.backend.context_size}", style="dim")
                    line.append(")", style="dim")
            elif chain.backend.endpoint:
                line.append(f" -> {chain.backend.endpoint}", style="dim")

        self.console.print(line)

        # Configs — full chain tree
        if chain.configs:
            for conf in chain.configs:
                self._render_config_node(conf, home, indent=6)

    def _render_config_node(self, conf, home: str, indent: int = 6):
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
