"""Parse config files to trace the full instruction chain.

Traces which file references which other file, and what each file controls.
"""

from __future__ import annotations

import json
import logging
import os
import re

from nervmap.ai.models import ConfigNode

logger = logging.getLogger("nervmap.ai.chain_parser")

# Max depth to prevent infinite recursion on circular references
_MAX_DEPTH = 5


def trace_config_chain(config: ConfigNode, seen: set[str] | None = None,
                       depth: int = 0) -> ConfigNode:
    """Parse a config file and recursively trace referenced files.

    Returns the same ConfigNode enriched with role and children.
    """
    if seen is None:
        seen = set()
    if depth >= _MAX_DEPTH or config.path in seen or not config.exists:
        return config

    seen.add(config.path)

    basename = os.path.basename(config.path).lower()

    # Route to the appropriate parser
    if basename.endswith(".json"):
        _parse_json_config(config, seen, depth)
    elif basename.endswith(".md"):
        _parse_markdown_config(config, seen, depth)
    elif basename.endswith((".yml", ".yaml")):
        _parse_yaml_config(config, seen, depth)
    elif basename.endswith((".gguf", ".bin", ".safetensors")):
        config.role = "model weights"
        config.config_type = "model"

    return config


def _parse_json_config(config: ConfigNode, seen: set[str], depth: int):
    """Parse a JSON config file (settings.json, package.json, etc.)."""
    try:
        with open(config.path, "r", errors="replace") as f:
            data = json.load(f)
    except Exception:
        return

    basename = os.path.basename(config.path).lower()

    if basename == "settings.json" and "hooks" in data:
        _parse_claude_settings(config, data, seen, depth)
    elif basename == "settings.json":
        config.role = "agent settings"
    elif basename == "config.json":
        config.role = "agent configuration"


def _parse_claude_settings(config: ConfigNode, data: dict,
                           seen: set[str], depth: int):
    """Parse Claude Code settings.json with hooks, permissions, etc."""
    roles = []

    # Hooks — deduplicate by path, aggregate events
    hooks = data.get("hooks", {})
    if hooks:
        hook_map: dict[str, list[str]] = {}  # path -> [event_names]
        for event_name, event_hooks in hooks.items():
            for hook_entry in event_hooks:
                hook_list = hook_entry.get("hooks", [hook_entry])
                for h in hook_list:
                    cmd = h.get("command", "")
                    if not cmd:
                        continue
                    scripts = _extract_paths_from_command(cmd)
                    for script_path in scripts:
                        if os.path.isfile(script_path):
                            hook_map.setdefault(script_path, [])
                            if event_name not in hook_map[script_path]:
                                hook_map[script_path].append(event_name)
        for script_path, events in hook_map.items():
            if script_path not in seen:
                events_str = ", ".join(sorted(set(events)))
                child = ConfigNode(
                    path=script_path,
                    config_type="hook",
                    role=f"hook: {events_str}",
                    detection="referenced",
                    confidence=1.0,
                    exists=True,
                    content_hash=ConfigNode.hash_file(script_path),
                )
                config.children.append(child)
        if hook_map:
            roles.append(f"hooks ({len(hook_map)} scripts)")

    # Permissions
    perms = data.get("permissions", {})
    if perms:
        allow = len(perms.get("allow", []))
        deny = len(perms.get("deny", []))
        ask = len(perms.get("ask", []))
        roles.append(f"permissions (allow:{allow} deny:{deny} ask:{ask})")

    # Context files
    context_files = data.get("contextFiles", [])
    for cf in context_files:
        # Resolve relative to home or absolute
        if not os.path.isabs(cf):
            cf_abs = os.path.join(os.path.dirname(config.path), cf)
        else:
            cf_abs = cf
        if os.path.isfile(cf_abs) and cf_abs not in seen:
            child = ConfigNode(
                path=cf_abs,
                config_type="instruction",
                role="context file (auto-loaded)",
                detection="referenced",
                confidence=1.0,
                exists=True,
                content_hash=ConfigNode.hash_file(cf_abs),
            )
            trace_config_chain(child, seen, depth + 1)
            config.children.append(child)
    if context_files:
        roles.append(f"context files ({len(context_files)})")

    # Model/effort settings
    if data.get("alwaysThinkingEnabled"):
        roles.append("extended thinking: on")
    effort = data.get("effortLevel")
    if effort:
        roles.append(f"effort: {effort}")

    # Plugins
    plugins = data.get("extraKnownMarketplaces", {})
    if plugins:
        roles.append(f"plugins ({', '.join(plugins.keys())})")

    config.role = ", ".join(roles) if roles else "agent settings"


