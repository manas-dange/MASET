"""Tests for MA-SET Lab 2.0: Failure Classifier Subsystem."""

import pytest

from ma_set.evaluation.failure_classifier import FailureClassifier, FailureType, FailureReport


def test_classify_security_violation():
    classifier = FailureClassifier()
    reports = classifier.classify(
        functional_passed=False,
        constraint_violations=["Protected file 'demo_target/legacy_billing.py' was modified"],
    )
    assert len(reports) == 1
    assert reports[0].failure_type == FailureType.F10_SECURITY_VIOLATION


def test_classify_tool_loop():
    classifier = FailureClassifier()
    reports = classifier.classify(
        functional_passed=False,
        commands=[
            {"command": "pytest demo_target/tests/"},
            {"command": "pytest demo_target/tests/"},
            {"command": "pytest demo_target/tests/"},
        ],
    )
    assert len(reports) == 1
    assert reports[0].failure_type == FailureType.F05_TOOL_LOOP


def test_classify_regression():
    classifier = FailureClassifier()
    reports = classifier.classify(
        functional_passed=True,
        regressions=["FAILED test_existing_feature.py"],
    )
    assert len(reports) == 1
    assert reports[0].failure_type == FailureType.F09_REGRESSION


def test_classify_bad_recovery():
    classifier = FailureClassifier()
    reports = classifier.classify(
        functional_passed=False,
        recovery_attempts=2,
    )
    assert len(reports) == 1
    assert reports[0].failure_type == FailureType.F13_BAD_RECOVERY


def test_classify_premature_termination():
    classifier = FailureClassifier()
    reports = classifier.classify(
        functional_passed=False,
        files_modified=[],
    )
    assert len(reports) == 1
    assert reports[0].failure_type == FailureType.F08_PREMATURE_TERMINATION
