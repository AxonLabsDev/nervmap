"""AI agent and LLM backend discovery."""

from __future__ import annotations

import logging
import os
import re
import subprocess

from nervmap.ai.models import (
    AIChain, SessionNode, AgentNode, ConfigNode, BackendNode, ProxyNode,
)
from nervmap.ai.signatures import (
    AGENT_SIGNATURES, BACKEND_SIGNATURES,
    match_agent, match_backend, load_custom_profiles,
)
from nervmap.ai.config_resolver import ConfigResolver

logger = logging.getLogger("nervmap.ai.collector")


class AICollector:
    """Discover AI agents and LLM backends on the system."""

    def __init__(self, cfg: dict | None = None):
        self.cfg = cfg or {}
        self.config_resolver = ConfigResolver()
        self._tmux_panes: dict[int, str] | None = None  # pid -> session
        self._ttyd_map: dict[int, dict] | None = None    # pid -> {port, session}
        # Load custom profiles from .nervmap.yml
        self._extra_agents, self._extra_backends = load_custom_profiles(self.cfg)

    def collect(self, state=None) -> list[AIChain]:
        """Run full AI discovery and return chains."""
        chains: list[AIChain] = []

        # Phase 1: Scan all processes for agents + backends + ttyd + proxies
        agents_raw = []
        backends_raw = []
        proxies_raw = []
        self._ttyd_map = {}

        for pid in self._iter_pids():
            cmdline = self._read_cmdline(pid)
            if not cmdline:
                continue

            # Detect ttyd during same scan
            if "ttyd" in cmdline:
                self._parse_ttyd_cmdline(pid, cmdline)

            # Detect socat proxies (TCP forwarding)
            if "socat" in cmdline and "TCP-LISTEN" in cmdline:
                proxy = self._parse_socat_cmdline(pid, cmdline)
                if proxy:
                    proxies_raw.append(proxy)

            agent_sig = match_agent(cmdline, self._extra_agents)
            if agent_sig:
                cwd = self._read_cwd(pid)
                agents_raw.append({
                    "pid": pid,
                    "cmdline": cmdline,
                    "cwd": cwd,
                    "signature": agent_sig,
                })

            backend_sig = match_backend(cmdline, self._extra_backends)
            if backend_sig:
                backends_raw.append({
                    "pid": pid,
                    "cmdline": cmdline,
                    "signature": backend_sig,
                })

        # Phase 2: Resolve tmux sessions (ttyd already loaded in Phase 1)
        self._load_tmux_panes()

        # Build backend nodes
        backend_nodes: list[BackendNode] = []
        for bk in backends_raw:
            node = self._build_backend_node(bk)
            if node:
                backend_nodes.append(node)

        # Build agent chains
        for ag in agents_raw:
            chain = self._build_agent_chain(ag, backend_nodes)
            if chain:
                chains.append(chain)

        # Build standalone backend chains (LLM servers without an agent)
        agent_pids = {ag["pid"] for ag in agents_raw}
        for bk_node in backend_nodes:
            if bk_node.pid and bk_node.pid not in agent_pids:
                # Find proxy that forwards to this backend
                proxy = self._find_proxy_for_port(
                    proxies_raw, bk_node.ports[0] if bk_node.ports else None)
                chain = AIChain(
                    id=f"ai:{bk_node.provider}:{bk_node.pid}",
                    status="running",
                    agent=AgentNode(
                        agent_type=bk_node.provider,
                        pid=bk_node.pid,
                        cwd="",
                        cmdline="",
                        display_name=f"{bk_node.provider} (standalone)",
                    ),
                    backend=bk_node,
                    proxy=proxy,
                )
                chains.append(chain)

        # Detect consumers: find processes connecting to backend/proxy ports
        self._detect_consumers(chains, state)

        return chains

    def _build_agent_chain(self, ag: dict, backends: list[BackendNode]) -> AIChain | None:
        """Build a full chain for an agent process."""
        sig = ag["signature"]
        pid = ag["pid"]
        cwd = ag["cwd"]

        # Agent node
        agent_node = AgentNode(
            agent_type=sig.agent_type,
            pid=pid,
            cwd=cwd,
            cmdline=ag["cmdline"],
            display_name=sig.display_name,
        )

        # Session node (tmux + ttyd)
        session_node = self._resolve_session(pid)

        # Config files
        configs = self.config_resolver.resolve(
            sig.agent_type, sig, pid, cwd,
        )

        # Trace the full config chain (file references file references file...)
        from nervmap.ai.chain_parser import trace_config_chain
        for conf in configs:
            trace_config_chain(conf)

        # Backend node
        backend_node = self._match_backend_for_agent(sig, backends, pid)

        chain = AIChain(
            id=f"ai:{sig.agent_type}:{pid}",
            status="running",
            session=session_node,
            agent=agent_node,
            configs=configs,
            backend=backend_node,
        )
        return chain

    def _build_backend_node(self, bk: dict) -> BackendNode | None:
        """Build a BackendNode from a discovered backend process."""
        sig = bk["signature"]
        cmdline = bk["cmdline"]
        pid = bk["pid"]
        args = cmdline.split()

        # Extract host/port
        host = self._extract_flag(args, sig.host_flag) or "127.0.0.1"
        port_str = self._extract_flag(args, sig.port_flag)
        port = int(port_str) if port_str and port_str.isdigit() else None

        # Extract model path
        model_path = None
        model_name = None
        if sig.model_flag:
            model_path = self._extract_flag(args, sig.model_flag)
            # Also try short flags like -m
            if not model_path and sig.model_flag == "--model":
                model_path = self._extract_flag(args, "-m")
            if model_path:
                model_name = self._parse_model_name(model_path)

        # Extract extra flags (gpu_layers, context_size, etc.)
        gpu_layers = None
        context_size = None
        for flag, field_name in sig.extra_flags.items():
            value = self._extract_flag(args, flag)
            if value and value.isdigit():
                if field_name == "gpu_layers":
                    gpu_layers = int(value)
                elif field_name == "context_size":
                    context_size = int(value)

        endpoint = f"{host}:{port}" if port else host

        return BackendNode(
            backend_type="local",
            provider=sig.backend_type,
            endpoint=endpoint,
            pid=pid,
            model_name=model_name,
            model_path=model_path,
            gpu_layers=gpu_layers,
            context_size=context_size,
            ports=[port] if port else [],
        )

    def _match_backend_for_agent(self, sig, backends: list[BackendNode],
                                 pid: int = 0) -> BackendNode:
        """Match an agent to its LLM backend."""
        if sig.backend_type == "cloud":
            return BackendNode(
                backend_type="cloud",
                provider=sig.provider,
                endpoint=f"api.{sig.provider}.com",
                auth_method=self._detect_auth_method(sig, pid),
            )
        # For local agents, find matching backend by provider
        for bk in backends:
            if bk.provider == sig.provider:
                return bk
        return BackendNode(
            backend_type="unknown",
            provider=sig.provider,
            endpoint="unknown",
        )

    def _resolve_session(self, agent_pid: int) -> SessionNode | None:
        """Find tmux session and ttyd terminal for an agent PID."""
        session = SessionNode()

        # Find tmux session via pane PID ancestry
        if self._tmux_panes:
            for pane_pid, sess_name in self._tmux_panes.items():
                if self._is_descendant(agent_pid, pane_pid) or pane_pid == agent_pid:
                    session.mux_type = "tmux"
                    session.mux_session = sess_name
                    break

        # Find ttyd terminal
        if self._ttyd_map:
            for ttyd_pid, info in self._ttyd_map.items():
                ttyd_session = info.get("session", "")
                if session.mux_session and ttyd_session and \
                   session.mux_session in ttyd_session:
                    session.terminal_type = "ttyd"
                    session.terminal_pid = ttyd_pid
                    session.terminal_port = info.get("port")
                    session.terminal_bind = info.get("bind")
                    break

        if session.mux_session or session.terminal_type:
            return session
        return None

    def _load_tmux_panes(self):
        """Load tmux pane PIDs and session names."""
        self._tmux_panes = {}
        try:
            result = subprocess.run(
                ["tmux", "list-panes", "-a", "-F",
                 "#{pane_pid} #{session_name}"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode != 0:
                return
            for line in result.stdout.splitlines():
                parts = line.split(None, 1)
                if len(parts) == 2:
                    try:
                        self._tmux_panes[int(parts[0])] = parts[1]
                    except ValueError:
                        continue
        except Exception:
            logger.debug("Cannot enumerate tmux panes", exc_info=True)

    def _parse_ttyd_cmdline(self, pid: int, cmdline: str):
        """Parse a ttyd process cmdline and store in ttyd map."""
        args = cmdline.split()
        port = None
        bind_addr = None
        session_target = ""

        for i, arg in enumerate(args):
            if arg == "-p" and i + 1 < len(args):
                try:
                    port = int(args[i + 1])
                except ValueError:
                    pass
            elif arg == "-i" and i + 1 < len(args):
                bind_addr = args[i + 1]

        # Extract target session from tmux command at the end
        if "tmux" in cmdline:
            tmux_idx = cmdline.index("tmux")
            tmux_part = cmdline[tmux_idx:]
            s_match = re.search(r"(?:-[st]|attach\s+-t)\s+(\S+)", tmux_part)
            if s_match:
                session_target = s_match.group(1)

        if port:
            self._ttyd_map[pid] = {
                "port": port,
                "bind": bind_addr,
                "session": session_target,
            }

    def _detect_auth_method(self, sig, pid: int = 0) -> str:
        """Detect if agent uses API key or OAuth by checking process env."""
        if not pid:
            return "oauth"
        try:
            with open(f"/proc/{pid}/environ", "rb") as f:
                data = f.read()
            env_str = data.decode("utf-8", errors="replace")
            for env_key in sig.env_signatures:
                if env_key.endswith("_KEY") and env_key + "=" in env_str:
                    return "api_key"
        except (OSError, PermissionError):
            pass
        return "oauth"

    @staticmethod
    def _is_descendant(pid: int, ancestor: int) -> bool:
        """Check if pid is a descendant of ancestor via ppid chain."""
        current = pid
        seen = set()
        while current > 1 and current not in seen:
            seen.add(current)
            if current == ancestor:
                return True
            try:
                with open(f"/proc/{current}/stat", "r") as f:
                    # ppid is field 4 (0-indexed after closing paren)
                    content = f.read()
                    after_paren = content.split(")")[-1].split()
                    current = int(after_paren[1])  # PPID
            except (OSError, ValueError, IndexError):
                break
        return False

    @staticmethod
    def _iter_pids():
        """Iterate over all numeric PIDs in /proc."""
        try:
            for entry in os.listdir("/proc"):
                if entry.isdigit():
                    yield int(entry)
        except OSError:
            pass

    @staticmethod
    def _read_cmdline(pid: int) -> str:
        """Read /proc/PID/cmdline as a string."""
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as f:
                data = f.read()
            return data.replace(b"\x00", b" ").decode("utf-8", errors="replace").strip()
        except (OSError, PermissionError):
            return ""

    @staticmethod
    def _read_cwd(pid: int) -> str:
        """Read /proc/PID/cwd symlink."""
        try:
            return os.readlink(f"/proc/{pid}/cwd")
        except (OSError, PermissionError):
            return ""

    @staticmethod
    def _extract_flag(args: list[str], flag: str) -> str | None:
        """Extract value after a CLI flag."""
        if not flag:
            return None
        for i, arg in enumerate(args):
            if arg == flag and i + 1 < len(args):
                return args[i + 1]
            if arg.startswith(flag + "="):
                return arg[len(flag) + 1:]
        return None

    @staticmethod
    def _parse_model_name(model_path: str) -> str:
        """Extract a clean model name from a file path."""
        basename = os.path.basename(model_path)
        # Remove extension
        name = basename.rsplit(".", 1)[0] if "." in basename else basename
        return name

    @staticmethod
    def _parse_socat_cmdline(pid: int, cmdline: str) -> ProxyNode | None:
        """Parse a socat TCP-LISTEN/TCP forwarding command."""
        # socat TCP-LISTEN:18123,bind=1.2.3.4,... TCP:127.0.0.1:8123
        listen_match = re.search(r"TCP-LISTEN:(\d+)(?:,bind=([^,\s]+))?", cmdline)
        target_match = re.search(r"TCP:([^:,\s]+):(\d+)", cmdline)
        if not listen_match or not target_match:
            return None
        try:
            return ProxyNode(
                proxy_type="socat",
                pid=pid,
                listen_port=int(listen_match.group(1)),
                listen_bind=listen_match.group(2),
                target_port=int(target_match.group(2)),
                target_host=target_match.group(1),
            )
        except (ValueError, IndexError):
            return None

    @staticmethod
    def _find_proxy_for_port(proxies: list[ProxyNode], port: int | None) -> ProxyNode | None:
        """Find a proxy that forwards to a specific backend port."""
        if not port:
            return None
        for proxy in proxies:
            if proxy.target_port == port:
                return proxy
        return None

    def _detect_consumers(self, chains: list[AIChain], state=None):
        """Find processes that connect to backend/proxy ports (consumers).

        Uses established TCP connections from SystemState if available,
        otherwise uses /proc/net/tcp.
        """
        if not state:
            return

        # Build a map of backend ports -> chain IDs
        port_to_chain: dict[int, str] = {}
        for chain in chains:
            if chain.backend and chain.backend.ports:
                for p in chain.backend.ports:
                    port_to_chain[p] = chain.id
            if chain.proxy and chain.proxy.listen_port:
                port_to_chain[chain.proxy.listen_port] = chain.id

        if not port_to_chain:
            return

        # Check established connections for consumers
        established = getattr(state, "established", [])
        chain_consumers: dict[str, set[str]] = {}

        for conn in established:
            remote_port = conn.get("remote_port") or conn.get("dst_port")
            if not remote_port or remote_port not in port_to_chain:
                continue
            chain_id = port_to_chain[remote_port]
            local_pid = conn.get("pid")
            if not local_pid:
                continue
            # Try to identify the consumer by its process name
            cmdline = self._read_cmdline(local_pid)
            if not cmdline:
                continue
            # Extract a short consumer name
            parts = cmdline.split()
            name = os.path.basename(parts[0]) if parts else f"pid:{local_pid}"
            chain_consumers.setdefault(chain_id, set()).add(name)

        # Assign consumers to chains
        for chain in chains:
            consumers = chain_consumers.get(chain.id, set())
            if consumers:
                chain.consumers = sorted(consumers)
