"""Tests for the web dashboard module."""

import os
import pytest
from nervmap.web.security import PathGuard, ALLOWED_EXTENSIONS


class TestPathGuard:
    """Tests for filesystem access security."""

    def test_read_allowed_file(self, tmp_path):
        """Files under allowed roots can be read."""
        f = tmp_path / "config.json"
        f.write_text('{"key": "value"}')
        guard = PathGuard([str(tmp_path)])
        result = guard.validate_read(str(f))
        assert result == os.path.realpath(str(f))

    def test_read_blocked_outside_root(self, tmp_path):
        """Files outside allowed roots are blocked."""
        guard = PathGuard([str(tmp_path)])
        with pytest.raises(ValueError):
            guard.validate_read("/etc/hostname")

    def test_read_blocked_traversal(self, tmp_path):
        """Path traversal attempts are blocked."""
        guard = PathGuard([str(tmp_path)])
        with pytest.raises(ValueError):
            guard.validate_read(str(tmp_path / ".." / ".." / "etc" / "shadow"))

    def test_read_blocked_ssh_key(self, tmp_path):
        """SSH keys are always blocked."""
        ssh_dir = tmp_path / ".ssh"
        ssh_dir.mkdir()
        key = ssh_dir / "id_rsa"
        key.write_text("fake key")
        guard = PathGuard([str(tmp_path)])
        with pytest.raises(ValueError, match="blocked pattern"):
            guard.validate_read(str(key))

    def test_read_blocked_extension(self, tmp_path):
        """Disallowed extensions are blocked."""
        f = tmp_path / "binary.exe"
        f.write_bytes(b"\x00" * 100)
        guard = PathGuard([str(tmp_path)])
        with pytest.raises(ValueError, match="extension"):
            guard.validate_read(str(f))

    def test_read_file_too_large(self, tmp_path):
        """Files larger than MAX_FILE_SIZE are blocked."""
        f = tmp_path / "big.json"
        f.write_text("x" * 2_000_000)
        guard = PathGuard([str(tmp_path)])
        with pytest.raises(ValueError, match="too large"):
            guard.validate_read(str(f))

    def test_list_dir(self, tmp_path):
        """Directory listing returns entries with metadata."""
        (tmp_path / "file.py").write_text("print('hi')")
        (tmp_path / "subdir").mkdir()
        guard = PathGuard([str(tmp_path)])
        entries = guard.list_dir(str(tmp_path))
        names = {e["name"] for e in entries}
        assert "file.py" in names
        assert "subdir" in names
        # Check types
        file_entry = next(e for e in entries if e["name"] == "file.py")
        dir_entry = next(e for e in entries if e["name"] == "subdir")
        assert file_entry["type"] == "file"
        assert dir_entry["type"] == "directory"

    def test_list_dir_blocked_outside(self, tmp_path):
        """Dir listing outside root is blocked."""
        guard = PathGuard([str(tmp_path)])
        with pytest.raises(ValueError):
            guard.list_dir("/etc")

    def test_read_file_content(self, tmp_path):
        """Read file returns correct content."""
        f = tmp_path / "test.md"
        f.write_text("# Hello World")
        guard = PathGuard([str(tmp_path)])
        content = guard.read_file(str(f))
        assert content == "# Hello World"

    def test_symlink_detection(self, tmp_path):
        """Symlinks are detected in directory listing."""
        target = tmp_path / "real.py"
        target.write_text("print('real')")
        link = tmp_path / "link.py"
        link.symlink_to(target)
        guard = PathGuard([str(tmp_path)])
        entries = guard.list_dir(str(tmp_path))
        link_entry = next(e for e in entries if e["name"] == "link.py")
        assert link_entry["is_symlink"] is True
        assert "symlink_target" in link_entry

    def test_symlink_escape_blocked(self, tmp_path):
        """Symlink pointing outside allowed root is blocked on read."""
        link = tmp_path / "escape.py"
        link.symlink_to("/etc/hostname")
        guard = PathGuard([str(tmp_path)])
        with pytest.raises(ValueError):
            guard.validate_read(str(link))

    def test_env_file_blocked(self, tmp_path):
        """.env files are not in allowed extensions (security)."""
        f = tmp_path / ".env"
        f.write_text("SECRET=password123")
        guard = PathGuard([str(tmp_path)])
        with pytest.raises(ValueError, match="extension"):
            guard.validate_read(str(f))

    def test_env_example_allowed(self, tmp_path):
        """.env.example files ARE allowed."""
        f = tmp_path / ".env.example"
        f.write_text("SECRET=")
        guard = PathGuard([str(tmp_path)])
        result = guard.validate_read(str(f))
        assert result is not None

    def test_multiple_roots(self, tmp_path):
        """Multiple allowed roots all work."""
        dir_a = tmp_path / "a"
        dir_b = tmp_path / "b"
        dir_a.mkdir()
        dir_b.mkdir()
        (dir_a / "config.yml").write_text("key: val")
        (dir_b / "app.py").write_text("print('hi')")
        guard = PathGuard([str(dir_a), str(dir_b)])
        assert guard.validate_read(str(dir_a / "config.yml"))
        assert guard.validate_read(str(dir_b / "app.py"))


class TestWebServer:
    """Tests for the FastAPI app."""

    def test_app_creates(self):
        """App can be created."""
        from nervmap.web.server import create_app
        app = create_app({})
        assert app is not None

    def test_health_endpoint(self):
        """Health endpoint returns OK."""
        from fastapi.testclient import TestClient
        from nervmap.web.server import create_app
        app = create_app({})
        client = TestClient(app)
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_state_endpoint(self):
        """State endpoint returns scan data."""
        from fastapi.testclient import TestClient
        from nervmap.web.server import create_app
        app = create_app({})
        client = TestClient(app)
        resp = client.get("/api/state")
        assert resp.status_code == 200
        data = resp.json()
        assert "services" in data
        assert "summary" in data

    def test_tree_blocked_outside(self):
        """Tree endpoint blocks paths outside allowed roots."""
        from fastapi.testclient import TestClient
        from nervmap.web.server import create_app
        app = create_app({})
        client = TestClient(app)
        resp = client.get("/api/tree?root=/etc")
        assert resp.status_code == 403

    def test_file_blocked_outside(self):
        """File endpoint blocks paths outside allowed roots."""
        from fastapi.testclient import TestClient
        from nervmap.web.server import create_app
        app = create_app({})
        client = TestClient(app)
        resp = client.get("/api/file?path=/etc/hostname")
        assert resp.status_code == 403

    def test_serve_command_exists(self):
        """The serve subcommand is registered."""
        from nervmap.cli import main
        assert "serve" in [cmd for cmd in main.commands]
