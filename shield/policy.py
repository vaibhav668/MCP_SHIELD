import os
from pathlib import Path

import yaml

POLICY_FILE = Path(__file__).parent / "policy.yaml"


def load_policy(path=None):
    """Read the policy file into a plain dict. The SHIELD_POLICY environment variable can point to another file (the tests use this)."""
    with open(path or os.getenv("SHIELD_POLICY") or POLICY_FILE) as f:
        return yaml.safe_load(f)


def decide_action(policy, what, verdict):
    """Turn the graph's verdict into an action: ALLOW, BLOCK, SANITIZE or ASK_HUMAN."""
    if verdict == "ALLOW":
        return "ALLOW"
    if verdict == "UNSURE":
        return policy["on_unsure"]
    return policy["on_block"][what]
