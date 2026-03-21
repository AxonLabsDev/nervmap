# NervMap

> `docker ps` shows containers. **NervMap shows why your app is down.**

Your infrastructure's nervous system. Discovers services, maps dependencies, diagnoses failures. Zero config required.

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://python.org)
[![Tests](https://img.shields.io/badge/Tests-81%20passed-brightgreen.svg)]()

---

## What It Does

You arrive on a server. You type `nervmap`. In under 1 second, you see:

- **Every service running** (Docker containers + systemd units + bare processes)
- **Who depends on who** (inferred from TCP connections, env vars, Docker networks)
- **What's broken and why** (with severity, impact analysis, and fix suggestions)

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
nervmap                              # Full scan, colored output
nervmap scan --json                  # Machine-readable JSON
nervmap scan --quiet                 # Issues only
nervmap --scope myapp scan         # Scan only services matching "myapp"
nervmap --scope "docker:next*" scan  # Glob pattern on service IDs
nervmap --scope /opt/myproject scan  # Scope to a docker-compose project dir
nervmap deps                         # Dependency graph
nervmap deps --dot                   # Graphviz DOT export
nervmap deps --mermaid               # Mermaid diagram export
nervmap issues                       # All issues
nervmap issues --critical            # Critical only
nervmap scan --verbose               # Debug logging
nervmap scan --no-hooks              # Disable shell hooks
```

---

## Discovery

NervMap auto-detects services from 4 sources simultaneously.

Use `--scope` to limit the scan to a specific project:

| Scope Format | Example | What It Matches |
|-------------|---------|-----------------|
| Substring | `--scope myapp` | Any service with "myapp" in name or ID |
| Glob pattern | `--scope "docker:next*"` | Service IDs matching the glob |
| Compose directory | `--scope /opt/myproject` | Services from that docker-compose project |

All commands (`scan`, `deps`, `issues`) respect `--scope`.

| Source | What It Finds | How |
|--------|--------------|-----|
| **Docker** | Containers, ports, health, networks, env vars | Docker API socket |
| **Systemd** | Services, states, PIDs | `systemctl` |
| **TCP Ports** | All listening ports with owning PIDs | `/proc/net/tcp` + `/proc/net/tcp6` |
| **Processes** | Bare processes with port correlation | `/proc/*/cmdline` + `/proc/*/fd` |

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

15 built-in rules, zero false positives, deterministic (no LLM required):

| Category | Rules |
|----------|-------|
| **Network** | `port-conflict`, `port-unreachable`, `port-exposed-wildcard`, `connection-refused` |
| **Docker** | `container-restart-loop`, `container-unhealthy`, `container-oom-killed`, `container-orphan` |
| **Systemd** | `service-failed`, `service-activating-stuck` |
| **Dependencies** | `dependency-down`, `env-port-mismatch`, `circular-dependency` |
| **Resources** | `disk-pressure`, `memory-oom-risk` |

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

- [ ] `nervmap watch` — live monitoring daemon
- [ ] `nervmap serve` — REST API + WebSocket
- [ ] Web dashboard (Cytoscape.js graph)
- [ ] Plugin system (subprocess JSON protocol)
- [ ] Kubernetes support
- [ ] Community diagnostic rules (YAML format)

---

## License

MIT — Copyright 2026 AxonLabsDev

See [LICENSE](LICENSE) for details.
