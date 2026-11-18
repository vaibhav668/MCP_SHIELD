import json
import re
from shield.policy import load_policy


DESCRIPTION_RULES = [
    (r"<\s*(important|system|instructions?|secret)\b", 0.5, "hidden instruction tag"),
    (r"\b(do not|don't|never)\s+(mention|tell|reveal|inform|disclose)", 0.5, "asks to hide something from the user"),
    (r"\b(read|open|fetch|access)\s+(the\s+)?(file|contents?)\b", 0.4, "tells the agent to read a file"),
    (r"\b(using|with|via)\s+the\s+\w+\s+tool\b", 0.3, "tells the agent to use another tool"),
    (r"credentials|\.ssh|id_rsa|\.env\b|api[_ ]?key|password|secret", 0.3, "mentions sensitive data"),
    (r"before (using|calling|running) this tool", 0.3, "forces an action before the tool runs"),
    (r"pass\s+.{0,40}\s+(in|as|to)\s+(the\s+)?['\"`]?\w+['\"`]?\s+(parameter|argument)", 0.3, "asks to pass data in a parameter"),
]

RESULT_RULES = [
    (r"ignore\s+(all\s+|any\s+)?(previous|prior|above)\s+instructions?", 0.6, "classic override phrase"),
    (r"\b(do not|don't|never)\s+(mention|tell|reveal|inform|disclose)", 0.4, "asks to hide something from the user"),
    (r"\bno need to (ask|tell|inform|notify|mention)", 0.4, "tells the agent to skip asking the user"),
    (r"\b(pre-?approved|already approved|authorized by)", 0.3, "claims approval"),
    (r"\b(read|open|fetch|access)\s+(the\s+)?(file|contents?)\b", 0.3, "tells the agent to read a file"),
    (r"\b(using|with|via)\s+the\s+\w+\s+tool\b", 0.3, "tells the agent to use a tool"),
    (r"\b(email|send|forward|post|upload)\s+(its|the|all|your)?\s*(full\s+)?(contents?|data|file|credentials)", 0.4, "tells the agent to send data out"),
    (r"^\s*(system|assistant)\s*:", 0.3, "fake role marker"),
]

SECRET_RULES = [
    (r"\bsk-[A-Za-z0-9\-_]{10,}", 0.8, "API key (sk-...)"),
    (r"\bAKIA[0-9A-Z]{16}\b", 0.8, "AWS access key"),
    (r"\bghp_[A-Za-z0-9]{20,}", 0.8, "GitHub token"),
    (r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.", 0.8, "JWT token"),
    (r"(api[_ -]?key|secret|token|password|passwd)[\"']?\s*[:=]\s*\S+", 0.7, "credential assignment"),
    (r"BEGIN (RSA |OPENSSH |EC )?PRIVATE KEY", 0.9, "private key"),
    (r"\b\d{3}-\d{2}-\d{4}\b", 0.6, "SSN-like number"),
    (r"\b(?:\d[ -]?){13,16}\b", 0.5, "card-like number"),
]

TRUSTED_DOMAINS = load_policy()["trusted_domains"]


def run_rules(text, rules):
    """Add up the weights of every rule that matches. Returns (score, reasons)."""
    score, reasons = 0.0, []
    for pattern, weight, reason in rules:
        if re.search(pattern, text, re.IGNORECASE | re.MULTILINE):
            score += weight
            reasons.append(reason)
    return min(score, 1.0), reasons

def scan_description(text):
    """Check a tool description for hidden instructions (tool poisoning)."""
    return run_rules(text or "", DESCRIPTION_RULES)


def scan_result(text):
    """Check a tool result for injected instructions (indirect prompt injection)."""
    return run_rules(text or "", RESULT_RULES)


def scan_arguments(arguments):
    """Check outgoing tool arguments for secrets, PII and outside email addresses (exfiltration)."""
    text = json.dumps(arguments or {})
    score, reasons = run_rules(text, SECRET_RULES)
    for domain in re.findall(r"[\w.+-]+@([\w-]+\.[\w.-]+)", text):
        if domain.lower() not in TRUSTED_DOMAINS:
            score = min(score + 0.4, 1.0)
            reasons.append(f"email to outside domain: {domain}")
    return score, reasons 



