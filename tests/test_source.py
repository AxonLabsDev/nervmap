"""Tests for source code analysis module (v0.2)."""

import json
import os
import sqlite3
import pytest
from unittest.mock import patch, MagicMock

from nervmap.models import Service, SystemState
from nervmap.config import DEFAULTS
from nervmap.source.models import CodeProject
from nervmap.source.locator import ProjectLocator
from nervmap.source.linker import CodeLinker
from nervmap.source.cache import SourceCache
from nervmap.source.parsers.python_parser import PythonParser
from nervmap.source.parsers.js_parser import JsParser
from nervmap.source.parsers.config_parser import (
    parse_env_file,
    parse_dockerfile,
    parse_nginx_conf,
    parse_compose_build_context,
)
from nervmap.diagnostics.rules.code_rules import (
    check_code_port_drift,
    check_code_env_missing,
    check_code_dep_missing,
    check_code_entrypoint_mismatch,
    check_code_env_example_drift,
    check_code_dockerfile_no_healthcheck,
)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class TestCodeProject:
    """Tests for CodeProject dataclass."""

    def test_create_code_project(self):
        """CodeProject can be instantiated with all fields."""
        proj = CodeProject(
            path="/opt/myapp",
            name="myapp",
            language="python",
            framework="fastapi",
            entry_point="main.py",
            deps_file="requirements.txt",
            file_count=42,
            dependencies=["fastapi", "uvicorn"],
            env_refs=["DATABASE_URL", "SECRET_KEY"],
            port_bindings=[8000],
            linked_services=["docker:myapp"],
            metadata={},
        )
        assert proj.language == "python"
        assert proj.framework == "fastapi"
        assert len(proj.dependencies) == 2
        assert len(proj.env_refs) == 2
        assert proj.port_bindings == [8000]

    def test_code_project_to_dict(self):
        """CodeProject.to_dict() returns a serializable dict."""
        proj = CodeProject(
            path="/opt/myapp",
            name="myapp",
            language="python",
            framework=None,
            entry_point=None,
            deps_file=None,
            file_count=10,
            dependencies=[],
            env_refs=[],
            port_bindings=[],
            linked_services=[],
            metadata={"foo": "bar"},
        )
        d = proj.to_dict()
        assert d["path"] == "/opt/myapp"
        assert d["name"] == "myapp"
        assert d["language"] == "python"
        assert d["metadata"] == {"foo": "bar"}
        # Must be JSON serializable
        json.dumps(d)

    def test_code_project_defaults(self):
        """CodeProject with minimal args uses defaults correctly."""
        proj = CodeProject(
            path="/x", name="x", language="unknown",
            framework=None, entry_point=None, deps_file=None,
            file_count=0, dependencies=[], env_refs=[],
            port_bindings=[], linked_services=[], metadata={},
        )
        assert proj.language == "unknown"


# ---------------------------------------------------------------------------
# Python Parser
# ---------------------------------------------------------------------------

class TestPythonParser:
    """Tests for Python source file parser."""

    def test_extract_imports(self, tmp_path):
        """Extract standard Python imports."""
        src = tmp_path / "app.py"
        src.write_text(
            "import os\n"
            "import sys\n"
            "from pathlib import Path\n"
            "from fastapi import FastAPI\n"
            "import uvicorn\n"
        )
        parser = PythonParser()
        result = parser.parse(str(src))
        assert "os" in result["imports"]
        assert "sys" in result["imports"]
        assert "pathlib" in result["imports"]
        assert "fastapi" in result["imports"]
        assert "uvicorn" in result["imports"]

    def test_extract_env_refs(self, tmp_path):
        """Extract os.environ, os.getenv references."""
        src = tmp_path / "config.py"
        src.write_text(
            'import os\n'
            'db = os.environ["DATABASE_URL"]\n'
            'secret = os.environ.get("SECRET_KEY", "default")\n'
            'port = os.getenv("PORT", "8000")\n'
        )
        parser = PythonParser()
        result = parser.parse(str(src))
        assert "DATABASE_URL" in result["env_refs"]
        assert "SECRET_KEY" in result["env_refs"]
        assert "PORT" in result["env_refs"]

    def test_extract_port_bindings(self, tmp_path):
        """Extract port numbers from common patterns."""
        src = tmp_path / "server.py"
        src.write_text(
            'PORT = 8000\n'
            'app.listen(3000)\n'
            'sock.bind(("", 9090))\n'
        )
        parser = PythonParser()
        result = parser.parse(str(src))
        assert 8000 in result["port_bindings"]
        assert 3000 in result["port_bindings"]
        assert 9090 in result["port_bindings"]

    def test_only_reads_first_100_lines(self, tmp_path):
        """Parser only reads first 100 lines for imports."""
        lines = [f"import mod_{i}\n" for i in range(200)]
        src = tmp_path / "big.py"
        src.write_text("".join(lines))
        parser = PythonParser()
        result = parser.parse(str(src))
        # Should only have imports from first 100 lines
        assert "mod_0" in result["imports"]
        assert "mod_99" in result["imports"]
        assert "mod_100" not in result["imports"]

    def test_empty_file(self, tmp_path):
        """Empty file returns empty results."""
        src = tmp_path / "empty.py"
        src.write_text("")
        parser = PythonParser()
        result = parser.parse(str(src))
        assert result["imports"] == []
        assert result["env_refs"] == []
        assert result["port_bindings"] == []


