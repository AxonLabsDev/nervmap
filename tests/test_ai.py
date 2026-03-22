"""Tests for AI agent chain mapping module."""

import os
import json
import pytest

from nervmap.models import SystemState, Service, Connection
from nervmap.config import DEFAULTS
from nervmap.ai.models import AIChain, SessionNode, AgentNode, ConfigNode, BackendNode
from nervmap.ai.signatures import match_agent, match_backend
from nervmap.ai.rules import (
    check_ai_backend_down,
    check_ai_model_missing,
    check_ai_config_missing,
    check_ai_orphan_backend,
)


# ---------------------------------------------------------------------------
# Signature matching
# ---------------------------------------------------------------------------

class TestSignatures:
    """Tests for agent/backend signature matching."""

    def test_match_claude(self):
        assert match_agent("claude")
        assert match_agent("claude ").agent_type == "claude-code"

    def test_match_claude_with_path(self):
        sig = match_agent("/usr/local/bin/claude ")
        assert sig is not None
        assert sig.agent_type == "claude-code"

    def test_match_codex(self):
        sig = match_agent("codex ")
        assert sig is not None
        assert sig.agent_type == "codex-cli"

    def test_match_gemini(self):
        sig = match_agent("gemini ")
        assert sig is not None
        assert sig.agent_type == "gemini-cli"

    def test_no_match_random(self):
        assert match_agent("nginx worker") is None
        assert match_agent("python3 server.py") is None

    def test_no_false_positive_substring(self):
        """'claude' inside a word should not match."""
        assert match_agent("claudette-app") is None

    def test_match_llama_server(self):
        sig = match_backend("llama-server --model /opt/model.gguf --port 8123")
        assert sig is not None
        assert sig.backend_type == "llama_cpp"

    def test_match_ollama(self):
        sig = match_backend("ollama serve")
        assert sig is not None
        assert sig.backend_type == "ollama"

    def test_match_embedding(self):
        sig = match_backend("python3 embedding-server.py")
        assert sig is not None
        assert sig.backend_type == "embedding"

    def test_no_match_backend(self):
        assert match_backend("nginx -g daemon off") is None


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class TestModels:
    """Tests for AI data models."""

    def test_config_node_hash(self, tmp_path):
        f = tmp_path / "test.md"
        f.write_text("hello world")
        h = ConfigNode.hash_file(str(f))
        assert h is not None
        assert len(h) == 16

    def test_config_node_hash_missing(self):
        assert ConfigNode.hash_file("/nonexistent/file.md") is None

    def test_ai_chain_to_dict(self):
        chain = AIChain(
            id="ai:claude-code:1234",
            agent=AgentNode(
                agent_type="claude-code", pid=1234,
                cwd="/home/user", cmdline="claude",
                display_name="Claude Code",
            ),
            backend=BackendNode(
                backend_type="cloud", provider="anthropic",
                endpoint="api.anthropic.com", auth_method="oauth",
            ),
        )
        d = chain.to_dict()
        assert d["id"] == "ai:claude-code:1234"
        assert d["agent"]["pid"] == 1234
        assert d["backend"]["provider"] == "anthropic"

    def test_config_node_children(self):
        parent = ConfigNode(
            path="/home/user/CLAUDE.md", config_type="instruction",
            role="project instructions",
        )
        child = ConfigNode(
            path="/home/user/AGENTS.md", config_type="instruction",
            role="shared rules", detection="referenced",
        )
        parent.children.append(child)
        d = parent.to_dict()
        assert len(d["children"]) == 1
        assert d["children"][0]["path"] == "/home/user/AGENTS.md"

    def test_session_node_to_dict(self):
        s = SessionNode(
            terminal_type="ttyd", terminal_port=5001,
            mux_type="tmux", mux_session="claude",
        )
        d = s.to_dict()
        assert d["terminal_type"] == "ttyd"
        assert d["mux_session"] == "claude"


# ---------------------------------------------------------------------------
# Diagnostic rules
# ---------------------------------------------------------------------------

