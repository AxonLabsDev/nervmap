"""Rule runner — evaluate all diagnostic rules against system state."""

from __future__ import annotations

import logging
import re

from nervmap.models import SystemState, Issue
from nervmap.config import get_ignored_service_patterns

logger = logging.getLogger("nervmap.engine")


class RuleRunner:
    """Evaluate all registered rules and return Issues."""

    def _filter_ignored_services(self, state: SystemState, cfg: dict) -> SystemState:
        """Remove services matching ignore.services patterns from state."""
        patterns = get_ignored_service_patterns(cfg)
        if not patterns:
            return state

        compiled = []
        for p in patterns:
            try:
                compiled.append(re.compile(p, re.IGNORECASE))
            except re.error:
                logger.debug("Invalid ignore pattern: %s", p)

        if not compiled:
            return state

        filtered = []
        for svc in state.services:
            if any(rx.search(svc.name) or rx.search(svc.id) for rx in compiled):
                logger.debug("Ignoring service %s (matched ignore pattern)", svc.id)
                continue
            filtered.append(svc)

        # Don't mutate original state — deep copy to avoid shared references
        import copy
        new_state = copy.deepcopy(state)
        new_state.services = filtered
        return new_state

    def evaluate(self, state: SystemState, cfg: dict) -> list[Issue]:
        # Filter out ignored services before running diagnostics
        state = self._filter_ignored_services(state, cfg)

        issues: list[Issue] = []

        from nervmap.diagnostics.rules import get_all_rules
        for rule_fn in get_all_rules():
            try:
                result = rule_fn(state, cfg)
                if result:
                    issues.extend(result)
            except Exception:
                logger.debug("Rule %s failed", rule_fn.__name__, exc_info=True)
                continue

        # Sort: critical first, then warning, then info
        severity_order = {"critical": 0, "warning": 1, "info": 2}
        issues.sort(key=lambda i: severity_order.get(i.severity, 3))

        return issues
