"""Configuration loader for .nervmap.yml."""

from __future__ import annotations
import logging
logger = logging.getLogger("nervmap.config")

from pathlib import Path
from typing import Any

import yaml


DEFAULTS: dict[str, Any] = {
    "scan": {
        "docker": True,
        "systemd": True,
        "ports": True,
    },
    "ignore": {
        "ports": [],
        "services": [],
    },
    "timeouts": {
        "http": 5,
        "tcp": 3,
    },
    "custom_services": [],
    "hooks": {},
}


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config(path: str | None = None) -> dict[str, Any]:
    """Load config from .nervmap.yml, falling back to defaults."""
    candidates: list[Path] = []

    if path:
        candidates.append(Path(path))
    else:
        candidates.append(Path.cwd() / ".nervmap.yml")
        candidates.append(Path.home() / ".nervmap" / "config.yml")

    for candidate in candidates:
        try:
            if candidate.is_file():
                with open(candidate, "r") as f:
                    user_cfg = yaml.safe_load(f) or {}
                return _deep_merge(DEFAULTS, user_cfg)
        except Exception as _exc:
            logger.warning("Failed to parse config %s: %s", candidate, _exc)
            continue

    return DEFAULTS.copy()


def get_ignored_ports(cfg: dict) -> set[int]:
    return set(cfg.get("ignore", {}).get("ports", []))


def get_ignored_service_patterns(cfg: dict) -> list[str]:
    return cfg.get("ignore", {}).get("services", [])


def is_collector_enabled(cfg: dict, name: str) -> bool:
    return cfg.get("scan", {}).get(name, True)
