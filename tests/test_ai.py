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

class TestAICommand:
    """Tests for nervmap ai CLI command."""

    def test_ai_command_exists(self):
        from nervmap.cli import main
        assert "ai" in [cmd for cmd in main.commands]
