# NervMap — Specification v0.1.0

> `docker ps` shows containers. NervMap shows why your app is down.

## Vision

Outil open-source CLI qui cartographie automatiquement l'infrastructure d'un serveur Linux (Docker + systemd + bare processes), infere les dependances entre services, et diagnostique les problemes avec des suggestions de fix. Zero config, single command, instant results.

## Scope MVP v0.1.0

### In Scope
- **Discovery** : Docker containers (via Docker API socket), systemd services (via systemctl), TCP ports (via /proc/net/tcp ou ss)
- **Health checks** : process alive, port responding, HTTP 200 pour endpoints web
- **Dependency inference** : connexions TCP actives (ss -tnp), env vars (DATABASE_URL, REDIS_HOST, *_PORT), docker-compose depends_on/links, Docker networks
- **Diagnostics** : 15-20 regles embarquees (port conflict, OOM-kill exit 137, restart loop, connection refused, service depends on down service, config mismatch env vs port reel, disk pressure, cert expiring)
- **Output** : CLI coloree (Rich ou equivalent), --json flag, --quiet flag
- **Shell hooks** : ~/.nervmap/hooks/on-service-down.sh, on-issue-detected.sh (JSON sur stdin)
- **Config optionnelle** : .nervmap.yml pour overrides (ports a ignorer, timeouts custom, services a exclure)

### Out of Scope v0.1
- Web dashboard (v0.2+)
- Watch/daemon mode (v0.2+)
- REST API (v0.2+)
- LLM integration (plugin, v0.3+)
- Multi-server (v0.3+)
- Kubernetes (v0.3+)
- Windows/macOS host scanning

## Architecture

```
CLI Entry Point
  |
  +-- Discovery Engine
  |     +-- DockerCollector (Docker API via socket)
  |     +-- SystemdCollector (systemctl + journalctl)
  |     +-- PortCollector (/proc/net/tcp + ss)
  |     +-- ProcessCollector (/proc/*/cmdline, /proc/*/environ)
  |
  +-- Topology Builder
  |     +-- DependencyMapper (TCP connections, env vars, compose files)
  |     +-- ServiceFingerprinter (port -> service type heuristics)
  |     +-- ConfidenceScorer (100% declared, 85% observed, 60% inferred)
  |
  +-- Diagnostic Engine
  |     +-- RuleRunner (evaluate all rules against current state)
  |     +-- ImpactAnalyzer (which services are affected by each issue)
  |     +-- FixSuggester (deterministic suggestions, no LLM)
  |
  +-- Output Engine
  |     +-- ConsoleRenderer (colored CLI output)
  |     +-- JsonRenderer (machine-readable)
  |     +-- HookRunner (shell hooks on events)
  |
  +-- Plugin Interface (v0.2+)
        +-- Subprocess JSON protocol
        +-- Shell hooks (v0.1)
```

## Tech Stack

- **Language** : Python 3.10+ (MVP rapid proto, Go rewrite possible later)
- **CLI framework** : Click or Typer
- **Output** : Rich (colored tables, trees)
- **Docker** : docker SDK for Python
- **System** : psutil, /proc parsing
- **Config** : PyYAML or TOML
- **Zero heavy dependencies** : no databases, no web frameworks, no async runtime needed

## Data Model

```python
@dataclass
class Service:
    id: str                    # "docker:nginx" or "systemd:qwen35" or "process:node:8080"
    name: str
    type: str                  # docker | systemd | process
    status: str                # running | stopped | degraded | unknown
    ports: list[int]
    pid: int | None
    health: str                # healthy | unhealthy | no_check
    metadata: dict             # container_id, image, unit_file, etc.

@dataclass
class Connection:
    source: str                # service id
    target: str                # service id
    type: str                  # tcp | unix | declared | inferred
    source_port: int | None
    target_port: int | None
    confidence: float          # 0.0 - 1.0

@dataclass
class Issue:
    rule_id: str               # "port-conflict", "dependency-down"
    severity: str              # critical | warning | info
    service: str               # affected service id
    message: str
    hint: str                  # suggested fix
    impact: list[str]          # list of dependent service ids
```

