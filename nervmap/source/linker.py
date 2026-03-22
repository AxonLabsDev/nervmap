"""CodeLinker — link Docker containers to their source code directories."""

from __future__ import annotations

import os
import logging

from nervmap.models import Service
from nervmap.source.models import CodeProject
from nervmap.source.parsers.config_parser import parse_compose_build_context

logger = logging.getLogger("nervmap.source.linker")


class CodeLinker:
    """Link Docker containers to source code projects.

    4 strategies with confidence scores:
    - docker-compose build.context -> 100%
    - Docker label working_dir -> 100%
    - Dockerfile COPY/ADD directives -> 85%
    - Proximity heuristic (Dockerfile + source in same dir) -> 60%
    """

    def link(self, services: list[Service], projects: list[CodeProject]) -> list[dict]:
        """Link services to projects. Returns list of link dicts."""
        links: list[dict] = []
        linked_pairs: set[tuple[str, str]] = set()  # (svc_id, project_path)

        for svc in services:
            if svc.type != "docker":
                continue

            labels = svc.metadata.get("labels", {})

            for proj in projects:
                best_confidence = 0.0
                strategy = ""

                # Strategy 1: docker-compose build.context (100%)
                workdir = labels.get("com.docker.compose.project.working_dir", "")
                compose_service = labels.get("com.docker.compose.service", "")
                if workdir and compose_service:
                    for compose_name in ("docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"):
                        compose_path = os.path.join(workdir, compose_name)
                        if os.path.isfile(compose_path):
                            contexts = parse_compose_build_context(compose_path)
                            ctx = contexts.get(compose_service, "")
                            if ctx:
                                # Resolve context path relative to compose dir
                                resolved = os.path.normpath(os.path.join(workdir, ctx))
                                if os.path.normpath(proj.path) == resolved:
                                    best_confidence = 1.0
                                    strategy = "build-context"
                            break

                # Strategy 2: Docker label working_dir matches project path (100%)
                if best_confidence < 1.0:
                    label_workdir = labels.get("com.docker.compose.project.working_dir", "")
                    if label_workdir and os.path.normpath(label_workdir) == os.path.normpath(proj.path):
                        best_confidence = 1.0
                        strategy = "working-dir-label"

                # Strategy 3: Dockerfile COPY/ADD sources (85%)
                if best_confidence < 0.85:
                    dockerfile_path = os.path.join(proj.path, "Dockerfile")
                    if os.path.isfile(dockerfile_path):
                        from nervmap.source.parsers.config_parser import parse_dockerfile
                        df = parse_dockerfile(dockerfile_path)
                        copies = df.get("copy_sources", []) + df.get("add_sources", [])
                        # If Dockerfile copies from the project dir, good signal
                        if copies and any(c == "." or c.startswith("./") for c in copies):
                            # Check if container name relates to project name
                            if proj.name.lower() in svc.name.lower() or svc.name.lower() in proj.name.lower():
                                best_confidence = 0.85
                                strategy = "dockerfile-copy"

                # Strategy 4: Proximity heuristic (60%)
                if best_confidence < 0.6:
                    dockerfile_in_dir = os.path.isfile(os.path.join(proj.path, "Dockerfile"))
                    name_match = (
                        proj.name.lower() in svc.name.lower()
                        or svc.name.lower() in proj.name.lower()
                    )
                    if dockerfile_in_dir and name_match:
                        best_confidence = 0.6
                        strategy = "proximity"

                if best_confidence > 0:
                    pair = (svc.id, proj.path)
                    if pair not in linked_pairs:
                        linked_pairs.add(pair)
                        links.append({
                            "service": svc.id,
                            "project": proj.path,
                            "confidence": best_confidence,
                            "strategy": strategy,
                        })
                        # Update project linked_services
                        if svc.id not in proj.linked_services:
                            proj.linked_services.append(svc.id)

        return links
