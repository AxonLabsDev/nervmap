"""Process discovery via /proc filesystem."""

from __future__ import annotations

import logging
import os

from nervmap.models import Service
from nervmap.utils import redact_env

logger = logging.getLogger("nervmap.process")


class ProcessCollector:
    """Discover bare processes (not Docker/systemd) that listen on ports."""

    def collect(self, existing_services: list[Service], listening_ports: dict[int, str]) -> list[Service]:
        """Find processes for listening ports not already covered by docker/systemd."""
        # Build set of PIDs already known
        known_pids: set[int] = set()
        for svc in existing_services:
            if svc.pid:
                known_pids.add(svc.pid)

        # Map port -> pid from /proc
        port_to_pid = self._map_ports_to_pids()

        # Find uncovered listening ports
        new_services: list[Service] = []
        seen_pids: set[int] = set()

        for port, bind_addr in listening_ports.items():
            pid = port_to_pid.get(port)
            if pid is None or pid in known_pids or pid in seen_pids:
                continue

            seen_pids.add(pid)
            cmdline = self._read_cmdline(pid)
            if not cmdline:
                continue

            name = self._derive_name(cmdline)
            # Skip docker-proxy: internal Docker port forwarder, not a real service
            if name == "docker-proxy":
                continue
            env_vars = self._read_environ(pid)

            # Collect all ports for this PID
            pid_ports = [p for p, pp in port_to_pid.items() if pp == pid]

            svc = Service(
                id=f"process:{name}:{port}",
                name=name,
                type="process",
                status="running",
                ports=sorted(pid_ports),
                pid=pid,
                health="no_check",
                metadata={
                    "cmdline": cmdline,
                    "env": redact_env(env_vars),
                },
            )
            new_services.append(svc)

        return new_services

    def _map_ports_to_pids(self) -> dict[int, int]:
        """Map listening ports to PIDs by reading /proc/PID/fd symlinks."""
        port_to_inode: dict[int, int] = {}
        inode_to_pid: dict[int, int] = {}

        # Step 1: Parse /proc/net/tcp for listening socket inodes
        for net_path in ["/proc/net/tcp", "/proc/net/tcp6"]:
            try:
                with open(net_path, "r") as f:
                    for line in f.readlines()[1:]:
                        parts = line.split()
                        if len(parts) < 10:
                            continue
                        state = parts[3]
                        if state != "0A":  # LISTEN
                            continue
                        addr_port = parts[1]
                        _, port_hex = addr_port.split(":")
                        port = int(port_hex, 16)
                        inode = int(parts[9])
                        port_to_inode[port] = inode
            except Exception:
                continue

        # Step 2: Walk /proc/PID/fd to find socket inodes
        target_inodes = set(port_to_inode.values())
        if not target_inodes:
            return {}

        try:
            for entry in os.listdir("/proc"):
                if not entry.isdigit():
                    continue
                pid = int(entry)
                fd_dir = f"/proc/{pid}/fd"
                try:
                    for fd in os.listdir(fd_dir):
                        try:
                            link = os.readlink(f"{fd_dir}/{fd}")
                            if link.startswith("socket:["):
                                inode = int(link[8:-1])
                                if inode in target_inodes:
                                    inode_to_pid[inode] = pid
                        except (OSError, ValueError):
                            continue
                except (OSError, PermissionError):
                    continue
        except Exception:
            logger.debug("Process scan error", exc_info=True)

        # Step 3: Map port -> pid
        result: dict[int, int] = {}
        for port, inode in port_to_inode.items():
            pid = inode_to_pid.get(inode)
            if pid:
                result[port] = pid

        return result

    @staticmethod
    def _read_cmdline(pid: int) -> str:
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as f:
                raw = f.read(4096)
            return raw.replace(b"\x00", b" ").decode("utf-8", errors="replace").strip()
        except Exception:
            return ""

    @staticmethod
    def _read_environ(pid: int) -> dict[str, str]:
        """Read environment variables from /proc/PID/environ (needs root)."""
        env: dict[str, str] = {}
        try:
            with open(f"/proc/{pid}/environ", "rb") as f:
                raw = f.read(65536)
            for pair in raw.split(b"\x00"):
                decoded = pair.decode("utf-8", errors="replace")
                if "=" in decoded:
                    k, v = decoded.split("=", 1)
                    env[k] = v
        except (OSError, PermissionError):
            pass
        return env

    @staticmethod
    def _derive_name(cmdline: str) -> str:
        """Extract a short name from command line."""
        parts = cmdline.strip().split()
        if not parts:
            return "unknown"
        first = parts[0]
        # Get basename
        name = os.path.basename(first)
        # Strip common interpreters
        if name in ("python", "python3", "node", "java", "ruby", "perl", "bash", "sh"):
            if len(parts) > 1:
                return os.path.basename(parts[1]).split(".")[0]
        return name
