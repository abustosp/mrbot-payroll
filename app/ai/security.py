"""Heuristics that flag likely prompt injection in agreement documents.

These checks do not sanitize or rewrite the document. They only add review
warnings; the actual protection is the system prompt plus strict structured
output and mandatory human approval.
"""

from __future__ import annotations

import re

_INJECTION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "instruction_override",
        re.compile(
            r"(?:ignore|disregard|forget)\s+(?:all\s+)?(?:the\s+)?"
            r"(?:previous|above|prior)\s+(?:instructions|directions|rules)",
            re.IGNORECASE,
        ),
    ),
    (
        "instruction_override_es",
        re.compile(
            r"(?:ignor[áa]|olvid[áa]|descart[áa])\s+(?:todas?\s+)?"
            r"(?:las\s+)?(?:instrucciones|indicaciones|reglas)\s+"
            r"(?:anteriores|previas|de\s+arriba)",
            re.IGNORECASE,
        ),
    ),
    (
        "system_prompt",
        re.compile(r"\bsystem\s+prompt\b|\bprompt\s+del\s+sistema\b", re.IGNORECASE),
    ),
    (
        "role_override",
        re.compile(
            r"\byou\s+are\s+now\b|\bact[úu]a\s+como\b|\bdesde\s+ahora\s+sos\b",
            re.IGNORECASE,
        ),
    ),
    (
        "approval_bypass",
        re.compile(
            r"(?:aprob\w*|aprueb\w*|public\w*|valid\w*)\s+"
            r"(?:autom[áa]ticamente\s+)?"
            r"(?:la|esta|todas\s+las)\s+(?:f[oó]rmula|regla|propuesta)s?",
            re.IGNORECASE,
        ),
    ),
    (
        "skip_review",
        re.compile(
            r"(?:no|sin)\s+(?:requiere|necesita|hace\s+falta)\s+"
            r"(?:aprobaci[oó]n|revisi[oó]n)\s+humana",
            re.IGNORECASE,
        ),
    ),
    (
        "code_execution",
        re.compile(
            r"\b(?:ejecut[áa]|run|execute)\s+(?:el\s+)?(?:siguiente\s+)?"
            r"(?:c[oó]digo|code|script)\b",
            re.IGNORECASE,
        ),
    ),
)


def detect_prompt_injection(text: str) -> list[str]:
    """Return human-readable warnings for suspicious embedded instructions."""

    if not isinstance(text, str) or not text:
        return []
    warnings: list[str] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        for label, pattern in _INJECTION_PATTERNS:
            if pattern.search(line):
                snippet = " ".join(line.strip().split())
                if len(snippet) > 160:
                    snippet = f"{snippet[:157]}..."
                warnings.append(
                    f"Possible prompt injection ({label}) at line {line_number}: "
                    f"{snippet!r}. Treated as untrusted document data."
                )
                break
    return warnings