class TestAIRules:
    """Tests for AI diagnostic rules."""

    def test_backend_down(self):
        """Detect when local LLM backend port is not listening."""
        chain = AIChain(
            id="ai:llama:1234",
            agent=AgentNode(
                agent_type="llama_cpp", pid=1234,
                cwd="/", cmdline="llama-server",
                display_name="llama.cpp",
            ),
            backend=BackendNode(
                backend_type="local", provider="llama_cpp",
                endpoint="127.0.0.1:8123", ports=[8123],
            ),
        )
        state = SystemState(listening_ports={})  # port 8123 NOT listening
        state.ai_chains = [chain]
        issues = check_ai_backend_down(state, DEFAULTS)
        assert len(issues) >= 1
        assert issues[0].rule_id == "ai-backend-down"
        assert issues[0].severity == "critical"

    def test_backend_up_no_issue(self):
        """No issue when backend port is listening."""
        chain = AIChain(
            id="ai:llama:1234",
            agent=AgentNode(
                agent_type="llama_cpp", pid=1234,
                cwd="/", cmdline="llama-server",
                display_name="llama.cpp",
            ),
            backend=BackendNode(
                backend_type="local", provider="llama_cpp",
                endpoint="127.0.0.1:8123", ports=[8123],
            ),
        )
        state = SystemState(listening_ports={8123: "127.0.0.1"})
        state.ai_chains = [chain]
        issues = check_ai_backend_down(state, DEFAULTS)
        assert len(issues) == 0

    def test_model_missing(self, tmp_path):
        """Detect when model file does not exist."""
        chain = AIChain(
            id="ai:llama:1234",
            agent=AgentNode(
                agent_type="llama_cpp", pid=1234,
                cwd="/", cmdline="llama-server",
                display_name="llama.cpp",
            ),
            backend=BackendNode(
                backend_type="local", provider="llama_cpp",
                endpoint="127.0.0.1:8123",
                model_path="/nonexistent/model.gguf",
            ),
        )
        state = SystemState()
        state.ai_chains = [chain]
        issues = check_ai_model_missing(state, DEFAULTS)
        assert len(issues) >= 1
        assert issues[0].rule_id == "ai-model-missing"

    def test_model_exists_no_issue(self, tmp_path):
        """No issue when model file exists."""
        model = tmp_path / "model.gguf"
        model.write_bytes(b"\x00" * 100)
        chain = AIChain(
            id="ai:llama:1234",
            agent=AgentNode(
                agent_type="llama_cpp", pid=1234,
                cwd="/", cmdline="llama-server",
                display_name="llama.cpp",
            ),
            backend=BackendNode(
                backend_type="local", provider="llama_cpp",
                endpoint="127.0.0.1:8123",
                model_path=str(model),
            ),
        )
        state = SystemState()
        state.ai_chains = [chain]
        issues = check_ai_model_missing(state, DEFAULTS)
        assert len(issues) == 0

    def test_config_missing(self):
        """Detect expected config that does not exist."""
        chain = AIChain(
            id="ai:claude:1234",
            agent=AgentNode(
                agent_type="claude-code", pid=1234,
                cwd="/", cmdline="claude",
                display_name="Claude Code",
            ),
            configs=[ConfigNode(
                path="/nonexistent/CLAUDE.md",
                config_type="instruction",
                exists=False,
                confidence=0.9,
            )],
        )
        state = SystemState()
        state.ai_chains = [chain]
        issues = check_ai_config_missing(state, DEFAULTS)
        assert len(issues) >= 1
        assert issues[0].rule_id == "ai-config-missing"

    def test_no_chains_no_issues(self):
        """No AI chains means no AI issues."""
        state = SystemState()
        assert check_ai_backend_down(state, DEFAULTS) == []
        assert check_ai_model_missing(state, DEFAULTS) == []
        assert check_ai_config_missing(state, DEFAULTS) == []
        assert check_ai_orphan_backend(state, DEFAULTS) == []


# ---------------------------------------------------------------------------
# Chain parser
# ---------------------------------------------------------------------------

class TestChainParser:
    """Tests for config chain tracing."""

    def test_parse_markdown_references(self, tmp_path):
        """Markdown files reference other files via absolute paths."""
        from nervmap.ai.chain_parser import trace_config_chain

        child_file = tmp_path / "AGENTS.md"
        child_file.write_text("# Shared rules\nAll agents must...")

        main_file = tmp_path / "CLAUDE.md"
        main_file.write_text(f"# Instructions\nRead {child_file} for rules.\n")

        config = ConfigNode(
            path=str(main_file), config_type="instruction", exists=True,
        )
        trace_config_chain(config)

        assert config.role == "project instructions (loaded every prompt)"
        assert len(config.children) >= 1
        assert any(c.path == str(child_file) for c in config.children)

    def test_parse_json_settings(self, tmp_path):
        """JSON settings with hooks are parsed."""
        from nervmap.ai.chain_parser import trace_config_chain

        settings = tmp_path / "settings.json"
        settings.write_text(json.dumps({
            "hooks": {},
            "permissions": {"allow": ["Read"], "deny": [], "ask": ["Write"]},
        }))

        config = ConfigNode(
            path=str(settings), config_type="settings", exists=True,
        )
        trace_config_chain(config)
        assert "permissions" in config.role

    def test_max_depth_prevents_infinite_loop(self, tmp_path):
        """Circular references don't cause infinite recursion."""
        from nervmap.ai.chain_parser import trace_config_chain

        a = tmp_path / "a.md"
        b = tmp_path / "b.md"
        a.write_text(f"See {b}")
        b.write_text(f"See {a}")

        config = ConfigNode(path=str(a), config_type="instruction", exists=True)
        # Should not raise
        trace_config_chain(config)


# ---------------------------------------------------------------------------
# CLI command
# ---------------------------------------------------------------------------

