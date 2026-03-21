"""Rule runner — evaluate all diagnostic rules against system state."""

from __future__ import annotations

from nervmap.models import SystemState, Issue


class RuleRunner:
    """Evaluate all registered rules and return Issues."""

    def evaluate(self, state: SystemState, cfg: dict) -> list[Issue]:
        issues: list[Issue] = []

        from nervmap.diagnostics.rules import get_all_rules
        for rule_fn in get_all_rules():
            try:
                result = rule_fn(state, cfg)
                if result:
                    issues.extend(result)
            except Exception:
                continue

        # Sort: critical first, then warning, then info
        severity_order = {"critical": 0, "warning": 1, "info": 2}
        issues.sort(key=lambda i: severity_order.get(i.severity, 3))

        return issues
