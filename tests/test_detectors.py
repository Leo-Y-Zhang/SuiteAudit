# SPDX-License-Identifier: Apache-2.0
"""Tests for the detectors.

Two halves, and the second matters more. The first checks that a lying test is
caught. The second checks that an honest test is left alone -- because a tool
that flags good tests gets switched off, and a switched-off tool finds nothing.
Every negative case below is a real pattern that a naive implementation of
these rules would flag, and several of them were flagged by the first release
candidate of this tool when it was pointed at popular open-source suites.
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from suiteaudit.detectors import analyse_file, analyse_source  # noqa: E402


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

    def test_identity_of_a_name_with_itself(self):
        """`x is x` is true by the definition of `is`; no user code runs."""
        src = "def test_x():\n    got = compute()\n    assert got is got\n"
        self.assertIn("tautology", rules(src))

    def test_unittest_assert_equal_with_two_constants(self):
        src = ("class T(unittest.TestCase):\n    def test_x(self):\n"
               "        self.assertEqual(2, 2)\n")
        self.assertIn("tautology", rules(src))

    def test_unittest_assert_is_same_name(self):
        src = ("class T(unittest.TestCase):\n    def test_x(self):\n"
               "        got = compute()\n"
               "        self.assertIs(got, got)\n")
        self.assertIn("tautology", rules(src))

    def test_assert_true_on_constant_expression(self):
        src = "def test_x():\n    assert (2 + 2) == 4\n"
        self.assertIn("tautology", rules(src))

    def test_unittest_assert_true_on_a_constant(self):
        src = ("class T(unittest.TestCase):\n    def test_x(self):\n"
               "        self.assertTrue(1)\n")
        self.assertIn("tautology", rules(src))

    def test_only_tautologies_is_high_severity(self):
        """Every assertion is fixed, so the test cannot fail: that is FAIL."""
        src = "def test_x():\n    assert True\n    assert 1 == 1\n"
        findings, _ = analyse_source(src, "t.py")
        self.assertEqual([f.severity for f in findings], ["high", "high"])

    def test_dead_assertion_beside_a_real_one_is_low_severity(self):
        """The test CAN fail, through `compute()`. The `assert True` is dead
        weight, which is worth a note and not a failed gate. The release
        candidate failed a popular suite's gate over `assert e1 is e1` in a
        test that went on to make real assertions."""
        src = ("def test_x():\n    e1 = make()\n"
               "    assert e1 is e1\n    assert compute(e1) == 1\n")
        findings, _ = analyse_source(src, "t.py")
        self.assertEqual([(f.rule, f.severity) for f in findings],
                         [("tautology", "low")])
        self.assertIn("other assertions", findings[0].detail)

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
        src = ("class T(unittest.TestCase):\n    def test_x(self):\n"
               "        self.assertEqual(compute(), 42)\n")
        self.assertNotIn("tautology", rules(src))

    def test_equality_of_a_name_with_itself_is_user_code(self):
        """`x == x` calls `x.__eq__`, which is user code: float NaN is not
        equal to itself, and a project that generates `__eq__` tests exactly
        this reflexivity. The first release candidate flagged 26 such
        assertions in one popular suite."""
        src = "def test_x():\n    got = compute()\n    assert got == got\n"
        self.assertNotIn("tautology", rules(src))

    def test_assert_equal_of_a_name_with_itself_is_user_code(self):
        src = ("class T(unittest.TestCase):\n    def test_x(self):\n"
               "        got = compute()\n"
               "        self.assertEqual(got, got)\n")
        self.assertNotIn("tautology", rules(src))

    def test_equal_constructor_calls_test_the_eq_method(self):
        """`C(1) == C(1)` builds two objects and asks the class whether they
        are equal. That is the class's behaviour under test, not a tautology."""
        src = "def test_x():\n    assert C(1) == C(1)\n"
        self.assertNotIn("tautology", rules(src))

    def test_equal_hash_calls_test_the_hash_method(self):
        src = "def test_x():\n    assert hash(C(1)) == hash(C(1))\n"
        self.assertNotIn("tautology", rules(src))

    def test_equal_list_of_iterator_tests_iteration(self):
        src = "def test_x():\n    assert list(keys) == list(keys)\n"
        self.assertNotIn("tautology", rules(src))

    def test_loop_variable_compared_to_itself_is_user_code(self):
        src = ("def test_x():\n    for i in items:\n"
               "        assert i == i\n")
        self.assertNotIn("tautology", rules(src))

    def test_identity_of_two_calls_is_not_fixed(self):
        """`f(1) is f(1)` may well be two objects; whether it is one is
        exactly what a caching test checks."""
        src = "def test_x():\n    assert f(1) is f(1)\n"
        self.assertNotIn("tautology", rules(src))

    def test_identity_of_an_attribute_with_itself_may_run_a_property(self):
        src = "def test_x():\n    assert obj.value is obj.value\n"
        self.assertNotIn("tautology", rules(src))

    def test_identity_of_a_subscript_with_itself_runs_getitem(self):
        src = "def test_x():\n    assert xs[0] is xs[0]\n"
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

    def test_builtins_do_not_count_as_production_code(self):
        src = """
def test_x():
    svc = Mock()
    svc.items.return_value = [1, 2]
    assert len(svc.items()) == 2
"""
        self.assertIn("mock-only", rules(src))

    def test_decorators_are_not_production_code(self):
        """`@pytest.mark.parametrize` is a call, but not one that runs the
        system under test; the body is still nothing but a mock."""
        src = """
@pytest.mark.parametrize("n", [1, 2])
def test_x(n):
    svc = Mock()
    svc.run(n)
    svc.run.assert_called_once_with(n)
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

    def test_contract_test_that_calls_the_system_is_not_flagged(self):
        """The system under test IS called, with the mock injected; asserting
        that the collaborator was then used is a contract test. The first
        release candidate flagged this shape in a popular HTTP library because
        it only looked at the assertions, never at what else the body ran."""
        src = """
