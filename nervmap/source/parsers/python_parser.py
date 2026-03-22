"""Python source file parser — regex only, no AST."""

from __future__ import annotations

import re
import logging

logger = logging.getLogger("nervmap.source.python")

# Regex patterns for Python imports (first 100 lines only)
_IMPORT_RE = re.compile(r"^import\s+([\w.]+)", re.MULTILINE)
_FROM_IMPORT_RE = re.compile(r"^from\s+([\w.]+)\s+import", re.MULTILINE)

# Env var references
_ENV_BRACKET_RE = re.compile(r'os\.environ\[(?:"|\')(\w+)(?:"|\')\]')
_ENV_GET_RE = re.compile(r'os\.environ\.get\(\s*(?:"|\')(\w+)(?:"|\')')
_GETENV_RE = re.compile(r'os\.getenv\(\s*(?:"|\')(\w+)(?:"|\')')

# Port bindings
_PORT_ASSIGN_RE = re.compile(r'\bPORT\s*=\s*(\d{2,5})\b')
_LISTEN_RE = re.compile(r'\.listen\(\s*(\d{2,5})\s*\)')
_BIND_RE = re.compile(r'\.bind\(\s*\(\s*(?:"[^"]*"|\'[^\']*\')\s*,\s*(\d{2,5})\s*\)\s*\)')


class PythonParser:
    """Parse Python source files using regex."""

    MAX_IMPORT_LINES = 100

    def parse(self, filepath: str) -> dict:
        """Parse a Python file and return imports, env_refs, port_bindings."""
        try:
            with open(filepath, "r", errors="replace") as f:
                all_lines = f.readlines()
        except Exception:
            logger.debug("Cannot read %s", filepath, exc_info=True)
            return {"imports": [], "env_refs": [], "port_bindings": []}

        # Only first 100 lines for imports
        import_text = "".join(all_lines[:self.MAX_IMPORT_LINES])
        full_text = "".join(all_lines)

        imports = self._extract_imports(import_text)
        env_refs = self._extract_env_refs(full_text)
        port_bindings = self._extract_port_bindings(full_text)

        return {
            "imports": sorted(set(imports)),
            "env_refs": sorted(set(env_refs)),
            "port_bindings": sorted(set(port_bindings)),
        }

    @staticmethod
    def _extract_imports(text: str) -> list[str]:
        """Extract top-level module names from import statements."""
        modules: list[str] = []
        for m in _IMPORT_RE.finditer(text):
            mod = m.group(1).split(".")[0]
            modules.append(mod)
        for m in _FROM_IMPORT_RE.finditer(text):
            mod = m.group(1).split(".")[0]
            modules.append(mod)
        return modules

    @staticmethod
    def _extract_env_refs(text: str) -> list[str]:
        """Extract environment variable names referenced in code."""
        refs: list[str] = []
        for pattern in (_ENV_BRACKET_RE, _ENV_GET_RE, _GETENV_RE):
            for m in pattern.finditer(text):
                refs.append(m.group(1))
        return refs

    @staticmethod
    def _extract_port_bindings(text: str) -> list[int]:
        """Extract port numbers from common patterns."""
        ports: list[int] = []
        for pattern in (_PORT_ASSIGN_RE, _LISTEN_RE, _BIND_RE):
            for m in pattern.finditer(text):
                try:
                    port = int(m.group(1))
                    if 1 <= port <= 65535:
                        ports.append(port)
                except ValueError:
                    pass
        return ports
