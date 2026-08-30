# SPDX-License-Identifier: Apache-2.0
"""Tests for the detectors.

Two halves, and the second matters more. The first checks that a lying test is
caught. The second checks that an honest test is left alone -- because a tool
that flags good tests gets switched off, and a switched-off tool finds nothing.
Every negative case below is a real pattern that a naive implementation of
these rules would flag.
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from suiteaudit.detectors import analyse_source  # noqa: E402


def rules(source: str) -> list[str]:
    findings, _ = analyse_source(source, "t.py")
    return sorted(f.rule for f in findings)


def count_tests(source: str) -> int:
    _, n = analyse_source(source, "t.py")
    return n


class TestCollection(unittest.TestCase):
    def test_counts_module_level_and_class_tests(self):
        src = """
def test_a():
    assert compute() == 1

class TestThing:
    def test_b(self):
        assert compute() == 2
    def helper(self):
        pass
"""
        self.assertEqual(count_tests(src), 2)

    def test_non_test_functions_are_ignored(self):
        src = """
def helper():
    pass

def make_fixture():
    return 1
"""
        self.assertEqual(count_tests(src), 0)
        self.assertEqual(rules(src), [])


class TestEmptyTest(unittest.TestCase):
    def test_pass_only_body_is_caught(self):
        self.assertEqual(rules("def test_x():\n    pass\n"), ["empty-test"])

    def test_docstring_only_body_is_caught(self):
        self.assertEqual(rules('def test_x():\n    """later."""\n'), ["empty-test"])

    def test_empty_test_reports_once_not_also_no_assertion(self):
        """An empty test is already the strongest verdict; restating it as
        'no assertion' would double-count the same problem."""
        self.assertEqual(rules("def test_x():\n    pass\n"), ["empty-test"])


class TestTautology(unittest.TestCase):
    def test_assert_true_literal(self):
        self.assertIn("tautology", rules("def test_x():\n    assert True\n"))

    def test_constant_comparison(self):
        self.assertIn("tautology", rules("def test_x():\n    assert 1 == 1\n"))

    def test_same_expression_both_sides(self):
        src = "def test_x():\n    got = compute()\n    assert got == got\n"
        self.assertIn("tautology", rules(src))

    def test_unittest_assert_equal_with_two_constants(self):
        src = ("class T:\n    def test_x(self):\n"
               "        self.assertEqual(2, 2)\n")
        self.assertIn("tautology", rules(src))

    def test_unittest_assert_equal_same_expression(self):
        src = ("class T:\n    def test_x(self):\n"
               "        got = compute()\n"
               "        self.assertEqual(got, got)\n")
        self.assertIn("tautology", rules(src))

    def test_assert_true_on_constant_expression(self):
        src = "def test_x():\n    assert (2 + 2) == 4\n"
        self.assertIn("tautology", rules(src))

    # --- must NOT fire -------------------------------------------------
    def test_real_comparison_is_not_a_tautology(self):
        src = "def test_x():\n    assert compute() == 4\n"
        self.assertNotIn("tautology", rules(src))

    def test_comparing_two_different_calls_is_not_a_tautology(self):
        src = "def test_x():\n    assert compute(1) == compute(2)\n"
        self.assertNotIn("tautology", rules(src))

    def test_expected_constant_against_a_real_value_is_fine(self):
        """The overwhelmingly common honest pattern: real value, constant
        expectation. Flagging this would make the tool useless."""
        src = ("class T:\n    def test_x(self):\n"
               "        self.assertEqual(compute(), 42)\n")
        self.assertNotIn("tautology", rules(src))


class TestMockOnly(unittest.TestCase):
    def test_asserting_only_that_a_mock_was_called(self):
        src = """
def test_x():
    client = MagicMock()
    client.send("hi")
    client.send.assert_called_once_with("hi")
"""
        self.assertIn("mock-only", rules(src))

    def test_asserting_on_a_mocks_return_value_it_configured(self):
        src = """
def test_x():
    svc = Mock()
    svc.total.return_value = 7
    assert svc.total() == 7
"""
        self.assertIn("mock-only", rules(src))

    # --- must NOT fire -------------------------------------------------
    def test_mock_used_as_a_dependency_with_a_real_assertion(self):
        """The correct use of a mock: inject it, then assert on what the
        system under test produced. This must never be flagged."""
        src = """