def test_x():
    sender = Mock()
    notify(sender, "hi")
    sender.send.assert_called_once_with("hi")
"""
        self.assertNotIn("mock-only", rules(src))

    def test_patched_collaborator_with_the_system_called_inside(self):
        src = """
def test_x():
    with patch("app.utils.proxy_bypass") as bypass:
        should_bypass_proxies("http://example.test", no_proxy=None)
    bypass.assert_called_once_with("example.test")
"""
        self.assertNotIn("mock-only", rules(src))

    def test_a_helper_on_self_may_run_production_code(self):
        """`self.run_pipeline()` is not an assertion helper, so production
        code may have run; the rule says nothing."""
        src = """
class T(unittest.TestCase):
    def test_x(self):
        sink = Mock()
        self.run_pipeline(sink)
        sink.write.assert_called()
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
class T(unittest.TestCase):
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


class TestSuppression(unittest.TestCase):
    """`# suiteaudit: ignore[rule]` sets a finding aside; it never deletes it."""

    def test_ignore_on_the_def_line_suppresses_that_rule(self):
        src = "def test_x():  # suiteaudit: ignore[tautology]\n    assert True\n"
        report = analyse_file(src, "t.py")
        self.assertEqual([f.rule for f in report.findings], [])
        self.assertEqual([f.rule for f in report.suppressed], ["tautology"])
        self.assertEqual(report.n_tests, 1)

    def test_ignore_on_the_flagged_line_suppresses_that_rule(self):
        src = "def test_x():\n    assert True  # suiteaudit: ignore[tautology]\n"
        report = analyse_file(src, "t.py")
        self.assertEqual([f.rule for f in report.findings], [])
        self.assertEqual([f.rule for f in report.suppressed], ["tautology"])

    def test_bare_ignore_suppresses_every_rule(self):
        src = "def test_x():  # suiteaudit: ignore\n    compute()\n"
        report = analyse_file(src, "t.py")
        self.assertEqual(report.findings, [])
        self.assertEqual([f.rule for f in report.suppressed], ["no-assertion"])

    def test_several_rules_in_one_comment(self):
        src = ("def test_x():  # suiteaudit: ignore[no-assertion, tautology]\n"
               "    assert True\n")
        report = analyse_file(src, "t.py")
        self.assertEqual(report.findings, [])
        self.assertEqual(len(report.suppressed), 1)

    # --- must NOT suppress ---------------------------------------------
    def test_ignore_for_a_different_rule_does_not_suppress(self):
        src = "def test_x():  # suiteaudit: ignore[mock-only]\n    assert True\n"
        report = analyse_file(src, "t.py")
        self.assertEqual([f.rule for f in report.findings], ["tautology"])
        self.assertEqual(report.suppressed, [])

    def test_marker_inside_a_string_is_not_a_comment(self):
        src = ('def test_x():\n    label = "# suiteaudit: ignore"\n'
               "    assert True\n")
        report = analyse_file(src, "t.py")
        self.assertEqual([f.rule for f in report.findings], ["tautology"])

    def test_ignore_on_another_test_does_not_leak(self):
        src = ("def test_a():  # suiteaudit: ignore\n    assert True\n\n"
               "def test_b():\n    assert True\n")
        report = analyse_file(src, "t.py")
        self.assertEqual([f.test for f in report.findings], ["test_b"])
        self.assertEqual([f.test for f in report.suppressed], ["test_a"])

    def test_analyse_source_hides_suppressed_but_still_counts_the_test(self):
        src = "def test_x():  # suiteaudit: ignore\n    assert True\n"
        findings, n = analyse_source(src, "t.py")
        self.assertEqual((findings, n), ([], 1))