class TestAICollectorIntegration:
    """Integration tests for AICollector with mocked /proc."""

    def test_collect_with_mocked_processes(self):
        """AICollector discovers agents from mocked process data."""
        from unittest.mock import patch
        from nervmap.ai.collector import AICollector

        fake_procs = {
            100: "claude ",
            200: "llama-server --model /opt/models/test.gguf --port 8123 --host 127.0.0.1 --n-gpu-layers 40 --ctx-size 8192",
            300: "nginx -g daemon off",
            400: "codex ",
        }

        def mock_iter_pids():
            return iter(fake_procs.keys())

        def mock_read_cmdline(pid):
            return fake_procs.get(pid, "")

        def mock_read_cwd(pid):
            return "/home/user"

        collector = AICollector()
        with patch.object(collector, '_iter_pids', mock_iter_pids), \
             patch.object(collector, '_read_cmdline', mock_read_cmdline), \
             patch.object(collector, '_read_cwd', mock_read_cwd), \
             patch.object(collector, '_load_tmux_panes'):
            collector._tmux_panes = {}
            chains = collector.collect()

        # Should find claude, codex, and llama-server (3 chains)
        agent_types = {c.agent.agent_type for c in chains if c.agent}
        assert "claude-code" in agent_types
        assert "codex-cli" in agent_types
        assert "llama_cpp" in agent_types
        # nginx should NOT be detected
        assert not any(c.agent.agent_type == "nginx" for c in chains if c.agent)

    def test_collect_llama_model_parsing(self):
        """Verify model name and GPU layers are parsed from cmdline."""
        from unittest.mock import patch
        from nervmap.ai.collector import AICollector

        fake_procs = {
            500: "llama-server --model /opt/models/Qwen3-8B-Q4_K_M.gguf --port 9000 --n-gpu-layers 99 --ctx-size 16384",
        }

        collector = AICollector()
        with patch.object(collector, '_iter_pids', lambda: iter(fake_procs.keys())), \
             patch.object(collector, '_read_cmdline', lambda pid: fake_procs.get(pid, "")), \
             patch.object(collector, '_read_cwd', lambda pid: "/"), \
             patch.object(collector, '_load_tmux_panes'):
            collector._tmux_panes = {}
            chains = collector.collect()

        llama_chains = [c for c in chains if c.backend and c.backend.provider == "llama_cpp"]
        assert len(llama_chains) >= 1
        bk = llama_chains[0].backend
        assert bk.model_name == "Qwen3-8B-Q4_K_M"
        assert bk.gpu_layers == 99
        assert bk.context_size == 16384
        assert "9000" in bk.endpoint

    def test_collect_empty_server(self):
        """No AI processes returns empty chains."""
        from unittest.mock import patch
        from nervmap.ai.collector import AICollector

        collector = AICollector()
        with patch.object(collector, '_iter_pids', lambda: iter([])), \
             patch.object(collector, '_load_tmux_panes'):
            collector._tmux_panes = {}
            chains = collector.collect()

        assert chains == []


# ---------------------------------------------------------------------------
# Noise filtering
# ---------------------------------------------------------------------------

class TestNoiseFiltering:
    """Tests for _scan_open_files noise filtering."""

    def test_node_modules_filtered(self):
        """Paths containing /node_modules/ should be filtered."""
        from nervmap.ai.config_resolver import ConfigResolver
        resolver = ConfigResolver()
        # The noise filter is on the class, test it directly
        noise_path = "/home/user/project/node_modules/express/package.json"
        assert any(noise in noise_path for noise in resolver._FD_NOISE_DIRS)

    def test_regular_path_not_filtered(self):
        """Normal config paths should not be filtered."""
        from nervmap.ai.config_resolver import ConfigResolver
        resolver = ConfigResolver()
        good_path = "/home/user/.claude/settings.json"
        assert not any(noise in good_path for noise in resolver._FD_NOISE_DIRS)


# ---------------------------------------------------------------------------
# Quoted paths
# ---------------------------------------------------------------------------

class TestQuotedPaths:
    """Tests for _extract_paths_from_command with quoted paths."""

    def test_quoted_path_with_spaces(self, tmp_path):
        """Paths in quotes with spaces should be extracted."""
        from nervmap.ai.chain_parser import _extract_paths_from_command

        spaced_dir = tmp_path / "my scripts"
        spaced_dir.mkdir()
        script = spaced_dir / "hook.sh"
        script.write_text("#!/bin/bash\necho hi")

        cmd = f'"/bin/bash" "{script}"'
        paths = _extract_paths_from_command(cmd)
        assert str(script) in paths

    def test_env_var_skipped(self):
        """Env var assignments should not produce paths."""
        from nervmap.ai.chain_parser import _extract_paths_from_command
        cmd = "MY_VAR=/usr/local/bin/tool /usr/local/bin/tool run"
        paths = _extract_paths_from_command(cmd)
        # Only the actual binary path, not the env var value
        assert all("MY_VAR" not in p for p in paths)


# ---------------------------------------------------------------------------
# CLI command
# ---------------------------------------------------------------------------

class TestAICommand:
    """Tests for nervmap ai CLI command."""

    def test_ai_command_exists(self):
        from nervmap.cli import main
        assert "ai" in [cmd for cmd in main.commands]
