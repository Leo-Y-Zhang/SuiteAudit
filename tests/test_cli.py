# SPDX-License-Identifier: Apache-2.0
"""Tests for the command line: the exit-code contract a CI gate relies on."""
from __future__ import annotations

import contextlib
import io
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from suiteaudit import __main__ as cli  # noqa: E402

VACUOUS = "def test_nothing():\n    assert True\n"
HONEST = "def test_real():\n    assert compute() == 4\n"
SMOKE = "def test_smoke():\n    compute()\n"


def run(argv: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(argv)
    return code, out.getvalue(), err.getvalue()


def write(root: str, name: str, text: str) -> str:
    path = os.path.join(root, name)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


class TestExitCodes(unittest.TestCase):
    def test_fail_exits_1(self):
        with tempfile.TemporaryDirectory() as d:
            write(d, "test_bad.py", VACUOUS)
            code, out, _ = run(["check", d])
        self.assertEqual(code, 1)
        self.assertIn("VERDICT: FAIL", out)

    def test_pass_exits_0(self):
        with tempfile.TemporaryDirectory() as d:
            write(d, "test_ok.py", HONEST)
            code, out, _ = run(["check", d])
        self.assertEqual(code, 0)
        self.assertIn("VERDICT: PASS", out)

    def test_no_data_exits_1_by_default(self):
        with tempfile.TemporaryDirectory() as d:
            code, out, _ = run(["check", d])
        self.assertEqual(code, 1)
        self.assertIn("VERDICT: NO DATA", out)

    def test_warn_exits_0_by_default_and_1_with_fail_on_any(self):
        with tempfile.TemporaryDirectory() as d:
            write(d, "test_smoke.py", SMOKE)
            self.assertEqual(run(["check", d])[0], 0)
            self.assertEqual(run(["check", d, "--fail-on", "any"])[0], 1)

    def test_fail_on_never_exits_0_even_on_no_data(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(run(["check", d, "--fail-on", "never"])[0], 0)

    def test_no_command_prints_help_and_exits_2(self):
        code, out, _ = run([])
        self.assertEqual(code, 2)
        self.assertIn("usage:", out)


class TestSeveralPaths(unittest.TestCase):
    def test_two_paths_are_merged(self):
        """pre-commit hands the hook many filenames; the first release
        candidate rejected a second positional argument."""
        with tempfile.TemporaryDirectory() as d:
            a = write(d, "test_ok.py", HONEST)
            b = write(d, "test_bad.py", VACUOUS)
            code, out, _ = run(["check", a, b])
        self.assertEqual(code, 1)
        self.assertIn("2 test file(s), 2 test(s)", out)

    def test_json_output_carries_the_suppressed_count(self):
        with tempfile.TemporaryDirectory() as d:
            write(d, "test_bad.py",
                  "def test_nothing():  # suiteaudit: ignore\n    assert True\n")
            code, out, _ = run(["check", d, "--json"])
        self.assertEqual(code, 0)
        self.assertIn('"suppressed_count": 1', out)

    def test_text_report_mentions_set_aside_findings(self):
        with tempfile.TemporaryDirectory() as d:
            write(d, "test_bad.py",
                  "def test_nothing():  # suiteaudit: ignore\n    assert True\n")
            _, out, _ = run(["check", d])
        self.assertIn("1 finding(s) set aside", out)


class TestVersion(unittest.TestCase):
    def test_version_flag_prints_the_package_version(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit) as cm:
            cli.main(["--version"])
        self.assertEqual(cm.exception.code, 0)
        self.assertTrue(out.getvalue().startswith("suiteaudit "), out.getvalue())


class TestVerifyPreflight(unittest.TestCase):
    def test_verify_outside_a_checkout_says_so_and_exits_2(self):
        """From a wheel install there is no tests/ directory; the first release
        candidate raised ImportError with a traceback."""
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(cli, "_checkout_root", return_value=d):
            code, _, err = run(["verify"])
        self.assertEqual(code, 2)
        self.assertIn("source checkout", err)

    def test_preflight_passes_in_this_checkout(self):
        """Not run end to end here: verify runs this very suite, which would
        recurse. The guard is what the wheel case tests, so pin the guard."""
        self.assertIsNone(cli._verify_preflight(cli._checkout_root()))


class TestExplain(unittest.TestCase):
    def test_every_rule_explains_when_it_is_fine_to_ignore(self):
        for rule in cli.RULE_HELP:
            code, out, _ = run(["explain", rule])
            self.assertEqual(code, 0)
            self.assertIn("when it is fine to ignore", out)

    def test_unknown_rule_exits_2(self):
        code, _, err = run(["explain", "nonsense"])
        self.assertEqual(code, 2)
        self.assertIn("known rules", err)


if __name__ == "__main__":
    unittest.main(verbosity=2)