def test_x():
    clock = Mock()
    clock.now.return_value = 0
    result = schedule(clock)
    assert result.due_at == 0
"""
        self.assertNotIn("mock-only", rules(src))

    def test_mixed_assertions_are_not_flagged(self):
        src = """
def test_x():
    client = MagicMock()
    out = handler(client)
    client.send.assert_called_once()
    assert out.status == 200
"""
        self.assertNotIn("mock-only", rules(src))

    def test_no_mocks_means_no_finding(self):
        src = "def test_x():\n    assert compute() == 1\n"
        self.assertNotIn("mock-only", rules(src))

    def test_a_variable_that_merely_looks_like_a_mock_is_not_one(self):
        """Matching on the constructor, not the name: `mock_total` holding a
        real integer is not a test double."""
        src = """
def test_x():
    mock_total = 5
    assert compute() == mock_total
"""
        self.assertNotIn("mock-only", rules(src))


class TestNoAssertion(unittest.TestCase):
    def test_body_that_only_calls_the_system(self):
        src = "def test_x():\n    compute(1)\n    compute(2)\n"
        self.assertIn("no-assertion", rules(src))

    # --- must NOT fire -------------------------------------------------
    def test_pytest_raises_counts_as_an_assertion(self):
        src = """
def test_x():
    with pytest.raises(ValueError):
        compute(-1)
"""
        self.assertNotIn("no-assertion", rules(src))

    def test_unittest_assert_raises_counts(self):
        src = """
class T:
    def test_x(self):
        with self.assertRaises(ValueError):
            compute(-1)
"""
        self.assertNotIn("no-assertion", rules(src))

    def test_mock_call_assertion_counts_as_an_assertion(self):
        """It is a weak assertion, and mock-only will say so separately, but
        it is not *absent*. Reporting both would be double-counting."""
        src = """
def test_x():
    client = MagicMock()
    handler(client)
    client.send.assert_called_once()
"""
        self.assertNotIn("no-assertion", rules(src))


class TestSeverity(unittest.TestCase):
    def test_empty_and_tautology_are_high(self):
        findings, _ = analyse_source("def test_x():\n    assert True\n", "t.py")
        self.assertTrue(all(f.severity == "high" for f in findings))

    def test_no_assertion_is_medium_because_it_still_catches_crashes(self):
        findings, _ = analyse_source("def test_x():\n    compute()\n", "t.py")
        self.assertEqual([f.severity for f in findings], ["medium"])


class TestRobustness(unittest.TestCase):
    def test_async_tests_are_analysed(self):
        src = "async def test_x():\n    pass\n"
        self.assertEqual(rules(src), ["empty-test"])

    def test_syntax_error_raises_rather_than_silently_passing(self):
        """A file the tool cannot parse must not be reported as clean."""
        with self.assertRaises(SyntaxError):
            analyse_source("def test_x(:\n", "t.py")

    def test_empty_file_is_clean_and_counts_no_tests(self):
        findings, n = analyse_source("", "t.py")
        self.assertEqual((findings, n), ([], 0))


if __name__ == "__main__":
    unittest.main(verbosity=2)


class TestAssertionsFromOtherLibraries(unittest.TestCase):
    """Regression guard for the first false positives this tool ever produced.

    The initial version knew only unittest's assertion names, so numpy's entire
    `assert_*` family read as "no assertion at all" and three numeric codebases
    were reported as untested. Any callable named assert-something counts.
    """

    def test_numpy_assert_allclose_counts(self):
        src = """
def test_x():
    got = rotate(a, b, 360)
    np.testing.assert_allclose(got, expected, atol=1e-9)
"""
        self.assertNotIn("no-assertion", rules(src))

    def test_numpy_assert_array_equal_counts(self):
        src = """
def test_x():
    np.testing.assert_array_equal(compute(), expected)
"""
        self.assertNotIn("no-assertion", rules(src))

    def test_pandas_assert_frame_equal_counts(self):
        src = """
def test_x():
    pd.testing.assert_frame_equal(build(), expected)
"""
        self.assertNotIn("no-assertion", rules(src))

    def test_a_bare_call_is_still_flagged(self):
        """Widening must not swallow the rule: a call that is not an assertion
        still leaves the test with nothing to fail on."""
        src = "def test_x():\n    compute(1)\n"
        self.assertIn("no-assertion", rules(src))
