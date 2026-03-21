"""Port discovery via /proc/net/tcp and ss."""

from __future__ import annotations
import logging
logger = logging.getLogger("nervmap.ports")

import os
import subprocess
import struct
import re


class PortCollector:
    """Discover listening and established TCP connections."""

    def collect(self) -> dict:
        """Returns {'listening': {port: bind_addr}, 'established': [dict]}."""
        listening: dict[int, str] = {}
        established: list[dict] = []

        # Primary: parse /proc/net/tcp and /proc/net/tcp6
        try:
            l, e = self._parse_proc_net()
            listening.update(l)
            established.extend(e)
        except Exception as _exc:
            logger.debug("Port collection error: %s", _exc)

        # Fallback/supplement with ss
        if not listening:
            try:
                l, e = self._parse_ss()
                listening.update(l)
                established.extend(e)
            except Exception as _exc:
                logger.debug("Port parse error", exc_info=True)

        return {"listening": listening, "established": established}

    def _parse_proc_net(self) -> tuple[dict[int, str], list[dict]]:
        """Parse /proc/net/tcp and tcp6."""
        listening: dict[int, str] = {}
        established: list[dict] = []

        for path in ["/proc/net/tcp", "/proc/net/tcp6"]:
            if not os.path.exists(path):
                continue
            try:
                with open(path, "r") as f:
                    lines = f.readlines()[1:]  # skip header
                for line in lines:
                    parts = line.split()
                    if len(parts) < 4:
                        continue
                    local = parts[1]
                    remote = parts[2]
                    state = parts[3]

                    local_addr, local_port = self._decode_addr(local, ipv6=(path.endswith("6")))
                    remote_addr, remote_port = self._decode_addr(remote, ipv6=(path.endswith("6")))

                    if state == "0A":  # LISTEN
                        listening[local_port] = local_addr
                    elif state == "01":  # ESTABLISHED
                        established.append({
                            "local_addr": local_addr,
                            "local_port": local_port,
                            "remote_addr": remote_addr,
                            "remote_port": remote_port,
                        })
            except Exception as _exc:
                continue

        return listening, established

    @staticmethod
    def _decode_addr(hex_str: str, ipv6: bool = False) -> tuple[str, int]:
        """Decode hex address:port from /proc/net/tcp."""
        addr_hex, port_hex = hex_str.split(":")
        port = int(port_hex, 16)

        if ipv6:
            # IPv6 is 32 hex chars
            if len(addr_hex) == 32:
                # Stored as 4 groups of 4 bytes in network byte order
                groups = []
                for i in range(0, 32, 8):
                    chunk = addr_hex[i:i+8]
                    val = int(chunk, 16)
                    val = struct.unpack(">I", struct.pack("<I", val))[0]
                    groups.append(f"{val:08x}")
                full = "".join(groups)
                # Format as proper IPv6
                parts = [full[i:i+4] for i in range(0, 32, 4)]
                addr = ":".join(parts)
                # Simplify ::ffff:x.x.x.x (IPv4-mapped)
                # Use 'full' (raw hex without colons) for reliable extraction
                if full.startswith("00000000" * 2 + "0000ffff"):
                    hex_ip = full[24:]  # last 8 hex chars = IPv4
                    a = int(hex_ip[0:2], 16)
                    b = int(hex_ip[2:4], 16)
                    c = int(hex_ip[4:6], 16)
                    d = int(hex_ip[6:8], 16)
                    addr = f"{a}.{b}.{c}.{d}"
                elif addr.startswith("0000:0000:0000:0000:0000:ffff:"):
                    # Fallback for other formats
                    hex_ip = full[24:]
                    a = int(hex_ip[0:2], 16)
                    b = int(hex_ip[2:4], 16)
                    c = int(hex_ip[4:6], 16)
                    d = int(hex_ip[6:8], 16)
                    addr = f"{a}.{b}.{c}.{d}"
                elif addr == "0000:0000:0000:0000:0000:0000:0000:0000":
                    addr = "::"
                elif addr == "0000:0000:0000:0000:0000:0000:0000:0001":
                    addr = "::1"
            else:
                addr = addr_hex
        else:
            # IPv4: stored as little-endian hex
            ip_int = int(addr_hex, 16)
            a = ip_int & 0xFF
            b = (ip_int >> 8) & 0xFF
            c = (ip_int >> 16) & 0xFF
            d = (ip_int >> 24) & 0xFF
            addr = f"{a}.{b}.{c}.{d}"

        return addr, port

    def _parse_ss(self) -> tuple[dict[int, str], list[dict]]:
        """Fallback: use ss command."""
        listening: dict[int, str] = {}
        established: list[dict] = []

        try:
            result = subprocess.run(
                ["ss", "-tlnp"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                for line in result.stdout.splitlines()[1:]:
                    match = re.search(r'(\S+):(\d+)\s', line)
                    if match:
                        addr = match.group(1)
                        port = int(match.group(2))
                        listening[port] = addr
        except Exception as _exc:
            logger.debug("Port collection error: %s", _exc)

        try:
            result = subprocess.run(
                ["ss", "-tnp"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                for line in result.stdout.splitlines()[1:]:
                    if "ESTAB" not in line:
                        continue
                    parts = line.split()
                    if len(parts) < 5:
                        continue
                    local = parts[3]
                    remote = parts[4]
                    lm = re.match(r'(.+):(\d+)$', local)
                    rm = re.match(r'(.+):(\d+)$', remote)
                    if lm and rm:
                        established.append({
                            "local_addr": lm.group(1),
                            "local_port": int(lm.group(2)),
                            "remote_addr": rm.group(1),
                            "remote_port": int(rm.group(2)),
                        })
        except Exception as _exc:
            logger.debug("Port collection error: %s", _exc)

        return listening, established
