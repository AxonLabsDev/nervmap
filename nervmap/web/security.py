"""Path security for the web dashboard file API."""

from __future__ import annotations

import os

# Extensions allowed for reading/serving
ALLOWED_EXTENSIONS = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".mjs", ".cjs",
    ".json", ".yml", ".yaml", ".toml", ".cfg", ".conf", ".ini",
    ".md", ".txt", ".rst", ".sh", ".bash",
    ".env.example",
    ".html", ".css", ".xml",
    ".dockerfile", ".dockerignore", ".gitignore",
}

# Paths that are never served regardless of whitelist
BLOCKED_PATTERNS = (
    "/.ssh/", "/id_rsa", "/id_ed25519",
    "/.gnupg/", "/shadow", "/gshadow",
    "/.aws/credentials", "/.kube/config",
)

# Max file size for reading (1MB)
MAX_FILE_SIZE = 1_048_576


class PathGuard:
    """Validate and restrict filesystem access for the web API."""

    def __init__(self, allowed_roots: list[str]):
        self._roots = [os.path.realpath(os.path.expanduser(r))
                       for r in allowed_roots if r]

    def validate_read(self, requested_path: str) -> str:
        """Return resolved path if allowed, raise ValueError otherwise."""
        resolved = os.path.realpath(requested_path)

        # Check blocked patterns
        for pattern in BLOCKED_PATTERNS:
            if pattern in resolved:
                raise ValueError(f"Access denied: blocked pattern")

        # Check extension
        _, ext = os.path.splitext(resolved)
        basename = os.path.basename(resolved).lower()
        if ext.lower() not in ALLOWED_EXTENSIONS and basename not in (
            "dockerfile", "makefile", "gemfile", "procfile",
            ".env.example",
        ):
            raise ValueError(f"Access denied: extension not allowed")

        # Check against whitelist
        if not self._is_under_root(resolved):
            raise ValueError(f"Access denied: outside allowed paths")

        # Check file size
        try:
            size = os.path.getsize(resolved)
            if size > MAX_FILE_SIZE:
                raise ValueError(f"File too large: {size} bytes (max {MAX_FILE_SIZE})")
        except OSError:
            raise ValueError(f"Cannot access file")

        return resolved

    def validate_dir(self, requested_path: str) -> str:
        """Return resolved directory path if allowed."""
        resolved = os.path.realpath(requested_path)
        if not os.path.isdir(resolved):
            raise ValueError(f"Not a directory")
        if not self._is_under_root(resolved):
            raise ValueError(f"Access denied: outside allowed paths")
        return resolved

    def _is_under_root(self, resolved: str) -> bool:
        """Check if resolved path is under any allowed root."""
        return any(
            resolved == root or resolved.startswith(root + os.sep)
            for root in self._roots
        )

    def list_dir(self, path: str) -> list[dict]:
        """List directory contents with metadata."""
        resolved = self.validate_dir(path)
        entries = []
        try:
            for name in sorted(os.listdir(resolved)):
                full = os.path.join(resolved, name)
                try:
                    is_link = os.path.islink(full)
                    is_dir = os.path.isdir(full)
                    stat = os.stat(full)
                    entry = {
                        "name": name,
                        "path": full,
                        "type": "directory" if is_dir else "file",
                        "size": stat.st_size if not is_dir else 0,
                        "mtime": int(stat.st_mtime),
                        "is_symlink": is_link,
                    }
                    if is_link:
                        try:
                            target = os.readlink(full)
                            # Only expose target if it resolves within allowed roots
                            resolved_target = os.path.realpath(full)
                            if self._is_under_root(resolved_target):
                                entry["symlink_target"] = target
                            else:
                                entry["symlink_target"] = "(outside allowed paths)"
                        except OSError:
                            pass
                    entries.append(entry)
                except (OSError, PermissionError):
                    continue
        except (OSError, PermissionError):
            raise ValueError(f"Cannot read directory")
        return entries

    def read_file(self, path: str) -> str:
        """Read file content after validation."""
        resolved = self.validate_read(path)
        with open(resolved, "r", errors="replace") as f:
            return f.read()
