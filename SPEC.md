# NervMap — Specification v0.4.0

> `docker ps` shows containers. NervMap shows why your app is down.

## Status: v0.4.0 — COMPLETE (10/10 review score)

- 179 tests passing, 77% coverage
- 0% false positive rate
- 26 diagnostic rules (15 infra + 6 code + 5 AI)
- Source code analysis with 4-strategy linking
- AI agent chain mapping with config tracing + proxy detection + consumer tracking
- `nervmap code` and `nervmap ai` subcommands

## Architecture

```
CLI Entry Point (Click)
  |
  +-- Discovery Engine
  |     +-- DockerCollector (Docker API socket, host-mapped ports only)
  |     +-- SystemdCollector (systemctl JSON + fallback text)
  |     +-- PortCollector (/proc/net/tcp + /proc/net/tcp6, IPv4-mapped IPv6 support)
  |     +-- ProcessCollector (/proc/*/cmdline + /proc/*/fd, docker-proxy filtered)
  |
  +-- Source Code Analysis (v0.2)
  |     +-- ProjectLocator (3 discovery strategies)
  |     |     +-- Docker Compose labels (working_dir)
  |     |     +-- Systemd ExecStart paths
  |     |     +-- Config source.paths (user-defined)
  |     +-- CodeLinker (4 linking strategies with confidence)
  |     |     +-- build.context match (100%)
  |     |     +-- working_dir label match (100%)
  |     |     +-- Dockerfile COPY/ADD (85%)
  |     |     +-- Proximity heuristic (60%)
  |     +-- Language Parsers
  |     |     +-- PythonParser (imports, os.getenv, port bindings)
  |     |     +-- JsParser (require, import, process.env)
  |     |     +-- ConfigParser (.env, Dockerfile, nginx, compose)
  |     +-- SourceCache (SQLite incremental, mtime+size->sha256) [wired for future use]
  |
  +-- AI Agent Mapping (v0.3)
  |     +-- AICollector (2-phase: process signatures + tmux/ttyd)
  |     +-- ConfigResolver (static registry + /proc/fd hybrid, confidence 0.9)
  |     +-- ChainParser (recursive file reference tracing)
  |     +-- Signatures (Claude Code, Codex, Gemini, llama.cpp, Ollama, vLLM, TGI)
  |     +-- AIRenderer (Rich tree view per chain)
  |     +-- 4 AI diagnostic rules
  |
  +-- Topology Builder
  |     +-- DependencyMapper (TCP established, env vars, docker-compose, Docker networks)
  |     +-- ServiceFingerprinter (50+ port->service type mappings)
  |     +-- Confidence scoring (100% declared, 85% observed, 60% inferred, 30% association)
  |
  +-- Diagnostic Engine
  |     +-- RuleRunner (25 rules, deepcopy state, ignore.services regex)
  |     +-- ImpactAnalyzer (dependent services per issue)
  |     +-- FixSuggester (deterministic, no LLM)
  |
  +-- Output Engine
  |     +-- ConsoleRenderer (Rich colored tables + code analysis display)
  |     +-- JsonRenderer (secrets redacted, projects + connections_to_infra)
  |     +-- HookRunner (shell hooks, redacted data, +x check)
  |
  +-- Security
        +-- redact_env() on collection + output (defense in depth)
        +-- Patterns: PASSWORD, SECRET, KEY, TOKEN, CREDENTIAL, ://user:pass@
        +-- --show-secrets opt-in flag
```

## Tech Stack

- Python 3.10+, Click, Rich, psutil, docker SDK, PyYAML
- Zero database, in-memory only (SQLite cache prepared for v0.3)
- Single command install: `pip install nervmap`

## CLI Commands

| Command | Description |
|---------|------------|
| `nervmap` / `nervmap scan` | Full infrastructure + code scan |
| `nervmap scan --no-code` | Skip source code analysis |
| `nervmap code <path>` | Analyze source code in a specific directory |
| `nervmap deps` | Show dependency graph |
| `nervmap deps --dot` | Graphviz DOT export |
| `nervmap deps --mermaid` | Mermaid diagram export |
| `nervmap issues` | Show diagnosed issues |
| `nervmap issues --critical` | Critical issues only |
| `nervmap version` | Show version |

## Global Flags

| Flag | Description |
|------|------------|
| `--scope <pattern>` | Limit scan to matching services |
| `--json` | Machine-readable JSON output |
| `--quiet` | Issues only, no service list |
| `--deep` | Deep scan (config file parsing) |
| `--show-secrets` | Show raw env vars (dangerous) |
| `--verbose` / `-v` | Debug logging |
| `--no-hooks` | Skip shell hook execution |
| `--config <path>` | Custom config file path |

## Diagnostic Rules (25)

### Network (4)
- `port-conflict` — host-mapped ports only, docker-proxy filtered
- `port-unreachable` — Docker internal ports excluded
- `port-exposed-wildcard` — 0.0.0.0 / :: detection (severity: warning)
- `connection-refused` — uses actual bind address, skips confirmed listening ports

### Docker (4)
- `container-restart-loop` — restart count > 3
- `container-unhealthy` — healthcheck failing
- `container-oom-killed` — exit code 137
- `container-orphan` — no docker-compose labels

### Systemd (2)
- `service-failed` — unit in failed state
- `service-activating-stuck` — activating > 60s

### Dependencies (3)
- `dependency-down` — service depends on stopped service
- `env-port-mismatch` — env var points to non-listening port (skips Docker hostnames)
- `circular-dependency` — DFS with frozenset dedup, association edges excluded, declared-only cycles skipped, 2-node inferred cycles downgraded to info