if __name__ == "__main__":
    unittest.main(verbosity=2)


class TestSecondMeasurementFalsePositives(unittest.TestCase):
    """Shapes the 0.1.0 candidate flagged when it was run against eight more
    popular suites on 7 Sep 2026 (django, pytest, pydantic, rich, httpx, black,
    urllib3, flask). Every one is a real test that CAN fail, or is not a test."""

    def test_assert_false_in_an_except_branch_is_a_fail_marker(self):
        # Textualize/rich tests/test_inspect.py::test_inspect_swig_edge_case
        src = '''
def test_x():
    try:
        inspect(thing)
    except Exception as e:
        assert False, f"should not raise {e}"
'''
        self.assertEqual(rules(src), [])

    def test_assert_zero_in_an_else_branch_is_a_fail_marker(self):
        # pytest-dev/pytest testing/test_runner.py::test_exit_propagates
        src = '''
def test_x():
    try:
        run()
    except SystemExit:
        pass
    else:
        assert 0, "did not raise"
'''
        self.assertEqual(rules(src), [])

    def test_a_fail_marker_inside_a_nested_function_is_not_a_tautology(self):
        # pydantic tests/test_validate_call.py::test_do_not_call_repr_on_validate_call
        src = '''
def test_x():
    class Thing:
        def __repr__(self):
            assert False
    Thing(50)
'''
        self.assertNotIn("tautology", rules(src))

    def test_a_constant_that_always_fails_is_not_a_tautology(self):
        self.assertEqual(rules("def test_x():\n    assert 1 == 2\n"), [])
        self.assertEqual(rules("def test_x():\n    assert None\n"), [])
        self.assertEqual(rules("def test_x():\n    assert not True\n"), [])
        self.assertEqual(rules("def test_x():\n    assert ()\n"), [])

    def test_truthy_constants_are_still_tautologies(self):
        self.assertEqual(rules("def test_x():\n    assert 1 == 1\n"), ["tautology"])
        self.assertEqual(rules("def test_x():\n    assert not False\n"), ["tautology"])
        self.assertEqual(rules("def test_x():\n    assert (1, 2)\n"), ["tautology"])
        self.assertEqual(rules("def test_x():\n    assert 'x'\n"), ["tautology"])
        self.assertEqual(rules("def test_x():\n    assert 1 < 2 <= 2\n"), ["tautology"])

    def test_unittest_assert_true_on_false_always_fails(self):
        src = "class T(unittest.TestCase):\n    def test_x(self):\n        self.assertTrue(False)\n"
        self.assertEqual(rules(src), [])

    def test_unittest_assert_false_on_false_is_a_tautology(self):
        src = "class T(unittest.TestCase):\n    def test_x(self):\n        self.assertFalse(False)\n"
        self.assertEqual(rules(src), ["tautology"])

    def test_unittest_assert_equal_of_two_different_constants_always_fails(self):
        src = "class T(unittest.TestCase):\n    def test_x(self):\n        self.assertEqual(2, 3)\n"
        self.assertEqual(rules(src), [])

    def test_unittest_assert_is_of_two_equal_singletons_is_a_tautology(self):
        src = "class T(unittest.TestCase):\n    def test_x(self):\n        self.assertIs(None, None)\n"
        self.assertEqual(rules(src), ["tautology"])

    def test_a_constant_expression_too_big_to_evaluate_is_left_alone(self):
        # Deciding this would mean computing it; the rule says nothing instead.
        src = "def test_x():\n    assert 2 ** 10 ** 9 == 0\n"
        self.assertEqual(rules(src), [])
        src = "def test_x():\n    assert 'a' * 10 ** 9\n"
        self.assertEqual(rules(src), [])

    def test_an_http_patch_request_is_not_a_mock(self):
        # encode/httpx tests/test_api.py::test_patch
        src = '''
def test_patch(server):
    response = httpx.patch(server.url, content=b"x")
    assert response.status_code == 200
'''
        self.assertEqual(rules(src), [])

    def test_mock_dot_patch_is_still_a_mock_factory(self):
        src = '''
def test_x():
    with mock.patch("app.client") as client:
        client.send("hi")
    client.send.assert_called_once_with("hi")
'''
        self.assertEqual(rules(src), ["mock-only"])

    def test_pytest_mock_mocker_patch_is_a_mock_factory(self):
        src = '''
def test_x(mocker):
    client = mocker.patch("app.client")
    client.send("hi")
    client.send.assert_called_once_with("hi")
'''
        self.assertEqual(rules(src), ["mock-only"])

    def test_patch_imported_under_an_alias_is_a_mock_factory(self):
        src = '''
from unittest.mock import patch as p

def test_x():
    with p("app.client") as client:
        client.send("hi")
    client.send.assert_called_once_with("hi")
'''
        self.assertEqual(rules(src), ["mock-only"])

    def test_unittest_mock_fully_qualified_is_a_mock_factory(self):
        src = '''
import unittest.mock

def test_x():
    client = unittest.mock.MagicMock()
    client.send("hi")
    client.send.assert_called_once_with("hi")
'''
        self.assertEqual(rules(src), ["mock-only"])

    def test_a_module_imported_as_mock_is_a_mock_root(self):
        src = '''
from unittest import mock as m

def test_x():
    client = m.Mock()
    client.send("hi")
    client.send.assert_called_once_with("hi")
'''
        self.assertEqual(rules(src), ["mock-only"])

    def test_methods_in_a_plain_class_are_not_tests(self):
        # django tests/template_tests/filter_tests/test_dictsort.py::User
        src = '''
class User:
    password = "abc"

    def test_method(self):
        """This is just a test method."""


class FunctionTests(SimpleTestCase):
    def test_property_resolver(self):
        assert resolve(User()) == "abc"
'''
        self.assertEqual(count_tests(src), 1)
        self.assertEqual(rules(src), [])

    def test_methods_in_a_test_class_are_tests(self):
        for header in ("class T(unittest.TestCase):", "class T(SimpleTestCase):",
                       "class TestT:", "class ThingTests:", "class ThingTest(Base):",
                       "class T(Mixin, django.test.TestCase):",
                       "class T(IsolatedAsyncioTestCase):"):
            src = header + "\n    def test_x(self):\n        pass\n"
            self.assertEqual(count_tests(src), 1, header)
            self.assertEqual(rules(src), ["empty-test"], header)

    def test_an_empty_body_under_an_unknown_decorator_is_low(self):
        # django tests/gis_tests/test_gis_tests_utils.py::test_not_mutated
        src = '''
@test_mutation(raises=False)
def test_not_mutated(func):
    pass
'''
        findings, _ = analyse_source(src, "t.py")
        self.assertEqual([(f.rule, f.severity) for f in findings],
                         [("empty-test", "low")])

    def test_an_empty_body_under_an_inert_decorator_is_still_high(self):
        for deco in ("@pytest.mark.parametrize('a', [1])", "@pytest.mark.skip",
                     "@unittest.skipIf(True, 'x')", "@patch('app.x')",
                     "@mock.patch.object(A, 'x')", "@override_settings(DEBUG=True)"):
            src = deco + "\ndef test_x(*a):\n    pass\n"
            findings, _ = analyse_source(src, "t.py")
            self.assertEqual([(f.rule, f.severity) for f in findings],
                             [("empty-test", "high")], deco)

    def test_a_subclass_of_a_local_test_class_is_a_test_class(self):
        # django tests/staticfiles_tests/test_liveserver.py::StaticLiveServerChecks
        src = '''
class LiveServerBase(LiveServerTestCase):
    pass


class StaticLiveServerChecks(LiveServerBase):
    def test_test_test(self):
        pass
'''
        self.assertEqual(count_tests(src), 1)
        self.assertEqual(rules(src), ["empty-test"])

    def test_a_base_class_cycle_does_not_recurse_forever(self):
        src = "class A(B):\n    def test_x(self):\n        pass\n\nclass B(A):\n    pass\n"
        self.assertEqual(count_tests(src), 0)

    def test_a_plain_base_from_elsewhere_is_not_guessed_at(self):
        # A miss, on purpose: the base's name says nothing and it is not in
        # this file, so its methods are not reported.
        src = "class Checks(Base):\n    def test_x(self):\n        pass\n"
        self.assertEqual(count_tests(src), 0)