def _parse_markdown_config(config: ConfigNode, seen: set[str], depth: int):
    """Parse a Markdown instruction file and find referenced file paths."""
    try:
        with open(config.path, "r", errors="replace") as f:
            content = f.read()
    except Exception:
        return

    basename = os.path.basename(config.path).lower()

    # Assign role based on filename
    if basename == "claude.md":
        config.role = "project instructions (loaded every prompt)"
    elif basename == "agents.md":
        config.role = "shared agent rules"
    elif basename == "soul.md":
        config.role = "agent identity + personality"
    elif basename == "user.md":
        config.role = "user profile + preferences"
    elif "memory" in basename.lower() or "memory" in config.path.lower():
        config.role = "persistent memory"
        config.config_type = "memory"
    elif basename == "gemini.md":
        config.role = "project instructions"
    else:
        config.role = "instruction file"

    # Extract file path references from content
    # Match absolute paths like /home/user/project/identity.md
    path_pattern = re.compile(r'(?:^|\s|`|"|\')(/[a-zA-Z0-9_./-]+\.[a-zA-Z]{1,10})(?:\s|`|"|\'|$|,|\))', re.MULTILINE)
    for match in path_pattern.finditer(content):
        ref_path = match.group(1)
        # Skip URLs and common non-config patterns
        if "://" in ref_path or ref_path.startswith("/proc/") or \
           ref_path.startswith("/dev/") or ref_path.startswith("/tmp/"):
            continue
        if not os.path.isfile(ref_path) or ref_path in seen:
            continue
        # Only follow .md, .json, .yml, .yaml, .sh files
        ext = os.path.splitext(ref_path)[1].lower()
        if ext not in (".md", ".json", ".yml", ".yaml", ".sh", ".py", ".js"):
            continue

        child = ConfigNode(
            path=ref_path,
            config_type=_infer_type(ref_path),
            detection="referenced",
            confidence=0.9,
            exists=True,
            content_hash=ConfigNode.hash_file(ref_path),
        )
        trace_config_chain(child, seen, depth + 1)
        config.children.append(child)

    # Also extract cat/source commands: `cat /home/user/project/rules.md`
    cat_pattern = re.compile(r'(?:cat|source|\.)\s+(/[a-zA-Z0-9_./-]+)')
    for match in cat_pattern.finditer(content):
        ref_path = match.group(1)
        if os.path.isfile(ref_path) and ref_path not in seen:
            child = ConfigNode(
                path=ref_path,
                config_type=_infer_type(ref_path),
                role="startup read (cat/source)",
                detection="referenced",
                confidence=0.85,
                exists=True,
                content_hash=ConfigNode.hash_file(ref_path),
            )
            trace_config_chain(child, seen, depth + 1)
            config.children.append(child)


def _parse_yaml_config(config: ConfigNode, seen: set[str], depth: int):
    """Parse YAML config files."""
    config.role = "configuration"


def _extract_paths_from_command(cmd: str) -> list[str]:
    """Extract executable/script paths from a shell command string.

    Skips paths that are values of env var assignments (VAR=/path/...).
    """
    paths = []

    # Resolve ${CLAUDE_DIR} style variables
    claude_dir = os.path.expanduser("~/.claude")
    cmd_expanded = cmd.replace("${CLAUDE_DIR}", claude_dir)

    # Split on spaces, skip env var assignments (KEY=value)
    tokens = cmd_expanded.split()
    for token in tokens:
        if "=" in token and not token.startswith("/"):
            # Env var assignment (KEY=/path), skip the value
            continue
        # Extract absolute path from token
        match = re.match(r'(/[a-zA-Z0-9_./-]+)', token)
        if match:
            path = match.group(1)
            if path not in paths and os.path.isfile(path):
                paths.append(path)

    return paths


def _infer_type(path: str) -> str:
    """Infer config type from path."""
    basename = os.path.basename(path).lower()
    if basename.endswith(".md"):
        if "memory" in path.lower():
            return "memory"
        return "instruction"
    if basename.endswith((".json", ".yml", ".yaml", ".toml")):
        return "settings"
    if basename.endswith((".sh", ".py", ".js", ".ts")):
        return "script"
    return "settings"
