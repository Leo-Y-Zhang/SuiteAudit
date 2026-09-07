# SPDX-License-Identifier: Apache-2.0
"""Tests for the project walk and the verdict.

The verdict is the product. These pin the parts of it that an adopter's CI
depends on: that a broken file is reported rather than fatal, that several
paths merge into one verdict, and that no suppression can ever manufacture a
PASS out of a run that checked nothing.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from suiteaudit.audit import audit, audit_paths, to_json  # noqa: E402

VACUOUS = "def test_nothing():\n    assert True\n"
HONEST = "def test_real():\n    assert compute() == 4\n"


def write(root: str, name: str, text: str | bytes) -> str:
    path = os.path.join(root, name)
    mode = "wb" if isinstance(text, bytes) else "w"
    kwargs = {} if isinstance(text, bytes) else {"encoding": "utf-8"}
    with open(path, mode, **kwargs) as fh:
        fh.write(text)
    return path


class TestVerdict(unittest.TestCase):
    def test_empty_directory_is_no_data_not_pass(self):
        with tempfile.TemporaryDirectory() as d:
            verdict, _ = audit(d).verdict()
        self.assertEqual(verdict, "NO DATA")

    def test_test_file_with_no_tests_is_no_data(self):
        with tempfile.TemporaryDirectory() as d:
            write(d, "test_empty.py", "def helper():\n    return 1\n")
            verdict, _ = audit(d).verdict()
        self.assertEqual(verdict, "NO DATA")

    def test_honest_suite_passes(self):
        with tempfile.TemporaryDirectory() as d:
            write(d, "test_ok.py", HONEST)
            verdict, _ = audit(d).verdict()
        self.assertEqual(verdict, "PASS")

    def test_vacuous_suite_fails(self):
        with tempfile.TemporaryDirectory() as d:
            write(d, "test_bad.py", VACUOUS)
            verdict, _ = audit(d).verdict()
        self.assertEqual(verdict, "FAIL")

    def test_only_medium_findings_is_warn(self):
        with tempfile.TemporaryDirectory() as d:
            write(d, "test_smoke.py", "def test_smoke():\n    compute()\n")
            verdict, _ = audit(d).verdict()
        self.assertEqual(verdict, "WARN")

    def test_a_dead_assertion_in_a_real_test_is_warn_not_fail(self):
        with tempfile.TemporaryDirectory() as d:
            write(d, "test_mixed.py",
                  "def test_x():\n    assert True\n    assert compute() == 1\n")
            result = audit(d)
        self.assertEqual(result.verdict()[0], "WARN")
        self.assertEqual([f.severity for f in result.findings], ["low"])


class TestRobustness(unittest.TestCase):
    def test_a_non_utf8_file_is_recorded_not_fatal(self):
        """The first release candidate crashed with a traceback on a latin-1
        file and abandoned every other file in the run."""
        with tempfile.TemporaryDirectory() as d:
            write(d, "test_latin1.py", "# caf\xe9\n".encode("latin-1") + VACUOUS.encode())
            write(d, "test_ok.py", HONEST)
            result = audit(d)
        self.assertEqual(len(result.unparsed), 1)
        self.assertIn("not utf-8", result.unparsed[0][1])
        self.assertEqual(result.n_files, 1)
        self.assertEqual(result.verdict()[0], "PASS")

    def test_null_bytes_are_recorded_not_fatal(self):
        with tempfile.TemporaryDirectory() as d:
            write(d, "test_nul.py", b"def test_x():\n    assert True\x00\n")
            write(d, "test_ok.py", HONEST)
            result = audit(d)
        self.assertEqual(len(result.unparsed), 1)
        self.assertEqual(result.n_files, 1)

    def test_syntax_error_is_recorded_not_fatal(self):
        with tempfile.TemporaryDirectory() as d:
            write(d, "test_broken.py", "def test_x(:\n")
            result = audit(d)
        self.assertEqual(len(result.unparsed), 1)
        self.assertIn("syntax error", result.unparsed[0][1])
        self.assertEqual(result.verdict()[0], "NO DATA")

    def test_unparsed_files_appear_in_the_json(self):
        with tempfile.TemporaryDirectory() as d:
            write(d, "test_broken.py", "def test_x(:\n")
            data = json.loads(to_json(audit(d)))
        self.assertEqual(len(data["unparsed"]), 1)
        self.assertEqual(data["verdict"], "NO DATA")


class TestSeveralPaths(unittest.TestCase):
    def test_two_directories_merge_into_one_verdict(self):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            write(a, "test_ok.py", HONEST)
            write(b, "test_bad.py", VACUOUS)
            result = audit_paths([a, b])
        self.assertEqual(result.n_files, 2)
        self.assertEqual(result.n_tests, 2)
        self.assertEqual(result.verdict()[0], "FAIL")
        self.assertEqual(result.roots, [a, b])

    def test_a_single_file_path_is_audited_as_itself(self):
        with tempfile.TemporaryDirectory() as d:
            path = write(d, "test_bad.py", VACUOUS)
            result = audit_paths([path])
        self.assertEqual(result.n_files, 1)
        self.assertEqual(result.findings[0].file, path)

    def test_no_paths_is_no_data(self):
        result = audit_paths([])
        self.assertEqual(result.verdict()[0], "NO DATA")


class TestSuppressionAtTheVerdict(unittest.TestCase):
    def test_suppressed_findings_leave_the_verdict_and_are_counted(self):
        with tempfile.TemporaryDirectory() as d:
            write(d, "test_bad.py",
                  "def test_nothing():  # suiteaudit: ignore[tautology]\n"
                  "    assert True\n")
            result = audit(d)
            data = json.loads(to_json(result))
        self.assertEqual(result.verdict()[0], "PASS")
        self.assertEqual(data["suppressed_count"], 1)
        self.assertEqual(data["suppressed"][0]["rule"], "tautology")
        self.assertEqual(data["findings"], [])

    def test_suppression_cannot_turn_no_data_into_pass(self):
        """A file that is nothing but an ignore comment checked nothing."""
        with tempfile.TemporaryDirectory() as d:
            write(d, "test_none.py", "# suiteaudit: ignore\n")
            result = audit(d)
        self.assertEqual(result.verdict()[0], "NO DATA")
        self.assertEqual(result.suppressed, [])

    def test_a_suppression_for_the_wrong_rule_still_fails(self):
        with tempfile.TemporaryDirectory() as d:
            write(d, "test_bad.py",
                  "def test_nothing():  # suiteaudit: ignore[mock-only]\n"
                  "    assert True\n")
            result = audit(d)
        self.assertEqual(result.verdict()[0], "FAIL")


if __name__ == "__main__":
    unittest.main(verbosity=2)