class TestMutationCoverageGaps(unittest.TestCase):
    """Six gaps a mutation-testing pass found in this file's own suite
    (audit/mutants/SuiteAudit.md, section 3): each mutation below survived the
    previous tests because nothing pinned the exact behaviour it changes."""

    def test_mock_only_finding_is_high_severity(self):
        # detectors.py ~784: `severity="high"` on the mock-only Finding can
        # silently become `None` -- `rules()` only checks that "mock-only" is
        # among the rule names, never the severity that decides FAIL/WARN.
        src = """
def test_x():
    client = MagicMock()
    client.send("hi")
    client.send.assert_called_once_with("hi")
"""
        findings, _ = analyse_source(src, "t.py")
        finding = next(f for f in findings if f.rule == "mock-only")
        self.assertEqual(finding.severity, "high")

    def test_self_in_a_mock_only_assertion_does_not_defeat_the_rule(self):
        # detectors.py ~761: `names.discard("self")` -- the assertion's own
        # receiver (`self` in unittest) must not read as "something besides
        # the mock was inspected", or a plain unittest-style mock-only test
        # that happens to compare against `self` would be missed.
        src = """
class T(unittest.TestCase):
    def test_x(self):
        mock = Mock()
        mock.owner = self
        assert mock.owner is self
"""
        self.assertIn("mock-only", rules(src))

    def test_one_undecidable_side_is_not_a_tautology(self):
        # detectors.py ~516: `if not (ok_a and ok_b)` must bail out whenever
        # EITHER side of assertEqual/assertIs/assertAlmostEqual is undecided.
        # `2 * 3` is syntactically a constant expression (so it reaches
        # `_constants_agree` at all) but `*` is one of the `_UNBOUNDED_OPS`
        # `_constant_value` deliberately refuses to fold, so it is undecided
        # in practice; pairing it with a real constant must never read as
        # "both sides are equal constants".
        src = "def test_x():\n    assertEqual(2 * 3, None)\n"
        self.assertNotIn("tautology", rules(src))

    def test_assert_is_of_two_equal_non_none_constants_is_a_tautology(self):
        # detectors.py ~520: the assertIs type-match check must compare the
        # two operands' types to EACH OTHER. The only existing coverage
        # (`assertIs(None, None)`) has both sides already `NoneType`, so a
        # check that quietly compares one side to `NoneType` instead of to
        # the other side's type would pass it unnoticed.
        src = "class T(unittest.TestCase):\n    def test_x(self):\n        self.assertIs(1, 1)\n"
        self.assertEqual(rules(src), ["tautology"])

    def test_dict_literal_equality_is_a_tautology(self):
        # detectors.py ~381: `_is_constant_expr`'s ast.Dict clause. No
        # existing test ever hands a dict literal to a tautology check, so
        # this branch is never even reached by the suite.
        src = "def test_x():\n    assertEqual({'a': 1}, {'a': 1})\n"
        self.assertIn("tautology", rules(src))

    def test_list_literal_equality_is_a_tautology(self):
        # detectors.py ~453: `_fold`'s list clause must fold each element of
        # the actual list. Tuple folding is exercised elsewhere
        # (`assert (1, 2)`), but no test ever folds a list literal.
        src = "def test_x():\n    assertEqual([1, 2], [1, 2])\n"
        self.assertIn("tautology", rules(src))


