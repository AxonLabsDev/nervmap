"""Config file parsers — .env, Dockerfile, nginx.conf, docker-compose."""

from __future__ import annotations

import re
import logging
from pathlib import Path

import yaml

logger = logging.getLogger("nervmap.source.config")


def parse_env_file(filepath: str) -> dict[str, str]:
    """Parse a .env file into key=value pairs."""
    result: dict[str, str] = {}
    try:
        with open(filepath, "r", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip()
                # Remove surrounding quotes
                if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                    value = value[1:-1]
                result[key] = value
    except FileNotFoundError:
        pass
    except Exception:
        logger.debug("Cannot parse env file %s", filepath, exc_info=True)
    return result


def parse_dockerfile(filepath: str) -> dict:
    """Parse Dockerfile directives into structured dict."""
    result = {
        "from_image": None,
        "workdir": None,
        "copy_sources": [],
        "add_sources": [],
        "expose": [],
        "cmd": None,
        "entrypoint": None,
        "has_healthcheck": False,
    }
    try:
        with open(filepath, "r", errors="replace") as f:
            for line in f:
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue

                upper = stripped.upper()

                if upper.startswith("FROM "):
                    result["from_image"] = stripped[5:].strip().split(" AS ")[0].split(" as ")[0].strip()

                elif upper.startswith("WORKDIR "):
                    result["workdir"] = stripped[8:].strip()

                elif upper.startswith("COPY "):
                    parts = stripped[5:].strip().split()
                    # COPY --from=... is multi-stage, skip
                    if parts and not parts[0].startswith("--"):
                        for p in parts[:-1]:  # All but last (dest)
                            if not p.startswith("--"):
                                result["copy_sources"].append(p)

                elif upper.startswith("ADD "):
                    parts = stripped[4:].strip().split()
                    if parts:
                        for p in parts[:-1]:
                            if not p.startswith("--"):
                                result["add_sources"].append(p)

                elif upper.startswith("EXPOSE "):
                    for token in stripped[7:].strip().split():
                        port_str = token.split("/")[0]
                        try:
                            result["expose"].append(int(port_str))
                        except ValueError:
                            pass

                elif upper.startswith("CMD "):
                    result["cmd"] = stripped[4:].strip()

                elif upper.startswith("ENTRYPOINT "):
                    result["entrypoint"] = stripped[11:].strip()

                elif upper.startswith("HEALTHCHECK "):
                    result["has_healthcheck"] = True

    except FileNotFoundError:
        pass
    except Exception:
        logger.debug("Cannot parse Dockerfile %s", filepath, exc_info=True)
    return result


def parse_nginx_conf(filepath: str) -> dict:
    """Parse nginx.conf for upstream, proxy_pass, listen directives."""
    result = {
        "upstreams": [],
        "listen_ports": [],
        "proxy_pass": [],
    }
    try:
        with open(filepath, "r", errors="replace") as f:
            text = f.read()

        # upstream blocks
        for m in re.finditer(r"upstream\s+(\w+)\s*\{", text):
            result["upstreams"].append(m.group(1))

        # listen directives
        for m in re.finditer(r"listen\s+(\d+)", text):
            try:
                result["listen_ports"].append(int(m.group(1)))
            except ValueError:
                pass

        # proxy_pass directives
        for m in re.finditer(r"proxy_pass\s+(https?://[^;]+)", text):
            result["proxy_pass"].append(m.group(1).strip())

    except FileNotFoundError:
        pass
    except Exception:
        logger.debug("Cannot parse nginx conf %s", filepath, exc_info=True)
    return result


def parse_compose_build_context(filepath: str) -> dict[str, str]:
    """Extract build.context from docker-compose.yml.

    Returns: {service_name: context_path}
    """
    result: dict[str, str] = {}
    try:
        with open(filepath, "r") as f:
            compose = yaml.safe_load(f) or {}
    except Exception:
        logger.debug("Cannot parse compose %s", filepath, exc_info=True)
        return result

    services = compose.get("services", {})
    if not isinstance(services, dict):
        return result

    for svc_name, svc_def in services.items():
        if not isinstance(svc_def, dict):
            continue
        build = svc_def.get("build")
        if build is None:
            continue
        if isinstance(build, str):
            result[svc_name] = build
        elif isinstance(build, dict):
            ctx = build.get("context")
            if ctx:
                result[svc_name] = ctx

    return result
