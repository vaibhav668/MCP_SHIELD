import json
from collections import Counter
from pathlib import Path

CASES = json.loads(Path("evals/dataset.json").read_text())
KINDS = {"description", "arguments", "result"}


def test_dataset_has_200_cases_with_unique_ids():
    assert len(CASES) == 200
    assert len({c["id"] for c in CASES}) == 200


def test_every_case_is_well_formed():
    for c in CASES:
        assert c["kind"] in KINDS
        assert c["label"] in ("attack", "benign")
        assert c["difficulty"] in ("easy", "hard", "normal", "lookalike")
        if c["kind"] == "arguments":
            assert isinstance(c["content"], dict)
        else:
            assert isinstance(c["content"], str) and c["content"]


def test_attack_and_benign_cases_match_their_difficulty():
    for c in CASES:
        allowed = ("easy", "hard") if c["label"] == "attack" else ("normal", "lookalike")
        assert c["difficulty"] in allowed


def test_each_surface_has_both_attacks_and_benign_cases():
    counts = Counter((c["kind"], c["label"]) for c in CASES)
    for kind in KINDS:
        assert counts[(kind, "attack")] >= 30 and counts[(kind, "benign")] >= 30


def test_dataset_contains_hard_attacks_and_lookalikes():
    counts = Counter(c["difficulty"] for c in CASES)
    assert counts["hard"] >= 50 and counts["lookalike"] >= 25