class TestMockContextPlainImport(unittest.TestCase):
    """`mock_context`'s `ast.Import` branch (detectors.py ~228-237): every
    existing mock-root fixture uses `from unittest import mock as m`
    (`ImportFrom`); a bare `import mock`, an aliased `import mock as m`, and
    an unrelated import are never exercised at all
    (audit/mutants/SuiteAudit.md, section 4, item 1)."""

    def test_bare_import_mock_is_recognized_and_does_not_crash(self):
        # The single most common way to import the mock library. A survivor
        # mutation turns `.split(".")[0]` into `.split(".")[1]`, which is an
        # outright IndexError on this exact input (`"mock".split(".")` has
        # only one element) -- mock_context runs on every file, so that
        # mutation would crash the whole audit on any file that merely
        # contains this import, whether or not Mock() is even used.
        src = """
import mock

def test_x():
    client = mock.Mock()
    client.send("hi")
    client.send.assert_called_once_with("hi")
"""
        self.assertEqual(rules(src), ["mock-only"])

    def test_import_mock_as_an_alias_is_a_mock_root(self):
        # `import mock as m` binds a root name ("m") that is NOT already in
        # DEFAULT_MOCK_ROOTS, so this is the one case that actually proves
        # the import is read at all (unlike bare `import mock`, where "mock"
        # is already a default root regardless of this code running).
        src = """
import mock as m

def test_x():
    client = m.Mock()
    client.send("hi")
    client.send.assert_called_once_with("hi")
"""
        self.assertEqual(rules(src), ["mock-only"])

    def test_an_unrelated_import_is_not_mistaken_for_a_mock_root(self):
        # The false positive the docstring exists to prevent: an ordinary,
        # unrelated import must never add its own name to `roots`. Pairs
        # with `test_an_http_patch_request_is_not_a_mock`, but with the
        # import actually present so `mock_context`'s `in MOCK_MODULES`
        # check is the thing standing between this test and a false "mock".
        src = """
import requests

def test_patch(server):
    response = requests.patch(server.url, content=b"x")
    assert response.status_code == 200
"""
        self.assertEqual(rules(src), [])


