from shield import detectors, graph
from shield.policy import decide_action, load_policy


def test_policy_file_has_the_settings():
    policy = load_policy()
    assert policy["low"] < policy["high"]
    assert "company.com" in policy["trusted_domains"]


def test_allow_stays_allow():
    assert decide_action(load_policy(), "result", "ALLOW") == "ALLOW"


def test_block_action_depends_on_what_was_inspected():
    policy = load_policy()
    assert decide_action(policy, "description", "BLOCK") == "BLOCK"
    assert decide_action(policy, "arguments", "BLOCK") == "SANITIZE"
    assert decide_action(policy, "result", "BLOCK") == "SANITIZE"


def test_shipped_policy_sends_everything_that_is_not_an_obvious_attack_to_the_judge():
    from shield.policy import POLICY_FILE
    shipped = load_policy(POLICY_FILE)  # the real file, not the test policy
    assert shipped["low"] == 0.0 and shipped["high"] == 0.8


def test_unsure_asks_a_human():
    assert decide_action(load_policy(), "arguments", "UNSURE") == "ASK_HUMAN"


def test_detectors_and_graph_use_the_policy_values():
    policy = load_policy()
    assert graph.LOW == policy["low"] and graph.HIGH == policy["high"]
    assert list(detectors.TRUSTED_DOMAINS) == policy["trusted_domains"]
