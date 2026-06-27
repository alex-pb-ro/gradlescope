"""Ensure bundled runbooks exist and cover every runbook referenced by a rule."""
from gradlescope.analysis.rule import all_rules
from gradlescope.dashboard.runbooks import load_runbooks


def test_default_runbooks_load():
    rb = load_runbooks()
    # A representative sample of the bundled runbooks.
    for rid in [
        "configuration-cache",
        "build-cache",
        "remote-build-cache",
        "convention-plugins",
        "untangle-dependency-graph",
        "bazel-migration",
        "affected-builds",
    ]:
        assert rid in rb, f"missing runbook: {rid}"
        assert rb[rid]["html"]


def test_every_rule_runbook_reference_resolves():
    rb = load_runbooks()
    for rule in all_rules():
        if rule.runbook:
            assert rule.runbook in rb, f"rule {rule.id} references missing runbook {rule.runbook}"