### Resources (2)
- `disk-pressure` — filesystem > 90% (snap/boot excluded)
- `memory-oom-risk` — system memory > 80%

### Code (6) — v0.2
- `code-port-drift` — port in source code != port in runtime container (Dockerfile EXPOSE excluded — infra, not code)
- `code-env-missing` — env vars referenced in code but undefined in .env or runtime
- `code-dep-missing` — declared dependencies not importable (uses find_spec, not __import__)
- `code-entrypoint-mismatch` — Dockerfile CMD/ENTRYPOINT points to missing file (skipped when FROM is app image, not base image)
- `code-env-example-drift` — .env.example missing vars that code references
- `code-dockerfile-no-healthcheck` — Dockerfile has no HEALTHCHECK instruction

## Source Code Analysis (v0.2)

### Project Discovery
ProjectLocator uses 3 strategies:
1. Docker Compose labels (`com.docker.compose.project.working_dir`)
2. Systemd ExecStart paths (directory of executable)
3. Config `source.paths` (user-defined list in `.nervmap.yml`)

### Language Detection
| Marker | Language |
|--------|----------|
| `requirements.txt` / `pyproject.toml` / `setup.py` | Python |
| `package.json` | JavaScript |
| `tsconfig.json` | TypeScript |
| `go.mod` | Go |

### Code Parsing
- **PythonParser**: regex-based (no AST for speed), extracts imports, `os.getenv()`, `os.environ[]`, port bindings
- **JsParser**: `require()`, `import from`, `process.env.*`
- **ConfigParser**: `.env` key-value, Dockerfile CMD/ENTRYPOINT/EXPOSE/HEALTHCHECK/COPY, nginx upstream, compose build context

### CodeLinker
Links Docker containers to source code directories. 4 strategies with decreasing confidence:
1. `build-context` (100%): docker-compose build.context matches project path
2. `working-dir-label` (100%): Docker label matches project path
3. `dockerfile-copy` (85%): Dockerfile COPY from project dir + name match
4. `proximity` (60%): Dockerfile in project dir + name match

### JSON Output (v0.2)
When projects are found, JSON output includes:
- `projects`: list of CodeProject objects (path, language, framework, dependencies, env_refs, port_bindings, linked_services)
- `connections_to_infra`: cross-references from code env refs to linked infrastructure services

## Scope Filtering

`--scope` limits scan to a subset of services:
- Substring match: `--scope myapp`
- Glob pattern: `--scope "docker:next*"`
- Docker-compose directory: `--scope /opt/myproject`

Filters services, connections, listening_ports, and established data. All commands (scan, deps, issues) respect scope.

## Key Design Decisions

1. **Host-mapped ports only** for Docker — internal container ports are NOT on the host
2. **Docker network = association, not dependency** — prevents false circular-dependency
3. **Secrets redacted at collection AND output** — defense in depth
4. **No LLM in core** — deterministic rules only, LLM as optional plugin
5. **Zero config by default** — .nervmap.yml is optional
6. **All error paths logged** — no bare except:pass anywhere
7. **Scope = generic** — no hardcoded project names, works on any server
8. **Regex parsers, not AST** — fast, no tree-sitter dependency, good enough for env/port extraction
9. **find_spec over __import__** — safe dependency checking without executing module code
10. **Code analysis opt-out** — `--no-code` flag for infra-only scans
11. **AI detection via signatures, not tracing** — no strace/eBPF/MITM, pure /proc + tmux + static registry
12. **Config chain tracing** — recursive file reference parsing with depth limit and cycle protection
13. **Confidence scoring on configs** — 1.0 for /proc/fd observed, 0.9 for known path + exists, 0.85 for referenced

## AI Agent Chain Mapping (v0.3)

### Discovery
2-phase process:
1. **Signature scan**: walk /proc/*/cmdline, match against known agent/backend patterns (+ detect ttyd terminals in same pass)
2. **Session resolution**: `tmux list-panes -a` to map PIDs to sessions, ppid chain walk for ttyd linkage

### Agent Signatures
Claude Code, Codex CLI, Gemini CLI detected by binary name regex. llama.cpp, Ollama, vLLM, TGI detected by cmdline patterns.

### Config Resolution
- Static registry: known config paths per agent type (`{cwd}/CLAUDE.md`, `{home}/.claude/settings.json`, etc.)
- /proc/PID/fd snapshot: files currently open (upgrades confidence to 1.0)
- Content hash: sha256 for drift detection between scans

### Config Chain Tracing
Recursive parsing of config file contents to find referenced files:
- Markdown: regex extraction of absolute file paths
- JSON (settings): hooks, permissions, context files, plugins
- Shell commands (`cat`, `source`): referenced file paths
- Depth limit: 5 levels, cycle protection via `seen` set

### Diagnostic Rules (4)
- `ai-backend-down` — local LLM port not listening (critical)
- `ai-model-missing` — model file path does not exist (critical)
- `ai-config-missing` — expected config file not found (info)
- `ai-orphan-backend` — LLM running with no agent connected (info)
- `ai-gpu-overcommit` — GPU memory >90% with multiple LLM backends (warning)

## Roadmap

- v0.4: watch mode, REST API, WebSocket, incremental SQLite cache, plugin system
- v0.5: Cytoscape.js web dashboard, community rules YAML
- v1.0: Go rewrite (single binary), Kubernetes support

## License

MIT — Copyright 2026 AxonLabsDev
