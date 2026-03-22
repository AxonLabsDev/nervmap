"""JavaScript/TypeScript source file parser — regex only."""

from __future__ import annotations

import re
import logging

logger = logging.getLogger("nervmap.source.js")

# ES module imports: import X from 'Y'; import { X } from 'Y'
_ES_IMPORT_RE = re.compile(r"""import\s+.*?\s+from\s+['"]([^'"./][^'"]*?)['"]""")
# require(): const X = require('Y')
_REQUIRE_RE = re.compile(r"""require\(\s*['"]([^'"./][^'"]*?)['"]""")
# Dynamic import: import('Y')
_DYNAMIC_IMPORT_RE = re.compile(r"""import\(\s*['"]([^'"./][^'"]*?)['"]""")

# process.env.X or process.env["X"]
_ENV_DOT_RE = re.compile(r'process\.env\.([A-Z_][A-Z0-9_]*)')
_ENV_BRACKET_RE = re.compile(r'process\.env\[(?:"|\')([A-Z_][A-Z0-9_]*)(?:"|\')\]')

# Port bindings
_PORT_ASSIGN_RE = re.compile(r'\bPORT\s*=\s*(\d{2,5})\b')
_LISTEN_RE = re.compile(r'\.listen\(\s*(\d{2,5})\s*[,)]')
_PORT_PROP_RE = re.compile(r'\.port\s*=\s*(\d{2,5})\b')


class JsParser:
    """Parse JavaScript/TypeScript source files using regex."""

    MAX_IMPORT_LINES = 100

    def parse(self, filepath: str) -> dict:
        """Parse a JS/TS file and return imports, env_refs, port_bindings."""
        try:
            with open(filepath, "r", errors="replace") as f:
                all_lines = f.readlines()
        except Exception:
            logger.debug("Cannot read %s", filepath, exc_info=True)
            return {"imports": [], "env_refs": [], "port_bindings": []}

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
        """Extract package names from import/require statements."""
        pkgs: list[str] = []
        for pattern in (_ES_IMPORT_RE, _REQUIRE_RE, _DYNAMIC_IMPORT_RE):
            for m in pattern.finditer(text):
                pkg = m.group(1)
                # Handle scoped packages: @scope/pkg -> @scope/pkg
                if pkg.startswith("@"):
                    parts = pkg.split("/")
                    if len(parts) >= 2:
                        pkgs.append("/".join(parts[:2]))
                else:
                    pkgs.append(pkg.split("/")[0])
        return pkgs

    @staticmethod
    def _extract_env_refs(text: str) -> list[str]:
        """Extract env var names from process.env references."""
        refs: list[str] = []
        for pattern in (_ENV_DOT_RE, _ENV_BRACKET_RE):
            for m in pattern.finditer(text):
                refs.append(m.group(1))
        return refs

    @staticmethod
    def _extract_port_bindings(text: str) -> list[int]:
        """Extract port numbers from listen() and assignments."""
        ports: list[int] = []
        for pattern in (_PORT_ASSIGN_RE, _LISTEN_RE, _PORT_PROP_RE):
            for m in pattern.finditer(text):
                try:
                    port = int(m.group(1))
                    if 1 <= port <= 65535:
                        ports.append(port)
                except ValueError:
                    pass
        return ports