## Diagnostic Rules (MVP)

### Network
- `port-conflict` : two services on same port
- `port-unreachable` : service declared but port not responding
- `port-exposed-wildcard` : listening on 0.0.0.0 (security warning)
- `connection-refused` : active dependency returns connection refused

### Docker
- `container-restart-loop` : restart count > 3 in 10min
- `container-unhealthy` : healthcheck failing
- `container-oom-killed` : exit code 137
- `container-orphan` : running but not in any compose

### Systemd
- `service-failed` : unit in failed state
- `service-activating-stuck` : activating > 60s

### Dependencies
- `dependency-down` : service A depends on B, B is down
- `env-port-mismatch` : env var points to port X, but service listens on port Y
- `circular-dependency` : A -> B -> A

### Resources
- `disk-pressure` : filesystem > 90%
- `memory-oom-risk` : RSS > 80% of cgroup limit

## Configuration (.nervmap.yml)

```yaml
# Optional - everything works without this file
scan:
  docker: true
  systemd: true
  ports: true

ignore:
  ports: [22]                  # Don't flag SSH
  services: ["snap.*"]         # Regex patterns to exclude

timeouts:
  http: 5                      # seconds
  tcp: 3

custom_services:
  - name: "my-llm"
    port: 8123
    health_url: "http://127.0.0.1:8123/health"
    timeout: 10                # LLM is slow, give it time

hooks:
  on_issue: "~/.nervmap/hooks/notify.sh"
```

## CLI Interface

```bash
nervmap                        # Full scan, colored output
nervmap scan                   # Same as above (explicit)
nervmap scan --json            # Machine-readable JSON
nervmap scan --quiet           # Only issues, no service list
nervmap scan --deep            # Also parse config files (nginx, compose)
nervmap deps                   # Show only dependency graph
nervmap deps --dot             # Output in Graphviz DOT format
nervmap deps --mermaid         # Output in Mermaid format
nervmap issues                 # Show only issues
nervmap issues --critical      # Only critical issues
nervmap version                # Version info
```

## Distribution

```bash
pip install nervmap            # Primary
pipx install nervmap           # Isolated install
curl -fsSL get.nervmap.dev | sh  # Script install (future)
```

## Project Structure

```
nervmap/
  nervmap/
    __init__.py
    __main__.py              # python -m nervmap
    cli.py                   # Click/Typer CLI
    discovery/
      __init__.py
      docker.py              # Docker API collector
      systemd.py             # systemctl collector
      ports.py               # /proc/net/tcp + ss
      process.py             # /proc/*/cmdline, environ
    topology/
      __init__.py
      mapper.py              # Dependency inference
      fingerprints.py        # Port -> service type
    diagnostics/
      __init__.py
      engine.py              # Rule runner
      rules/
        __init__.py
        network.py
        docker.py
        systemd.py
        dependencies.py
        resources.py
    output/
      __init__.py
      console.py             # Rich renderer
      json.py                # JSON renderer
      hooks.py               # Shell hook runner
    config.py                # .nervmap.yml loader
    models.py                # Service, Connection, Issue dataclasses
  tests/
    test_discovery.py
    test_topology.py
    test_diagnostics.py
    test_output.py
  pyproject.toml
  README.md
  LICENSE                    # MIT
  .nervmap.yml.example
```

## Success Criteria MVP

1. `pip install nervmap && nervmap` works in < 10 seconds on any Linux server
2. Correctly discovers > 90% of Docker containers and systemd services
3. Infers at least 50% of actual dependencies via TCP connections
4. Zero false positive on critical issues
5. < 5% false positive on warnings
6. Beautiful colored output that makes you want to screenshot it