# ---------------------------------------------------------------------------
# JS/TS Parser
# ---------------------------------------------------------------------------

class TestJsParser:
    """Tests for JS/TS source file parser."""

    def test_extract_es_imports(self, tmp_path):
        """Extract ES module import statements."""
        src = tmp_path / "app.js"
        src.write_text(
            "import express from 'express';\n"
            "import { Router } from 'express';\n"
            "import cors from 'cors';\n"
        )
        parser = JsParser()
        result = parser.parse(str(src))
        assert "express" in result["imports"]
        assert "cors" in result["imports"]

    def test_extract_require(self, tmp_path):
        """Extract require() calls."""
        src = tmp_path / "server.js"
        src.write_text(
            "const express = require('express');\n"
            "const { Pool } = require('pg');\n"
            'const redis = require("redis");\n'
        )
        parser = JsParser()
        result = parser.parse(str(src))
        assert "express" in result["imports"]
        assert "pg" in result["imports"]
        assert "redis" in result["imports"]

    def test_extract_dynamic_import(self, tmp_path):
        """Extract dynamic import() calls."""
        src = tmp_path / "loader.js"
        src.write_text(
            "const mod = await import('dotenv');\n"
        )
        parser = JsParser()
        result = parser.parse(str(src))
        assert "dotenv" in result["imports"]

    def test_extract_env_refs(self, tmp_path):
        """Extract process.env references."""
        src = tmp_path / "config.js"
        src.write_text(
            'const port = process.env.PORT;\n'
            'const db = process.env["DATABASE_URL"];\n'
            'const key = process.env.SECRET_KEY || "default";\n'
        )
        parser = JsParser()
        result = parser.parse(str(src))
        assert "PORT" in result["env_refs"]
        assert "DATABASE_URL" in result["env_refs"]
        assert "SECRET_KEY" in result["env_refs"]

    def test_extract_port_bindings(self, tmp_path):
        """Extract port numbers from listen() calls and assignments."""
        src = tmp_path / "app.js"
        src.write_text(
            'app.listen(3000);\n'
            'const PORT = 8080;\n'
        )
        parser = JsParser()
        result = parser.parse(str(src))
        assert 3000 in result["port_bindings"]
        assert 8080 in result["port_bindings"]

    def test_only_reads_first_100_lines(self, tmp_path):
        """Parser only reads first 100 lines for imports."""
        lines = [f"import mod{i} from 'mod{i}';\n" for i in range(200)]
        src = tmp_path / "big.js"
        src.write_text("".join(lines))
        parser = JsParser()
        result = parser.parse(str(src))
        assert "mod0" in result["imports"]
        assert "mod99" in result["imports"]
        assert "mod100" not in result["imports"]


# ---------------------------------------------------------------------------
# Config Parsers
# ---------------------------------------------------------------------------

