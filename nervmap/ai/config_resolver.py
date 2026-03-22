"""Resolve config files for AI agents based on known paths."""

from __future__ import annotations

import logging
import os
import re

from nervmap.ai.models import ConfigNode
from nervmap.ai.signatures import AgentSignature

logger = logging.getLogger("nervmap.ai.config")


class ConfigResolver:
    """Find config files that control AI agent behavior."""

    def resolve(self, agent_type: str, signature: AgentSignature,
                pid: int, cwd: str) -> list[ConfigNode]:
        """Resolve config files for an agent process."""
        configs: list[ConfigNode] = []
        home = self._get_home(pid)
        project_slug = self._cwd_to_slug(cwd)

        # 1. Static registry: known config paths
        for path_template in signature.config_paths:
            path = path_template.format(
                cwd=cwd,
                home=home,
                project_slug=project_slug,
            )
            # Handle glob-like patterns
            if "*" in path:
                configs.extend(self._resolve_glob(path))
            else:
                exists = os.path.isfile(path)
                content_hash = ConfigNode.hash_file(path) if exists else None
                config_type = self._infer_config_type(path)
                configs.append(ConfigNode(
                    path=path,
                    config_type=config_type,
                    detection="known_path",
                    confidence=0.9 if exists else 0.0,
                    exists=exists,
                    content_hash=content_hash,
                ))

        # 2. /proc/PID/fd snapshot: files currently open
        fd_configs = self._scan_open_files(pid)
        for fd_path in fd_configs:
            # Skip if already found via registry
            if any(c.path == fd_path for c in configs):
                # Upgrade confidence to 1.0 if we also see it in fd
                for c in configs:
                    if c.path == fd_path:
                        c.confidence = 1.0
                        c.detection = "proc_fd"
                continue
            configs.append(ConfigNode(
                path=fd_path,
                config_type=self._infer_config_type(fd_path),
                detection="proc_fd",
                confidence=1.0,
                exists=True,
                content_hash=ConfigNode.hash_file(fd_path),
            ))

        # Filter out non-existent known paths
        configs = [c for c in configs if c.exists]
        return configs

    def resolve_from_cmdline(self, cmdline: str, flags: dict[str, str]) -> list[ConfigNode]:
        """Extract config/model paths from command-line flags."""
        configs: list[ConfigNode] = []
        args = cmdline.split()

        for flag, field_name in flags.items():
            value = self._extract_flag_value(args, flag)
            if value and os.path.isfile(value):
                configs.append(ConfigNode(
                    path=value,
                    config_type="model" if "model" in field_name.lower() else "flag",
                    detection="cmdline_arg",
                    confidence=1.0,
                    exists=True,
                    content_hash=ConfigNode.hash_file(value),
                ))
        return configs

    @staticmethod
    def _get_home(pid: int) -> str:
        """Get HOME dir for a process from /proc/PID/environ."""
        try:
            with open(f"/proc/{pid}/environ", "rb") as f:
                data = f.read()
            for entry in data.split(b"\x00"):
                if entry.startswith(b"HOME="):
                    return entry[5:].decode("utf-8", errors="replace")
        except (OSError, PermissionError):
            pass
        return os.path.expanduser("~")

    @staticmethod
    def _cwd_to_slug(cwd: str) -> str:
        """Convert cwd to a Claude-style project slug."""
        return cwd.replace("/", "-").lstrip("-")

    @staticmethod
    def _infer_config_type(path: str) -> str:
        """Infer the config type from filename."""
        basename = os.path.basename(path).lower()
        if basename.endswith(".md"):
            if "memory" in path.lower():
                return "memory"
            return "instruction"
        if basename.endswith((".json", ".yml", ".yaml", ".toml")):
            return "settings"
        if basename.endswith((".gguf", ".bin", ".safetensors")):
            return "model"
        return "settings"

    @staticmethod
    def _scan_open_files(pid: int) -> list[str]:
        """Read /proc/PID/fd to find open config/model files."""
        configs = []
        fd_dir = f"/proc/{pid}/fd"
        try:
            for fd in os.listdir(fd_dir):
                try:
                    target = os.readlink(os.path.join(fd_dir, fd))
                    # Only include regular files that look like configs/models
                    if not target.startswith("/"):
                        continue
                    if any(target.endswith(ext) for ext in (
                        ".md", ".json", ".yml", ".yaml", ".toml",
                        ".gguf", ".bin", ".safetensors", ".env",
                    )):
                        configs.append(target)
                except (OSError, PermissionError):
                    continue
        except (OSError, PermissionError):
            pass
        return configs

    @staticmethod
    def _extract_flag_value(args: list[str], flag: str) -> str | None:
        """Extract value after a CLI flag like --model /path."""
        for i, arg in enumerate(args):
            if arg == flag and i + 1 < len(args):
                return args[i + 1]
            if arg.startswith(flag + "="):
                return arg[len(flag) + 1:]
        return None

    @staticmethod
    def _resolve_glob(pattern: str) -> list[ConfigNode]:
        """Resolve a path pattern with * wildcards."""
        import glob
        configs = []
        for path in glob.glob(pattern):
            if os.path.isfile(path):
                configs.append(ConfigNode(
                    path=path,
                    config_type="memory" if "memory" in path.lower() else "settings",
                    detection="known_path",
                    confidence=0.9,
                    exists=True,
                    content_hash=ConfigNode.hash_file(path),
                ))
        return configs
