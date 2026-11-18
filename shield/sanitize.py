import re

from shield.detectors import RESULT_RULES, SECRET_RULES

REDACTED = "[REDACTED]"
REMOVED = "[removed by MCP Shield: possible injected instruction]"


def redact(text):
    """Replace every secret in a string. Returns (clean_text, how_many_replacements)."""
    count = 0
    for pattern, weight, reason in SECRET_RULES:
        text, n = re.subn(pattern, REDACTED, text, flags=re.IGNORECASE)
        count += n
    return text, count


def sanitize_arguments(value):
    """Redact secrets anywhere inside tool arguments (strings, dicts, lists)."""
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, dict):
        clean, total = {}, 0
        for key, item in value.items():
            clean[key], n = sanitize_arguments(item)
            total += n
        return clean, total
    if isinstance(value, list):
        clean, total = [], 0
        for item in value:
            new_item, n = sanitize_arguments(item)
            clean.append(new_item)
            total += n
        return clean, total
    return value, 0


def sanitize_result(text):
    """Remove every sentence that looks like an injected instruction. Returns (clean_text, how_many_removed)."""
    removed = 0
    parts = []
    for sentence in re.split(r"(?<=[.!?])\s+|\n\s*\n", text):
        if any(re.search(p, sentence, re.IGNORECASE | re.MULTILINE) for p, w, r in RESULT_RULES):
            parts.append(REMOVED)
            removed += 1
        else:
            parts.append(sentence)
    return "\n".join(parts), removed