class TestConfigParsers:
    """Tests for .env, Dockerfile, nginx, compose config parsers."""

    def test_parse_env_file(self, tmp_path):
        """Parse .env file key=value pairs."""
        env_file = tmp_path / ".env"
        env_file.write_text(
            "DATABASE_URL=postgres://localhost:5432/db\n"
            "SECRET_KEY=mysecret\n"
            "# this is a comment\n"
            "\n"
            "PORT=8000\n"
        )
        result = parse_env_file(str(env_file))
        assert result["DATABASE_URL"] == "postgres://localhost:5432/db"
        assert result["SECRET_KEY"] == "mysecret"
        assert result["PORT"] == "8000"
        assert len(result) == 3

    def test_parse_env_file_nonexistent(self):
        """Non-existent .env returns empty dict."""
        result = parse_env_file("/nonexistent/.env")
        assert result == {}

    def test_parse_dockerfile(self, tmp_path):
        """Parse Dockerfile directives."""
        dockerfile = tmp_path / "Dockerfile"
        dockerfile.write_text(
            "FROM python:3.11-slim\n"
            "WORKDIR /app\n"
            "COPY requirements.txt .\n"
            "RUN pip install -r requirements.txt\n"
            "COPY . .\n"
            "EXPOSE 8000\n"
            "HEALTHCHECK CMD curl -f http://localhost:8000/health\n"
            'CMD ["python", "main.py"]\n'
        )
        result = parse_dockerfile(str(dockerfile))
        assert result["from_image"] == "python:3.11-slim"
        assert result["workdir"] == "/app"
        assert "requirements.txt" in result["copy_sources"]
        assert "." in result["copy_sources"]
        assert 8000 in result["expose"]
        assert result["cmd"] == '["python", "main.py"]'
        assert result["has_healthcheck"] is True

    def test_parse_dockerfile_no_healthcheck(self, tmp_path):
        """Dockerfile without HEALTHCHECK is detected."""
        dockerfile = tmp_path / "Dockerfile"
        dockerfile.write_text(
            "FROM node:18\n"
            "COPY . /app\n"
            'CMD ["node", "server.js"]\n'
        )
        result = parse_dockerfile(str(dockerfile))
        assert result["has_healthcheck"] is False

    def test_parse_dockerfile_entrypoint(self, tmp_path):
        """Parse ENTRYPOINT directive."""
        dockerfile = tmp_path / "Dockerfile"
        dockerfile.write_text(
            "FROM golang:1.21\n"
            'ENTRYPOINT ["./server"]\n'
        )
        result = parse_dockerfile(str(dockerfile))
        assert result["entrypoint"] == '["./server"]'

    def test_parse_nginx_conf(self, tmp_path):
        """Parse nginx.conf directives."""
        conf = tmp_path / "nginx.conf"
        conf.write_text(
            "upstream backend {\n"
            "    server 127.0.0.1:8000;\n"
            "    server 127.0.0.1:8001;\n"
            "}\n"
            "server {\n"
            "    listen 80;\n"
            "    listen 443 ssl;\n"
            "    location / {\n"
            "        proxy_pass http://backend;\n"
            "    }\n"
            "    location /api {\n"
            "        proxy_pass http://127.0.0.1:9000;\n"
            "    }\n"
            "}\n"
        )
        result = parse_nginx_conf(str(conf))
        assert "backend" in result["upstreams"]
        assert 80 in result["listen_ports"]
        assert 443 in result["listen_ports"]
        assert "http://backend" in result["proxy_pass"]
        assert "http://127.0.0.1:9000" in result["proxy_pass"]

    def test_parse_compose_build_context(self, tmp_path):
        """Extract build.context from docker-compose.yml."""
        compose = tmp_path / "docker-compose.yml"
        compose.write_text(
            "services:\n"
            "  web:\n"
            "    build:\n"
            "      context: ./frontend\n"
            "      dockerfile: Dockerfile\n"
            "  api:\n"
            "    build: ./backend\n"
            "  db:\n"
            "    image: postgres:15\n"
        )
        result = parse_compose_build_context(str(compose))
        assert result["web"] == "./frontend"
        assert result["api"] == "./backend"
        assert "db" not in result


# ---------------------------------------------------------------------------
# ProjectLocator
# ---------------------------------------------------------------------------

