# NervMap

> `docker ps` shows containers. **NervMap shows why your app is down.**

Your infrastructure's nervous system. Discovers services, maps dependencies, analyzes source code, and diagnoses failures. Zero config required.

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://python.org)
[![Tests](https://img.shields.io/badge/Tests-170%20passed-brightgreen.svg)]()

---

## What It Does

You arrive on a server. You type `nervmap`. In under 2 seconds, you see:

- **Every service running** (Docker containers + systemd units + bare processes)
- **Who depends on who** (inferred from TCP connections, env vars, Docker networks)
- **Source code cross-references** (which code project runs in which container)
- **AI agent chains** (which LLM, which config files, which terminal session)
- **What's broken and why** (25 diagnostic rules with severity, impact, and fix suggestions)

No config file. No setup wizard. No database. Just answers.

---

## Install

```bash
pip install nervmap
```

Or in isolation:

```bash
pipx install nervmap
```

---

## Quick Start

```bash
# Infrastructure scan
nervmap                              # Full scan, colored output
nervmap scan --json                  # Machine-readable JSON
nervmap scan --quiet                 # Issues only
nervmap scan --no-code               # Skip source code analysis

# Scope filtering
nervmap --scope myapp scan           # Scan only services matching "myapp"
nervmap --scope "docker:next*" scan  # Glob pattern on service IDs
nervmap --scope /opt/myproject scan  # Scope to a docker-compose project dir

# Source code analysis
nervmap code /opt/myproject          # Analyze a specific project directory
nervmap code /opt/myproject --json   # JSON output for code analysis

# AI agent mapping
nervmap ai                           # Map all AI agents + LLM backends
nervmap ai --json                    # JSON output

# Other
nervmap version                      # Show version

# Dependency graph
nervmap deps                         # Pretty-print dependency graph
nervmap deps --dot                   # Graphviz DOT export
nervmap deps --mermaid               # Mermaid diagram export

# Diagnostics
nervmap issues                       # All issues
nervmap issues --critical            # Critical only

# Options
nervmap scan --deep                  # Deep scan (parse config files)
nervmap scan --verbose               # Debug logging
nervmap scan --no-hooks              # Disable shell hooks
nervmap scan --show-secrets          # Show raw env vars (dangerous)
nervmap scan --config /path/to.yml   # Custom config file
```

---

## Discovery

NervMap auto-detects services from 4 sources simultaneously.

| Source | What It Finds | How |
|--------|--------------|-----|
| **Docker** | Containers, ports, health, networks, env vars | Docker API socket |
| **Systemd** | Services, states, PIDs | `systemctl` |
| **TCP Ports** | All listening ports with owning PIDs | `/proc/net/tcp` + `/proc/net/tcp6` |
| **Processes** | Bare processes with port correlation | `/proc/*/cmdline` + `/proc/*/fd` |

### Scope Filtering

Use `--scope` to limit the scan to a specific project:

| Scope Format | Example | What It Matches |
|-------------|---------|-----------------|
| Substring | `--scope myapp` | Any service with "myapp" in name or ID |
| Glob pattern | `--scope "docker:next*"` | Service IDs matching the glob |
| Compose directory | `--scope /opt/myproject` | Services from that docker-compose project |

All commands (`scan`, `deps`, `issues`) respect `--scope`.

---

## Source Code Analysis (v0.2)

NervMap automatically finds source code projects linked to running services and cross-references them with the infrastructure.

### Project Discovery

3 strategies, tried in order:

| Strategy | Source | Signal |
|----------|--------|--------|
| Docker Compose labels | `com.docker.compose.project.working_dir` | Container metadata |
| Systemd ExecStart | Service unit file paths | `/etc/systemd/system/*.service` |
| Config `source.paths` | `.nervmap.yml` explicit paths | User-defined |

### Code-to-Infrastructure Linking

4 linking strategies with confidence scores:

| Strategy | Confidence | Method |
|----------|-----------|--------|
| Docker Compose `build.context` | 100% | Declared build context matches project path |
| Docker label `working_dir` | 100% | Label path matches project path |
| Dockerfile `COPY`/`ADD` | 85% | Dockerfile copies from project dir + name match |
| Proximity heuristic | 60% | Dockerfile in project dir + name match |

### Language Support

| Language | Detected By | Parsed |
|----------|------------|--------|
| Python | `requirements.txt`, `pyproject.toml`, `setup.py` | imports, `os.getenv()`, `PORT =` bindings |
| JavaScript | `package.json` | `require()`, `import`, `process.env` |
| TypeScript | `tsconfig.json` | `import`, `process.env` |
| Go | `go.mod` | dependency names (go.mod only, no source parsing) |

### Framework Detection

Python: FastAPI, Flask, Django, Starlette, Tornado, Sanic
JavaScript/TypeScript: Express, Next.js, Nuxt.js, Koa, Hapi, Fastify, NestJS
Go: Gin, Gorilla, Fiber

---

## AI Agent Chain Mapping (v0.3)

NervMap traces the **complete execution chain** of every AI agent and LLM on the server — from the user's terminal to the inference engine, file by file.

```bash
nervmap ai
```

### What It Maps

For each AI agent, NervMap shows:
- **Terminal entry** — which ttyd/SSH port exposes the session
- **Session multiplexer** — which tmux/screen session contains the agent
- **Agent process** — PID, working directory, agent type
- **Config files** — every file that controls behavior, with role and references
- **LLM backend** — local model (path, GPU layers, context size) or cloud API (provider, auth method)

### Config Chain Tracing

NervMap recursively follows file references to build the full instruction chain:

```
ttyd :5001 -> tmux "dev" -> claude-code [PID]
  I CLAUDE.md (project instructions, loaded every prompt)
     I shared-rules.md (referenced instruction file)
  S settings.json (hooks, permissions, plugins)
     H pre-check.sh (hook: PreToolUse)
     H startup.sh (hook: SessionStart)
  Backend: api.anthropic.com (oauth)
```

### Supported Agents & Backends

| Type | Detected By |
|------|------------|
| Claude Code | `claude` binary signature |
| Codex CLI | `codex` binary signature |
| Gemini CLI | `gemini` binary signature |
| llama.cpp | `llama-server` in cmdline (extracts model, GPU layers, ctx) |
| Ollama | `ollama serve` in cmdline |
| vLLM | `vllm.entrypoints` in cmdline |
| TGI | `text-generation-launcher` in cmdline |
| Embedding servers | `embedding-server` / `embedding*.py` patterns |

---

## Dependency Mapping

NervMap infers connections between services using multiple evidence layers:

| Layer | Confidence | Method |
|-------|-----------|--------|
| Docker Compose `depends_on` | 100% | Declared |
| TCP established connections | 85% | Observed via `ss`/`/proc` |
| Environment variables (`DATABASE_URL`, `REDIS_HOST`, etc.) | 60% | Inferred |
| Docker network membership | 30% | Association |

50+ service fingerprints built-in (PostgreSQL, Redis, MySQL, MongoDB, Elasticsearch, Nginx, and more).

---

## Diagnostics

25 built-in rules, zero false positives, deterministic (no LLM required):

| Category | Rules |
|----------|-------|
| **Network** | `port-conflict`, `port-unreachable`, `port-exposed-wildcard`, `connection-refused` |
| **Docker** | `container-restart-loop`, `container-unhealthy`, `container-oom-killed`, `container-orphan` |
| **Systemd** | `service-failed`, `service-activating-stuck` |
| **Dependencies** | `dependency-down`, `env-port-mismatch`, `circular-dependency` |
| **Resources** | `disk-pressure`, `memory-oom-risk` |
| **Code** (v0.2) | `code-port-drift`, `code-env-missing`, `code-dep-missing`, `code-entrypoint-mismatch`, `code-env-example-drift`, `code-dockerfile-no-healthcheck` |
| **AI** (v0.3) | `ai-backend-down`, `ai-model-missing`, `ai-config-missing`, `ai-orphan-backend` |

### Code Diagnostic Rules (v0.2)

| Rule | Severity | Detects |
|------|----------|---------|
| `code-port-drift` | warning | Port in source code differs from runtime port |
| `code-env-missing` | warning | Code references env vars not defined in `.env` or runtime |
| `code-dep-missing` | info | Declared dependency not importable on the system |
| `code-entrypoint-mismatch` | warning | Dockerfile CMD/ENTRYPOINT points to missing file |
| `code-env-example-drift` | info | `.env.example` is missing vars that code references |
| `code-dockerfile-no-healthcheck` | info | Dockerfile has no HEALTHCHECK instruction |

### AI Diagnostic Rules (v0.3)

| Rule | Severity | Detects |
|------|----------|---------|
| `ai-backend-down` | critical | Local LLM backend port is not listening |
| `ai-model-missing` | critical | Model file referenced in cmdline does not exist |
| `ai-config-missing` | info | Expected config file for agent type not found |
| `ai-orphan-backend` | info | LLM backend running with no agent connected |

Every issue includes:
- **Severity** (critical / warning / info)
- **Affected service** with ID
- **Human-readable message** explaining what's wrong
- **Actionable hint** suggesting how to fix it
- **Impact list** of dependent services affected

---

## Security

- **Secrets are redacted by default** in all output (JSON, CLI, hooks)
- Env vars containing `PASSWORD`, `SECRET`, `KEY`, `TOKEN`, `CREDENTIAL` are masked
- URLs with embedded credentials (`://user:pass@host`) are masked
- Use `--show-secrets` to explicitly opt-in to raw output
- No shell injection: all subprocess calls use list arguments
- YAML config uses `safe_load` only
- Hook scripts require executable permission

---

## Configuration (Optional)

Everything works without config. Create `.nervmap.yml` to customize:

```yaml
scan:
  docker: true
  systemd: true
  ports: true

ignore:
  ports: [22]             # Don't flag SSH
  services: ["snap.*"]    # Regex patterns to exclude

source:
  paths:                  # Additional source code directories to scan
    - /opt/myapp
    - ~/projects/api

timeouts:
  http: 5
  tcp: 3

custom_services:
  - name: "my-llm"
    port: 8123
    health_url: "http://127.0.0.1:8123/health"
    timeout: 10

hooks:
  on_issue: "~/.nervmap/hooks/notify.sh"
```

Config search path: `./.nervmap.yml` > `~/.nervmap/config.yml`

---

## Shell Hooks

Trigger scripts when issues are detected:

```bash
mkdir -p ~/.nervmap/hooks
cat > ~/.nervmap/hooks/notify.sh << 'EOF'
#!/bin/bash
# Receives JSON on stdin with issue details
cat | jq '.issues[] | "\(.severity): \(.message)"'
EOF
chmod +x ~/.nervmap/hooks/notify.sh
```

Hook data is always redacted (no secrets passed to external scripts).

---

## Requirements

- **Linux** (Ubuntu 20.04+, Debian 11+, RHEL 8+, Arch)
- **Python 3.10+**
- Docker socket access (optional — skips Docker discovery if unavailable)
- Root or docker group (optional — for full `/proc` access)

---

## Roadmap

- [x] Source code analysis (v0.2)
- [x] AI agent chain mapping (v0.3)
- [ ] `nervmap watch` — live monitoring daemon
- [ ] `nervmap serve` — REST API + WebSocket
- [ ] Web dashboard (Cytoscape.js graph)
- [ ] Plugin system (subprocess JSON protocol)
- [ ] Kubernetes support
- [ ] Community diagnostic rules (YAML format)
- [ ] Incremental scan cache (SQLite)
- [ ] Custom AI agent profiles in `.nervmap.yml`

---

## License

MIT — Copyright 2026 AxonLabsDev

See [LICENSE](LICENSE) for details.