class TestFoldExceptionFallbackIsConservative(unittest.TestCase):
    """detectors.py ~421-423: when `_fold` raises for a syntactically
    constant-looking expression (division by zero, per the code's own
    comment), `_constant_value` must fall back to "undecided", never to
    "decidably equal" -- otherwise an assertion that cannot even RUN gets
    reported as an unfixable tautology (audit/mutants/SuiteAudit.md, section
    4, item 2 -- "the most actively misleading single verdict found")."""

    def test_a_division_by_zero_is_not_reported_as_a_tautology(self):
        src = ("class T(unittest.TestCase):\n    def test_x(self):\n"
               "        self.assertEqual(1 / 0, 1 / 0)\n")
        self.assertEqual(rules(src), [])


class TestConstantsAgreeDeadPaths(unittest.TestCase):
    """`_constants_agree`'s `assertIs` type-mismatch branch and its
    `assertAlmostEqual` branch are entirely unexercised by any existing test
    (coverage confirms detectors.py:521 and :525 are never hit)
    (audit/mutants/SuiteAudit.md, section 4, item 5)."""

    def test_assert_is_of_two_different_types_is_not_a_tautology(self):
        # `1 is 1.0` is False at runtime (different objects, different
        # types); the type-mismatch guard must say so.
        src = "class T(unittest.TestCase):\n    def test_x(self):\n        self.assertIs(1, 1.0)\n"
        self.assertEqual(rules(src), [])

    def test_assert_is_of_two_unequal_same_type_constants_is_not_a_tautology(self):
        # Same type on both sides, but the values differ: `assertIs(1, 2)`
        # is a real, working assertion (it fails), not an unfixable one.
        src = "class T(unittest.TestCase):\n    def test_x(self):\n        self.assertIs(1, 2)\n"
        self.assertEqual(rules(src), [])

    def test_assert_almost_equal_of_equal_floats_is_a_tautology(self):
        src = ("class T(unittest.TestCase):\n    def test_x(self):\n"
               "        self.assertAlmostEqual(2.0, 2.0)\n")
        self.assertEqual(rules(src), ["tautology"])

    def test_assert_almost_equal_of_different_floats_is_not_a_tautology(self):
        src = ("class T(unittest.TestCase):\n    def test_x(self):\n"
               "        self.assertAlmostEqual(2.0, 3.0)\n")
        self.assertEqual(rules(src), [])

    def test_assert_almost_equal_requires_numeric_operands(self):
        # `assertAlmostEqual` is meaningless for non-numeric types; two equal
        # constants of a type it does not accept must not be reported as a
        # tautology through the generic equality fallback that runs for
        # every OTHER helper. (Two equal bytes objects would satisfy a bare
        # `va == vb`, so this only passes when the numeric-type check is the
        # thing actually deciding it, not a name-string that merely looks
        # like "assertAlmostEqual".)
        src = ("class T(unittest.TestCase):\n    def test_x(self):\n"
               '        self.assertAlmostEqual(b"x", b"x")\n')
        self.assertEqual(rules(src), [])


