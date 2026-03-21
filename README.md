# NervMap

> `docker ps` shows containers. **NervMap shows why your app is down.**

Infrastructure cartography CLI that automatically discovers services (Docker + systemd + bare processes), maps dependencies between them, and diagnoses problems with actionable fix suggestions.

**Zero config. Single command. Instant results.**

---

## Install

```bash
pip install nervmap
```

Or install in isolation:

```bash
pipx install nervmap
```

## Quick Start

```bash
# Full infrastructure scan
nervmap

# JSON output for scripting
nervmap scan --json

# Only show issues
nervmap scan --quiet

# Dependency graph
nervmap deps

# Only critical issues
nervmap issues --critical

# Export as Graphviz DOT
nervmap deps --dot > infra.dot

# Export as Mermaid
nervmap deps --mermaid
```

## What It Does

### Discovery
- **Docker containers** via Docker API socket
- **Systemd services** via systemctl
- **TCP ports** via /proc/net/tcp
- **Bare processes** with port correlation via /proc

### Dependency Mapping
- Established TCP connections (ss/proc)
- Environment variable parsing (DATABASE_URL, REDIS_HOST, etc.)
- Docker network membership
- Confidence scoring (100% declared, 85% observed, 60% inferred)

### Diagnostics (15 built-in rules)

| Category | Rules |
|----------|-------|
| **Network** | port-conflict, port-unreachable, port-exposed-wildcard, connection-refused |
| **Docker** | container-restart-loop, container-unhealthy, container-oom-killed, container-orphan |
| **Systemd** | service-failed, service-activating-stuck |
| **Dependencies** | dependency-down, env-port-mismatch |
| **Resources** | disk-pressure, memory-oom-risk |

Every issue includes a **severity level**, **affected service**, and **suggested fix**.

## Configuration (Optional)

Create `.nervmap.yml` in your project or `~/.nervmap/config.yml`:

```yaml
scan:
  docker: true
  systemd: true
  ports: true

ignore:
  ports: [22]
  services: ["snap.*"]

timeouts:
  http: 5
  tcp: 3

hooks:
  on_issue: "~/.nervmap/hooks/notify.sh"
```

## Shell Hooks

NervMap can trigger scripts on events:

```bash
mkdir -p ~/.nervmap/hooks
cat > ~/.nervmap/hooks/on-issue-detected.sh << 'EOF'
#!/bin/bash
# Receives JSON on stdin
cat | jq '.issues[] | .message'
EOF
chmod +x ~/.nervmap/hooks/on-issue-detected.sh
```

## Requirements

- Linux (tested on Ubuntu 20.04+, Debian 11+)
- Python 3.10+
- Docker socket access (optional, for container discovery)
- Root or equivalent (optional, for /proc/*/environ reading)

## License

MIT -- Copyright 2026 AxonLabs
