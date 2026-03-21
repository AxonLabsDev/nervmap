"""Utility functions for NervMap."""

from __future__ import annotations

import re

# Keys whose values should always be redacted
_SENSITIVE_KEY_PATTERNS = re.compile(
    r"(PASSWORD|SECRET|KEY|TOKEN|CREDENTIAL)",
    re.IGNORECASE,
)

# URL with embedded credentials: scheme://user:pass@host
_CREDENTIAL_URL_PATTERN = re.compile(
    r"://[^/@]*:[^/@]+@",
)

REDACTED = "***REDACTED***"


def redact_env(env: dict[str, str]) -> dict[str, str]:
    """Return a copy of env with sensitive values replaced by REDACTED.

    Redacts:
    - Any key containing PASSWORD, SECRET, KEY, TOKEN, or CREDENTIAL
    - Any value containing a URL with embedded credentials (://user:pass@)
    """
    if not env:
        return env

    result: dict[str, str] = {}
    for k, v in env.items():
        if _SENSITIVE_KEY_PATTERNS.search(k):
            result[k] = REDACTED
        elif _CREDENTIAL_URL_PATTERN.search(str(v)):
            result[k] = REDACTED
        else:
            result[k] = v
    return result