class TestProjectLocator:
    """Tests for project directory discovery."""

    def test_locate_from_compose_labels(self, tmp_path):
        """Find project dirs from Docker compose working_dir labels."""
        project_dir = tmp_path / "myapp"
        project_dir.mkdir()
        (project_dir / "requirements.txt").write_text("fastapi\n")
        (project_dir / "main.py").write_text("import fastapi\n")

        svc = Service(
            id="docker:myapp-web", name="myapp-web", type="docker",
            status="running",
            metadata={"labels": {
                "com.docker.compose.project.working_dir": str(project_dir),
            }},
        )
        state = SystemState(services=[svc])

        locator = ProjectLocator(state, {})
        projects = locator.locate()
        paths = [p.path for p in projects]
        assert str(project_dir) in paths

    def test_locate_from_config_paths(self, tmp_path):
        """Find project dirs from .nervmap.yml source.paths."""
        project_dir = tmp_path / "myproject"
        project_dir.mkdir()
        (project_dir / "package.json").write_text('{"name": "myproject"}')

        cfg = {"source": {"paths": [str(project_dir)]}}
        state = SystemState()

        locator = ProjectLocator(state, cfg)
        projects = locator.locate()
        paths = [p.path for p in projects]
        assert str(project_dir) in paths

    def test_detect_python_language(self, tmp_path):
        """Detect Python by requirements.txt."""
        d = tmp_path / "pyproj"
        d.mkdir()
        (d / "requirements.txt").write_text("flask\n")
        (d / "app.py").write_text("from flask import Flask\n")

        cfg = {"source": {"paths": [str(d)]}}
        state = SystemState()
        locator = ProjectLocator(state, cfg)
        projects = locator.locate()
        assert projects[0].language == "python"

    def test_detect_javascript_language(self, tmp_path):
        """Detect JavaScript by package.json."""
        d = tmp_path / "jsproj"
        d.mkdir()
        (d / "package.json").write_text('{"name": "app", "dependencies": {"express": "^4"}}')
        (d / "index.js").write_text("const express = require('express');\n")

        cfg = {"source": {"paths": [str(d)]}}
        state = SystemState()
        locator = ProjectLocator(state, cfg)
        projects = locator.locate()
        assert projects[0].language in ("javascript", "typescript")

    def test_detect_typescript_language(self, tmp_path):
        """Detect TypeScript by tsconfig.json."""
        d = tmp_path / "tsproj"
        d.mkdir()
        (d / "tsconfig.json").write_text("{}")
        (d / "package.json").write_text('{"name": "app"}')

        cfg = {"source": {"paths": [str(d)]}}
        state = SystemState()
        locator = ProjectLocator(state, cfg)
        projects = locator.locate()
        assert projects[0].language == "typescript"

    def test_detect_go_language(self, tmp_path):
        """Detect Go by go.mod."""
        d = tmp_path / "goproj"
        d.mkdir()
        (d / "go.mod").write_text("module example.com/app\n")

        cfg = {"source": {"paths": [str(d)]}}
        state = SystemState()
        locator = ProjectLocator(state, cfg)
        projects = locator.locate()
        assert projects[0].language == "go"

    def test_deduplication(self, tmp_path):
        """Same directory from two sources is not duplicated."""
        d = tmp_path / "shared"
        d.mkdir()
        (d / "requirements.txt").write_text("flask\n")

        svc = Service(
            id="docker:web", name="web", type="docker",
            status="running",
            metadata={"labels": {
                "com.docker.compose.project.working_dir": str(d),
            }},
        )
        cfg = {"source": {"paths": [str(d)]}}
        state = SystemState(services=[svc])

        locator = ProjectLocator(state, cfg)
        projects = locator.locate()
        assert len(projects) == 1


# ---------------------------------------------------------------------------
# CodeLinker
# ---------------------------------------------------------------------------

