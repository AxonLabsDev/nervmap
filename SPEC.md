# NervMap — Specification v0.1.0

> `docker ps` shows containers. NervMap shows why your app is down.

## Status: v0.1.0 MVP — COMPLETE (10/10 review score)

- 71 tests passing
- 0% false positive rate
- 0.6s scan time
- --scope flag for project-level filtering

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
  +-- Topology Builder
  |     +-- DependencyMapper (TCP established, env vars, docker-compose)
  |     +-- ServiceFingerprinter (50+ port->service type mappings)
  |     +-- Confidence scoring (100% declared, 85% observed, 60% inferred, 30% association)
  |
  +-- Diagnostic Engine
  |     +-- RuleRunner (15 rules, deepcopy state, ignore.services regex)
  |     +-- ImpactAnalyzer (dependent services per issue)
  |     +-- FixSuggester (deterministic, no LLM)
  |
  +-- Output Engine
  |     +-- ConsoleRenderer (Rich colored tables)
  |     +-- JsonRenderer (secrets redacted by default)
  |     +-- HookRunner (shell hooks, redacted data, +x check)
  |
  +-- Security
        +-- redact_env() on collection + output (defense in depth)
        +-- Patterns: PASSWORD, SECRET, KEY, TOKEN, CREDENTIAL, ://user:pass@
        +-- --show-secrets opt-in flag
```

## Tech Stack

- Python 3.10+, Click, Rich, psutil, docker SDK, PyYAML
- Zero database, in-memory only
- Single command install: `pip install nervmap`

## Diagnostic Rules (15)

### Network
- `port-conflict` — host-mapped ports only, docker-proxy filtered
- `port-unreachable` — Docker internal ports excluded
- `port-exposed-wildcard` — 0.0.0.0 / :: detection (severity: warning)
- `connection-refused` — uses actual bind address, skips confirmed listening ports

### Docker
- `container-restart-loop` — restart count > 3
- `container-unhealthy` — healthcheck failing
- `container-oom-killed` — exit code 137
- `container-orphan` — no docker-compose labels

### Systemd
- `service-failed` — unit in failed state
- `service-activating-stuck` — activating > 60s

### Dependencies
- `dependency-down` — service depends on stopped service
- `env-port-mismatch` — env var points to non-listening port
- `circular-dependency` — DFS with frozenset dedup, association edges excluded

### Resources
- `disk-pressure` — filesystem > 90% (snap/boot excluded)
- `memory-oom-risk` — system memory > 80%

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

## Roadmap

- v0.2: watch mode, REST API, WebSocket, plugin system
- v0.3: Cytoscape.js web dashboard, community rules YAML
- v1.0: Go rewrite (single binary), Kubernetes support

## License

MIT — Copyright 2026 AxonLabsDev