class TestMockOnlyOrdinaryAttributeAssertion(unittest.TestCase):
    """detectors.py ~773 (`args_only_mocks`): every existing mock-only
    fixture asserts with `x.method.assert_called...()`. The equally ordinary
    `self.assertTrue(m.called)` shape -- a plain unittest assertion whose
    sole argument is an attribute read straight off the mock -- is never
    exercised (audit/mutants/SuiteAudit.md, section 4, item 6)."""

    def test_assert_true_on_a_mocks_called_attribute_is_mock_only(self):
        src = """
class T(unittest.TestCase):
    def test_x(self):
        m = Mock()
        m.thing()
        self.assertTrue(m.called)
"""
        self.assertEqual(rules(src), ["mock-only"])


class TestFoldSingletonIdentityGuard(unittest.TestCase):
    """`_fold`'s `is`/`is not` handling (detectors.py ~467-476) only
    guarantees identity for the language's own singletons (`None`, `True`,
    `False`, `...`); CPython does not guarantee it for other constants
    (large ints, strings), and the guard that refuses to decide those is
    never exercised in either direction (audit/mutants/SuiteAudit.md,
    section 4, item 7)."""

    def test_identity_of_two_equal_int_literals_is_left_undecided(self):
        src = "def test_x():\n    assert 1000000 is 1000000\n"
        self.assertEqual(rules(src), [])

    def test_identity_of_two_equal_string_literals_is_left_undecided(self):
        src = 'def test_x():\n    assert "abc" is "abc"\n'
        self.assertEqual(rules(src), [])

    def test_identity_of_the_none_singleton_is_still_a_tautology(self):
        # The guard must not swallow the one case it exists to allow.
        src = "def test_x():\n    assert None is None\n"
        self.assertEqual(rules(src), ["tautology"])

    def test_none_is_not_none_is_not_a_tautology(self):
        # `is not` must be evaluated as `is not`, never folded down to the
        # same check as `is`: `None is not None` is always False (a fail
        # marker, not a tautology) -- every other test above only exercises
        # the `is` half of this branch.
        src = "def test_x():\n    assert None is not None\n"
        self.assertEqual(rules(src), [])


class TestCollectTestsClassIdentity(unittest.TestCase):
    """`collect_tests`'s class-based branch (detectors.py ~255) builds each
    `TestFunction`'s identity and its `mocks` context positionally; nothing
    checks that two different test classes keep distinct identities, or that
    a class-based test method actually receives the file's real mock context
    rather than silently falling back to the default one
    (audit/mutants/SuiteAudit.md, section 4, item 8)."""

    def test_methods_in_different_classes_keep_distinct_qualified_names(self):
        src = """
class TestA(unittest.TestCase):
    def test_x(self):
        assert True

class TestB(unittest.TestCase):
    def test_x(self):
        assert True
"""
        findings, n = analyse_source(src, "t.py")
        self.assertEqual(n, 2)
        self.assertEqual(sorted(f.test for f in findings),
                         ["TestA.test_x", "TestB.test_x"])

    def test_a_class_method_using_a_non_default_mock_alias_is_recognized(self):
        # If `mocks=ctx` were dropped for class-based tests (falling back to
        # DEFAULT_MOCK_CONTEXT), a mock built through a non-default alias
        # would go unrecognized only inside a class -- module-level
        # functions receive `mocks=ctx` on a separate, untouched line.
        src = """
from unittest import mock as um

class T(unittest.TestCase):
    def test_x(self):
        client = um.Mock()
        client.send("hi")
        client.send.assert_called_once_with("hi")
"""
        self.assertEqual(rules(src), ["mock-only"])


class TestIsMockFactoryCallOnAComputedCallable(unittest.TestCase):
    """`_is_mock_factory_call`'s empty-`names` fallback (detectors.py
    ~295-296): a call through a callable that is not rooted in a plain
    dotted name (`(a or b)()`) must not be treated as a mock construction --
    it is ordinary, unrelated production code that happens to run alongside
    a mock (audit/mutants/SuiteAudit.md, section 4, item 9)."""

    def test_a_call_through_a_computed_callable_is_production_code(self):
        src = """
def test_x():
    m = Mock()
    m.thing()
    (real_a or real_b)()
    m.thing.assert_called_once()
"""
        self.assertEqual(rules(src), [])


class TestCallsOutsideMocksSelfRootedAssertionLikeCall(unittest.TestCase):
    """`_calls_outside_mocks`'s `self`-receiver exclusion (detectors.py
    ~552) is meant to let a real assertion helper called through `self` pass
    without being read as "production code ran". A call whose name merely
    LOOKS like an assertion (starts with `assert`) but is rooted somewhere
    else entirely must still count as real, unexcluded production code
    (audit/mutants/SuiteAudit.md, section 4, item 10)."""

    def test_an_assert_named_helper_not_rooted_in_self_is_production_code(self):
        src = """
def test_x():
    m = Mock()
    m.run()
    validators.assert_valid(42)
    m.run.assert_called_once()
"""
        self.assertEqual(rules(src), [])