class TestCodeLinker:
    """Tests for linking Docker containers to source code."""

    def test_link_via_compose_build_context(self, tmp_path):
        """Link via docker-compose build.context (100% confidence)."""
        project_dir = tmp_path / "myapp"
        project_dir.mkdir()
        compose = tmp_path / "docker-compose.yml"
        compose.write_text(
            "services:\n"
            "  web:\n"
            "    build:\n"
            "      context: ./myapp\n"
        )

        svc = Service(
            id="docker:myapp-web", name="myapp-web", type="docker",
            status="running",
            metadata={"labels": {
                "com.docker.compose.project.working_dir": str(tmp_path),
                "com.docker.compose.service": "web",
            }},
        )
        proj = CodeProject(
            path=str(project_dir), name="myapp", language="python",
            framework=None, entry_point=None, deps_file=None,
            file_count=5, dependencies=[], env_refs=[],
            port_bindings=[], linked_services=[], metadata={},
        )

        linker = CodeLinker()
        links = linker.link([svc], [proj])
        assert len(links) >= 1
        assert links[0]["confidence"] >= 0.6

    def test_link_via_working_dir_label(self, tmp_path):
        """Link via Docker label working_dir (100% confidence)."""
        project_dir = tmp_path / "myapp"
        project_dir.mkdir()

        svc = Service(
            id="docker:myapp-web", name="myapp-web", type="docker",
            status="running",
            metadata={"labels": {
                "com.docker.compose.project.working_dir": str(project_dir),
            }},
        )
        proj = CodeProject(
            path=str(project_dir), name="myapp", language="python",
            framework=None, entry_point=None, deps_file=None,
            file_count=5, dependencies=[], env_refs=[],
            port_bindings=[], linked_services=[], metadata={},
        )

        linker = CodeLinker()
        links = linker.link([svc], [proj])
        assert len(links) >= 1
        assert any(l["confidence"] == 1.0 for l in links)

    def test_link_via_proximity(self, tmp_path):
        """Link via Dockerfile in same directory (60% confidence)."""
        project_dir = tmp_path / "myapp"
        project_dir.mkdir()
        (project_dir / "Dockerfile").write_text("FROM python:3.11\n")
        (project_dir / "app.py").write_text("print('hello')\n")

        svc = Service(
            id="docker:myapp", name="myapp", type="docker",
            status="running", metadata={"labels": {}},
        )
        proj = CodeProject(
            path=str(project_dir), name="myapp", language="python",
            framework=None, entry_point=None, deps_file=None,
            file_count=2, dependencies=[], env_refs=[],
            port_bindings=[], linked_services=[], metadata={},
        )

        linker = CodeLinker()
        links = linker.link([svc], [proj])
        # Proximity heuristic: same name in project and container
        matched = [l for l in links if l["project"] == str(project_dir)]
        assert len(matched) >= 1


# ---------------------------------------------------------------------------
# Source Cache
# ---------------------------------------------------------------------------

class TestSourceCache:
    """Tests for SQLite incremental cache."""

    def test_cache_write_and_read(self, tmp_path):
        """Store and retrieve parsed data from cache."""
        db_path = tmp_path / "cache.db"
        cache = SourceCache(str(db_path))

        src = tmp_path / "test.py"
        src.write_text("import os\n")

        data = {"imports": ["os"], "env_refs": [], "port_bindings": []}
        cache.store(str(src), data)

        result = cache.get(str(src))
        assert result is not None
        assert result["imports"] == ["os"]

    def test_cache_invalidation_on_change(self, tmp_path):
        """Cache invalidates when file changes."""
        db_path = tmp_path / "cache.db"
        cache = SourceCache(str(db_path))

        src = tmp_path / "test.py"
        src.write_text("import os\n")
        data = {"imports": ["os"], "env_refs": [], "port_bindings": []}
        cache.store(str(src), data)

        # Modify the file
        import time
        time.sleep(0.05)  # ensure mtime changes
        src.write_text("import sys\n")

        result = cache.get(str(src))
        assert result is None  # Cache should be invalidated

    def test_cache_hit_on_unchanged_file(self, tmp_path):
        """Cache returns data when file is unchanged."""
        db_path = tmp_path / "cache.db"
        cache = SourceCache(str(db_path))

        src = tmp_path / "test.py"
        src.write_text("import os\n")
        data = {"imports": ["os"], "env_refs": [], "port_bindings": []}
        cache.store(str(src), data)

        # Re-read without changes
        result = cache.get(str(src))
        assert result is not None
        assert result["imports"] == ["os"]

    def test_cache_creates_db(self, tmp_path):
        """Cache creates the SQLite database file."""
        db_path = tmp_path / "subdir" / "cache.db"
        cache = SourceCache(str(db_path))
        assert os.path.exists(str(db_path))


# ---------------------------------------------------------------------------
# Code Rules (Diagnostics)
# ---------------------------------------------------------------------------

