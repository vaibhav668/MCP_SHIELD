import os
from pathlib import Path

# pytest imports this file before any test module. Unit tests must run offline and never call the LLM judge,
# so they use tests/policy_test.yaml instead of the real shield/policy.yaml.
os.environ["SHIELD_POLICY"] = str(Path(__file__).parent / "policy_test.yaml")

# Tests write to their own audit database, so they never wipe the real one the dashboard shows.
os.environ["SHIELD_AUDIT_DB"] = str(Path(__file__).parent.parent / "logs" / "test_audit.db")