class TestMockVariablesOrdinaryAssignmentBeforeAMock(unittest.TestCase):
    """`_mock_variables`'s `ast.walk` scan (detectors.py ~359-361): an
    ordinary, non-mock assignment appearing before the mock-constructing one
    in the same test body must not stop the scan from finding the mock that
    comes after it (audit/mutants/SuiteAudit.md, section 4, item 13)."""

    def test_a_plain_assignment_before_the_mock_does_not_hide_it(self):
        src = """
def test_x():
    expected = 5
    m = Mock()
    m.thing()
    m.thing.assert_called_once()
"""
        self.assertEqual(rules(src), ["mock-only"])


class TestFoldSetLiteral(unittest.TestCase):
    """`_fold`'s `ast.Set` clause (detectors.py ~454-455) is never exercised
    -- the same class of gap the delivered patch (0001) closed for lists and
    dicts, left open for set literals (audit/mutants/SuiteAudit.md, section
    4, item 14)."""

    def test_set_literal_equality_is_a_tautology(self):
        src = ("class T(unittest.TestCase):\n    def test_x(self):\n"
               "        self.assertEqual({1, 2}, {1, 2})\n")
        self.assertEqual(rules(src), ["tautology"])


class TestFailIsARealAssertion(unittest.TestCase):
    """`_is_assertion_name`'s fallback (detectors.py ~318-320) recognizes
    `fail` only because it is listed in `UNITTEST_ASSERTIONS` explicitly --
    it is the one member of that set that does not start with `assert`, so
    the `.startswith("assert")` half of the check cannot rescue it
    (audit/mutants/SuiteAudit.md, section 4, item 15)."""

    def test_self_fail_counts_as_an_assertion(self):
        src = """
class T(unittest.TestCase):
    def test_x(self):
        result = compute()
        if result != 1:
            self.fail("bad result")
"""
        self.assertNotIn("no-assertion", rules(src))


class TestSuppressionsCommentScanDoesNotStopEarly(unittest.TestCase):
    """`_suppressions`'s token scan (detectors.py ~567) must keep looking
    past an ordinary comment that is not itself a suppress directive -- a
    real `# suiteaudit: ignore` on a later line must not be missed just
    because an unrelated comment came first in the file
    (audit/mutants/SuiteAudit.md, section 4, item 4)."""

    def test_an_ordinary_comment_does_not_hide_a_later_suppress_comment(self):
        src = ("def test_x():  # just a note\n"
               "    assert True  # suiteaudit: ignore[tautology]\n")
        report = analyse_file(src, "t.py")
        self.assertEqual(report.findings, [])
        self.assertEqual([f.rule for f in report.suppressed], ["tautology"])


class TestSuppressionMultiRuleCommaSplit(unittest.TestCase):
    """`_suppressions` splits a multi-rule comment on `,` (detectors.py
    ~575). The existing multi-rule regression test's only real finding is
    the LAST rule named in the comment, which a whitespace-split would still
    match by accident (the stray comma glues itself to every rule but the
    last); this pins the FIRST rule instead, so a whitespace split would
    leave it suppressed as `"no-assertion,"` and the real `no-assertion`
    finding would leak through unsuppressed
    (audit/mutants/SuiteAudit.md, section 4, item 16)."""

    def test_the_first_rule_in_a_multi_rule_comment_is_still_suppressed(self):
        src = "def test_x():  # suiteaudit: ignore[no-assertion, tautology]\n    compute()\n"
        report = analyse_file(src, "t.py")
        self.assertEqual(report.findings, [])
        self.assertEqual([f.rule for f in report.suppressed], ["no-assertion"])


class TestMockVariablesAnnotatedAssignment(unittest.TestCase):
    """`_mock_variables`'s `ast.AnnAssign` branch (detectors.py ~353-354) is
    never exercised: no fixture declares a mock with a type annotation
    (`m: object = Mock()`) (audit/mutants/SuiteAudit.md, section 4, item
    17)."""

    def test_an_annotated_mock_assignment_is_recognized(self):
        src = """
def test_x():
    m: object = Mock()
    m.thing()
    m.thing.assert_called_once()
"""
        self.assertEqual(rules(src), ["mock-only"])
