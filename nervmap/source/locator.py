"""ProjectLocator — discover source code project directories."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from nervmap.models import SystemState
from nervmap.source.models import CodeProject
from nervmap.source.parsers.python_parser import PythonParser
from nervmap.source.parsers.js_parser import JsParser
from nervmap.source.parsers.config_parser import parse_env_file, parse_dockerfile

logger = logging.getLogger("nervmap.source.locator")

# File count limit for scanning
_MAX_SOURCE_FILES = 500

# Extensions by language
_PYTHON_EXTS = {".py"}
_JS_EXTS = {".js", ".mjs", ".cjs", ".jsx"}
_TS_EXTS = {".ts", ".tsx", ".mts"}
_GO_EXTS = {".go"}

# Framework detection
_PYTHON_FRAMEWORKS = {
    "fastapi": "fastapi",
    "flask": "flask",
    "django": "django",
    "starlette": "starlette",
    "tornado": "tornado",
    "sanic": "sanic",
}

_JS_FRAMEWORKS = {
    "express": "express",
    "next": "nextjs",
    "nuxt": "nuxtjs",
    "koa": "koa",
    "hapi": "hapi",
    "fastify": "fastify",
    "nest": "nestjs",
}


class ProjectLocator:
    """Discover project directories from infra state and config."""

    def __init__(self, state: SystemState, cfg: dict):
        self.state = state
        self.cfg = cfg

    def locate(self) -> list[CodeProject]:
        """Locate all project directories and return CodeProject list."""
        seen_paths: set[str] = set()
        projects: list[CodeProject] = []

        # 1. From Docker compose labels
        for svc in self.state.services:
            if svc.type != "docker":
                continue
            labels = svc.metadata.get("labels", {})
            workdir = labels.get("com.docker.compose.project.working_dir", "")
            if workdir and os.path.isdir(workdir) and workdir not in seen_paths:
                seen_paths.add(workdir)
                proj = self._analyze_directory(workdir)
                if proj:
                    projects.append(proj)

        # 2. From systemd ExecStart paths
        for svc in self.state.services:
            if svc.type != "systemd":
                continue
            exec_start = svc.metadata.get("exec_start", "")
            if exec_start:
                # Extract directory from exec path
                parts = exec_start.split()
                if parts:
                    exec_path = parts[-1] if len(parts) == 1 else parts[0]
                    # Try the directory containing the executable
                    d = os.path.dirname(os.path.abspath(exec_path))
                    if os.path.isdir(d) and d not in seen_paths:
                        seen_paths.add(d)
                        proj = self._analyze_directory(d)
                        if proj:
                            projects.append(proj)

        # 3. From config source.paths
        source_paths = self.cfg.get("source", {}).get("paths", [])
        for p in source_paths:
            p = os.path.abspath(os.path.expanduser(p))
            if os.path.isdir(p) and p not in seen_paths:
                seen_paths.add(p)
                proj = self._analyze_directory(p)
                if proj:
                    projects.append(proj)

        return projects

    def _analyze_directory(self, dirpath: str) -> CodeProject | None:
        """Analyze a directory and build a CodeProject."""
        language = self._detect_language(dirpath)
        if language == "unknown":
            # Only return projects we recognize
            if not self._has_any_source_files(dirpath):
                return None

        name = os.path.basename(dirpath)
        framework = self._detect_framework(dirpath, language)
        entry_point = self._detect_entry_point(dirpath, language)
        deps_file = self._detect_deps_file(dirpath, language)
        dependencies = self._read_dependencies(dirpath, language, deps_file)
        file_count = self._count_source_files(dirpath, language)

        # Aggregate env refs and port bindings from source files
        env_refs: list[str] = []
        port_bindings: list[int] = []

        parser = self._get_parser(language)
        if parser:
            for fpath in self._iter_source_files(dirpath, language):
                result = parser.parse(fpath)
                env_refs.extend(result.get("env_refs", []))
                port_bindings.extend(result.get("port_bindings", []))

        # Parse .env if present
        env_file_path = os.path.join(dirpath, ".env")
        metadata: dict = {}
        if os.path.isfile(env_file_path):
            metadata["env_file"] = env_file_path

        # Parse Dockerfile if present
        dockerfile_path = os.path.join(dirpath, "Dockerfile")
        if os.path.isfile(dockerfile_path):
            df = parse_dockerfile(dockerfile_path)
            metadata["has_dockerfile"] = True
            metadata["dockerfile_has_healthcheck"] = df.get("has_healthcheck", False)
            if df.get("cmd"):
                metadata["dockerfile_cmd"] = df["cmd"]
            if df.get("entrypoint"):
                metadata["dockerfile_entrypoint"] = df["entrypoint"]
            # Add EXPOSE ports
            for p in df.get("expose", []):
                if p not in port_bindings:
                    port_bindings.append(p)
        else:
            metadata["has_dockerfile"] = False

        return CodeProject(
            path=dirpath,
            name=name,
            language=language,
            framework=framework,
            entry_point=entry_point,
            deps_file=deps_file,
            file_count=file_count,
            dependencies=sorted(set(dependencies)),
            env_refs=sorted(set(env_refs)),
            port_bindings=sorted(set(port_bindings)),
            linked_services=[],  # Filled later by CodeLinker
            metadata=metadata,
        )

    @staticmethod
    def _detect_language(dirpath: str) -> str:
        """Detect project language from marker files."""
        if os.path.isfile(os.path.join(dirpath, "go.mod")):
            return "go"
        if os.path.isfile(os.path.join(dirpath, "tsconfig.json")):
            return "typescript"
        if os.path.isfile(os.path.join(dirpath, "requirements.txt")) or \
           os.path.isfile(os.path.join(dirpath, "pyproject.toml")) or \
           os.path.isfile(os.path.join(dirpath, "setup.py")):
            return "python"
        if os.path.isfile(os.path.join(dirpath, "package.json")):
            return "javascript"
        return "unknown"

    @staticmethod
    def _detect_framework(dirpath: str, language: str) -> str | None:
        """Detect framework from dependency files."""
        if language == "python":
            for f in ("requirements.txt", "pyproject.toml"):
                fpath = os.path.join(dirpath, f)
                if os.path.isfile(fpath):
                    try:
                        text = Path(fpath).read_text(errors="replace").lower()
                        for key, name in _PYTHON_FRAMEWORKS.items():
                            if key in text:
                                return name
                    except Exception:
                        pass
        elif language in ("javascript", "typescript"):
            pkg_path = os.path.join(dirpath, "package.json")
            if os.path.isfile(pkg_path):
                try:
                    pkg = json.loads(Path(pkg_path).read_text(errors="replace"))
                    all_deps = {}
                    all_deps.update(pkg.get("dependencies", {}))
                    all_deps.update(pkg.get("devDependencies", {}))
                    for key, name in _JS_FRAMEWORKS.items():
                        if key in all_deps:
                            return name
                except Exception:
                    pass
        elif language == "go":
            mod_path = os.path.join(dirpath, "go.mod")
            if os.path.isfile(mod_path):
                try:
                    text = Path(mod_path).read_text(errors="replace").lower()
                    if "gin-gonic" in text:
                        return "gin"
                    if "gorilla/mux" in text:
                        return "gorilla"
                    if "fiber" in text:
                        return "fiber"
                except Exception:
                    pass
        return None

    @staticmethod
    def _detect_entry_point(dirpath: str, language: str) -> str | None:
        """Find the most likely entry point file."""
        candidates = {
            "python": ["main.py", "app.py", "server.py", "run.py", "manage.py"],
            "javascript": ["index.js", "server.js", "app.js", "main.js"],
            "typescript": ["index.ts", "server.ts", "app.ts", "main.ts"],
            "go": ["main.go", "cmd/main.go"],
        }
        for candidate in candidates.get(language, []):
            if os.path.isfile(os.path.join(dirpath, candidate)):
                return candidate
        return None

    @staticmethod
    def _detect_deps_file(dirpath: str, language: str) -> str | None:
        """Find the dependency manifest file."""
        manifests = {
            "python": ["requirements.txt", "pyproject.toml", "Pipfile"],
            "javascript": ["package.json"],
            "typescript": ["package.json"],
            "go": ["go.mod"],
        }
        for m in manifests.get(language, []):
            fpath = os.path.join(dirpath, m)
            if os.path.isfile(fpath):
                return fpath
        return None

    @staticmethod
    def _read_dependencies(dirpath: str, language: str, deps_file: str | None) -> list[str]:
        """Read dependency names from manifest file."""
        if not deps_file or not os.path.isfile(deps_file):
            return []

        deps: list[str] = []
        try:
            if language == "python" and deps_file.endswith("requirements.txt"):
                with open(deps_file) as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#") or line.startswith("-"):
                            continue
                        # Strip version spec
                        name = line.split("==")[0].split(">=")[0].split("<=")[0].split("~=")[0].split("[")[0].strip()
                        if name:
                            deps.append(name)

            elif language in ("javascript", "typescript") and deps_file.endswith("package.json"):
                with open(deps_file) as f:
                    pkg = json.loads(f.read())
                deps.extend(pkg.get("dependencies", {}).keys())
                deps.extend(pkg.get("devDependencies", {}).keys())

            elif language == "go" and deps_file.endswith("go.mod"):
                with open(deps_file) as f:
                    in_require = False
                    for line in f:
                        line = line.strip()
                        if line.startswith("require ("):
                            in_require = True
                            continue
                        if in_require and line == ")":
                            in_require = False
                            continue
                        if in_require:
                            parts = line.split()
                            if parts:
                                deps.append(parts[0])
        except Exception:
            logger.debug("Cannot read deps from %s", deps_file, exc_info=True)

        return deps

    def _count_source_files(self, dirpath: str, language: str) -> int:
        """Count source files of the detected language."""
        count = 0
        exts = self._get_extensions(language)
        for fpath in self._iter_source_files(dirpath, language):
            count += 1
            if count >= _MAX_SOURCE_FILES:
                break
        return count

    @staticmethod
    def _get_extensions(language: str) -> set[str]:
        """Get file extensions for a language."""
        mapping = {
            "python": _PYTHON_EXTS,
            "javascript": _JS_EXTS,
            "typescript": _TS_EXTS | _JS_EXTS,
            "go": _GO_EXTS,
        }
        return mapping.get(language, _PYTHON_EXTS | _JS_EXTS | _TS_EXTS | _GO_EXTS)

    def _iter_source_files(self, dirpath: str, language: str):
        """Iterate over source files, skipping node_modules, .git, etc."""
        exts = self._get_extensions(language)
        skip_dirs = {"node_modules", ".git", "__pycache__", ".venv", "venv", "vendor", "dist", "build"}
        count = 0
        for root, dirs, files in os.walk(dirpath):
            dirs[:] = [d for d in dirs if d not in skip_dirs]
            for fname in files:
                if any(fname.endswith(ext) for ext in exts):
                    yield os.path.join(root, fname)
                    count += 1
                    if count >= _MAX_SOURCE_FILES:
                        return

    @staticmethod
    def _has_any_source_files(dirpath: str) -> bool:
        """Check if directory has any recognizable source files."""
        all_exts = _PYTHON_EXTS | _JS_EXTS | _TS_EXTS | _GO_EXTS
        skip_dirs = {"node_modules", ".git", "__pycache__", ".venv", "venv"}
        for root, dirs, files in os.walk(dirpath):
            dirs[:] = [d for d in dirs if d not in skip_dirs]
            for fname in files:
                if any(fname.endswith(ext) for ext in all_exts):
                    return True
        return False

    @staticmethod
    def _get_parser(language: str):
        """Get the appropriate parser for a language."""
        if language == "python":
            return PythonParser()
        if language in ("javascript", "typescript"):
            return JsParser()
        return None