class TestCodeRules:
    """Tests for code-related diagnostic rules."""

    def test_code_port_drift(self):
        """Detect when code port != runtime port."""
        svc = Service(
            id="docker:myapp", name="myapp", type="docker",
            status="running", ports=[8080],
        )
        proj = CodeProject(
            path="/opt/myapp", name="myapp", language="python",
            framework=None, entry_point=None, deps_file=None,
            file_count=10, dependencies=[], env_refs=[],
            port_bindings=[3000],  # Code says 3000, runtime says 8080
            linked_services=["docker:myapp"], metadata={},
        )
        state = SystemState(services=[svc])
        state.projects = [proj]

        issues = check_code_port_drift(state, DEFAULTS)
        assert len(issues) >= 1
        assert issues[0].rule_id == "code-port-drift"

    def test_code_port_drift_no_issue(self):
        """No issue when ports match."""
        svc = Service(
            id="docker:myapp", name="myapp", type="docker",
            status="running", ports=[8000],
        )
        proj = CodeProject(
            path="/opt/myapp", name="myapp", language="python",
            framework=None, entry_point=None, deps_file=None,
            file_count=10, dependencies=[], env_refs=[],
            port_bindings=[8000],
            linked_services=["docker:myapp"], metadata={},
        )
        state = SystemState(services=[svc])
        state.projects = [proj]

        issues = check_code_port_drift(state, DEFAULTS)
        assert len(issues) == 0

    def test_code_env_missing(self, tmp_path):
        """Detect env var referenced in code but not in .env or compose."""
        env_file = tmp_path / ".env"
        env_file.write_text("PORT=8000\n")

        proj = CodeProject(
            path=str(tmp_path), name="myapp", language="python",
            framework=None, entry_point=None, deps_file=None,
            file_count=10, dependencies=[], env_refs=["DATABASE_URL", "PORT"],
            port_bindings=[], linked_services=["docker:myapp"],
            metadata={"env_file": str(env_file)},
        )
        svc = Service(
            id="docker:myapp", name="myapp", type="docker",
            status="running",
            metadata={"env": {"PORT": "8000"}},
        )
        state = SystemState(services=[svc])
        state.projects = [proj]

        issues = check_code_env_missing(state, DEFAULTS)
        assert len(issues) >= 1
        assert issues[0].rule_id == "code-env-missing"
        assert "DATABASE_URL" in issues[0].message

    def test_code_env_missing_no_issue(self, tmp_path):
        """No issue when all env vars are defined."""
        proj = CodeProject(
            path=str(tmp_path), name="myapp", language="python",
            framework=None, entry_point=None, deps_file=None,
            file_count=10, dependencies=[], env_refs=["PORT"],
            port_bindings=[], linked_services=["docker:myapp"],
            metadata={},
        )
        svc = Service(
            id="docker:myapp", name="myapp", type="docker",
            status="running",
            metadata={"env": {"PORT": "8000"}},
        )
        state = SystemState(services=[svc])
        state.projects = [proj]

        issues = check_code_env_missing(state, DEFAULTS)
        assert len(issues) == 0

    def test_code_entrypoint_mismatch(self, tmp_path):
        """Detect Dockerfile CMD/ENTRYPOINT pointing to missing file."""
        proj = CodeProject(
            path=str(tmp_path), name="myapp", language="python",
            framework=None, entry_point=None, deps_file=None,
            file_count=5, dependencies=[], env_refs=[],
            port_bindings=[], linked_services=["docker:myapp"],
            metadata={"dockerfile_cmd": '["python", "app.py"]'},
        )
        # app.py does NOT exist in tmp_path
        state = SystemState()
        state.projects = [proj]

        issues = check_code_entrypoint_mismatch(state, DEFAULTS)
        assert len(issues) >= 1
        assert issues[0].rule_id == "code-entrypoint-mismatch"

    def test_code_entrypoint_mismatch_no_issue(self, tmp_path):
        """No issue when entrypoint file exists."""
        (tmp_path / "app.py").write_text("print('ok')\n")
        proj = CodeProject(
            path=str(tmp_path), name="myapp", language="python",
            framework=None, entry_point=None, deps_file=None,
            file_count=5, dependencies=[], env_refs=[],
            port_bindings=[], linked_services=["docker:myapp"],
            metadata={"dockerfile_cmd": '["python", "app.py"]'},
        )
        state = SystemState()
        state.projects = [proj]

        issues = check_code_entrypoint_mismatch(state, DEFAULTS)
        assert len(issues) == 0

    def test_code_env_example_drift(self, tmp_path):
        """Detect .env.example missing vars that code references."""
        (tmp_path / ".env.example").write_text("PORT=\n")
        proj = CodeProject(
            path=str(tmp_path), name="myapp", language="python",
            framework=None, entry_point=None, deps_file=None,
            file_count=5, dependencies=[], env_refs=["PORT", "SECRET_KEY"],
            port_bindings=[], linked_services=[],
            metadata={},
        )
        state = SystemState()
        state.projects = [proj]

        issues = check_code_env_example_drift(state, DEFAULTS)
        assert len(issues) >= 1
        assert issues[0].rule_id == "code-env-example-drift"
        assert "SECRET_KEY" in issues[0].message

    def test_code_env_example_no_example(self, tmp_path):
        """No issue when .env.example does not exist."""
        proj = CodeProject(
            path=str(tmp_path), name="myapp", language="python",
            framework=None, entry_point=None, deps_file=None,
            file_count=5, dependencies=[], env_refs=["SECRET_KEY"],
            port_bindings=[], linked_services=[],
            metadata={},
        )
        state = SystemState()
        state.projects = [proj]

        issues = check_code_env_example_drift(state, DEFAULTS)
        assert len(issues) == 0

    def test_code_dockerfile_no_healthcheck(self, tmp_path):
        """Detect Dockerfile without HEALTHCHECK."""
        (tmp_path / "Dockerfile").write_text("FROM node:18\nCMD node app.js\n")
        proj = CodeProject(
            path=str(tmp_path), name="myapp", language="javascript",
            framework=None, entry_point=None, deps_file=None,
            file_count=5, dependencies=[], env_refs=[],
            port_bindings=[], linked_services=[],
            metadata={"has_dockerfile": True, "dockerfile_has_healthcheck": False},
        )
        state = SystemState()
        state.projects = [proj]

        issues = check_code_dockerfile_no_healthcheck(state, DEFAULTS)
        assert len(issues) >= 1
        assert issues[0].rule_id == "code-dockerfile-no-healthcheck"

    def test_code_dockerfile_with_healthcheck(self, tmp_path):
        """No issue when Dockerfile has HEALTHCHECK."""
        proj = CodeProject(
            path=str(tmp_path), name="myapp", language="javascript",
            framework=None, entry_point=None, deps_file=None,
            file_count=5, dependencies=[], env_refs=[],
            port_bindings=[], linked_services=[],
            metadata={"has_dockerfile": True, "dockerfile_has_healthcheck": True},
        )
        state = SystemState()
        state.projects = [proj]

        issues = check_code_dockerfile_no_healthcheck(state, DEFAULTS)
        assert len(issues) == 0

    def test_code_port_drift_ignores_dockerfile_expose(self):
        """Dockerfile EXPOSE ports should NOT trigger port-drift (infra, not code)."""
        svc = Service(
            id="docker:myapp", name="myapp", type="docker",
            status="running", ports=[8080],
        )
        proj = CodeProject(
            path="/opt/myapp", name="myapp", language="python",
            framework=None, entry_point=None, deps_file=None,
            file_count=10, dependencies=[], env_refs=[],
            # port_bindings has NO source-code ports (EXPOSE was moved to metadata)
            port_bindings=[],
            linked_services=["docker:myapp"],
            metadata={"dockerfile_expose_ports": [9200, 9300]},
        )
        state = SystemState(services=[svc])
        state.projects = [proj]

        issues = check_code_port_drift(state, DEFAULTS)
        # No drift because port_bindings is empty (EXPOSE ports are in metadata only)
        assert len(issues) == 0

    def test_code_entrypoint_skip_app_image(self, tmp_path):
        """Entrypoint check skipped when FROM is a specific app image (not base)."""
        proj = CodeProject(
            path=str(tmp_path), name="myapp", language="python",
            framework=None, entry_point=None, deps_file=None,
            file_count=5, dependencies=[], env_refs=[],
            port_bindings=[], linked_services=["docker:myapp"],
            metadata={
                "dockerfile_cmd": '["opensearch"]',
                "dockerfile_from_image": "opensearchproject/opensearch:2.11",
            },
        )
        state = SystemState()
        state.projects = [proj]

        issues = check_code_entrypoint_mismatch(state, DEFAULTS)
        # Should be skipped — opensearch is not a base image
        assert len(issues) == 0

    def test_code_entrypoint_checks_base_image(self, tmp_path):
        """Entrypoint check runs when FROM is a base image (python, node, etc)."""
        proj = CodeProject(
            path=str(tmp_path), name="myapp", language="python",
            framework=None, entry_point=None, deps_file=None,
            file_count=5, dependencies=[], env_refs=[],
            port_bindings=[], linked_services=["docker:myapp"],
            metadata={
                "dockerfile_cmd": '["python", "app.py"]',
                "dockerfile_from_image": "python:3.11-slim",
            },
        )
        # app.py does NOT exist
        state = SystemState()
        state.projects = [proj]

        issues = check_code_entrypoint_mismatch(state, DEFAULTS)
        assert len(issues) >= 1
        assert issues[0].rule_id == "code-entrypoint-mismatch"

    def test_code_dep_missing(self, tmp_path):
        """Detect declared dependency not importable."""
        (tmp_path / "requirements.txt").write_text("flask\nnonexistent-pkg-xyz\n")
        proj = CodeProject(
            path=str(tmp_path), name="myapp", language="python",
            framework=None, entry_point=None,
            deps_file=str(tmp_path / "requirements.txt"),
            file_count=5,
            dependencies=["flask", "nonexistent-pkg-xyz"],
            env_refs=[], port_bindings=[], linked_services=[],
            metadata={},
        )
        state = SystemState()
        state.projects = [proj]

        issues = check_code_dep_missing(state, DEFAULTS)
        # nonexistent-pkg-xyz should be flagged as potentially missing
        flagged_deps = [i.message for i in issues]
        # At least one should be flagged (nonexistent-pkg-xyz)
        assert any("nonexistent-pkg-xyz" in msg for msg in flagged_deps)


# ---------------------------------------------------------------------------
# CLI `nervmap code` command
# ---------------------------------------------------------------------------

class TestCodeCommand:
    """Tests for `nervmap code` CLI command."""

    def test_code_command_exists(self):
        """The 'code' subcommand is registered."""
        from nervmap.cli import main
        assert "code" in [cmd for cmd in main.commands]

    def test_code_command_with_path(self, tmp_path):
        """nervmap code /path runs without crash."""
        from click.testing import CliRunner
        from nervmap.cli import main

        (tmp_path / "main.py").write_text("import os\n")
        (tmp_path / "requirements.txt").write_text("flask\n")

        runner = CliRunner()
        result = runner.invoke(main, ["code", str(tmp_path)])
        assert result.exit_code == 0

    def test_code_command_json(self, tmp_path):
        """nervmap code /path --json outputs valid JSON."""
        from click.testing import CliRunner
        from nervmap.cli import main

        (tmp_path / "main.py").write_text("import os\n")
        (tmp_path / "requirements.txt").write_text("flask\n")

        runner = CliRunner()
        result = runner.invoke(main, ["code", str(tmp_path), "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "projects" in data


# ---------------------------------------------------------------------------
# SystemState extended with projects
# ---------------------------------------------------------------------------

class TestSystemStateProjects:
    """Tests for SystemState.projects field."""

    def test_system_state_has_projects(self):
        """SystemState accepts projects field."""
        state = SystemState()
        state.projects = []
        assert state.projects == []

    def test_system_state_projects_in_to_dict(self):
        """to_dict includes projects when present."""
        proj = CodeProject(
            path="/opt/app", name="app", language="python",
            framework=None, entry_point=None, deps_file=None,
            file_count=10, dependencies=[], env_refs=[],
            port_bindings=[], linked_services=[], metadata={},
        )
        state = SystemState()
        state.projects = [proj]
        d = state.to_dict()
        assert "projects" in d
        assert len(d["projects"]) == 1


# ---------------------------------------------------------------------------
# Scan integration: --no-code flag
# ---------------------------------------------------------------------------

class TestNoCodeFlag:
    """Tests for --no-code flag."""

    def test_no_code_flag_accepted(self):
        """The --no-code flag is accepted by scan command."""
        from click.testing import CliRunner
        from nervmap.cli import main

        runner = CliRunner()
        result = runner.invoke(main, ["scan", "--no-code"])
        # Should not fail with 'no such option'
        assert "no such option" not in (result.output or "").lower()
