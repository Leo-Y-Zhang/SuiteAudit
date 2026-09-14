# SPDX-License-Identifier: Apache-2.0
"""Tests for the project walk and the verdict.

The verdict is the product. These pin the parts of it that an adopter's CI
depends on: that a broken file is reported rather than fatal, that several
paths merge into one verdict, and that no suppression can ever manufacture a
PASS out of a run that checked nothing.
"""
from __future__ import annotations

import builtins
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch as mock_patch

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from suiteaudit.audit import audit, audit_paths, excluded, to_json  # noqa: E402

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


class TestExclude(unittest.TestCase):
    """`exclude` drops files by a glob on their path relative to the root.
    pytest's own suite carries deliberately empty example tests under
    testing/example_scripts/ as fixtures; an adopter needs a way to leave such
    a directory out without a comment in every file."""

    def test_exclude_pattern_skips_matching_files(self):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "example_scripts", "sub"))
            write(d, "test_ok.py", HONEST)
            write(os.path.join(d, "example_scripts", "sub"), "test_fixture.py", VACUOUS)
            full = audit(d)
            trimmed = audit(d, exclude=["example_scripts/*"])
        self.assertEqual(full.verdict()[0], "FAIL")
        self.assertEqual(trimmed.verdict()[0], "PASS")
        self.assertEqual((trimmed.n_files, trimmed.n_tests), (1, 1))

    def test_exclude_matches_the_relative_path_with_forward_slashes(self):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "a", "b"))
            write(os.path.join(d, "a", "b"), "test_deep.py", VACUOUS)
            exact = audit(d, exclude=["a/b/test_deep.py"]).verdict()[0]
            star = audit(d, exclude=["*/test_deep.py"]).verdict()[0]
            other = audit(d, exclude=["other/*"]).verdict()[0]
        self.assertEqual((exact, star, other), ("NO DATA", "NO DATA", "FAIL"))

    def test_exclude_can_name_a_directory_or_a_file(self):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "fixtures"))
            write(d, "test_ok.py", HONEST)
            write(os.path.join(d, "fixtures"), "test_data.py", VACUOUS)
            by_dir = audit(d, exclude=["fixtures"]).verdict()[0]
            by_file = audit(d, exclude=["test_data.py"]).verdict()[0]
        self.assertEqual((by_dir, by_file), ("PASS", "PASS"))

    def test_excluding_everything_is_no_data_not_pass(self):
        with tempfile.TemporaryDirectory() as d:
            write(d, "test_ok.py", HONEST)
            verdict, _ = audit(d, exclude=["*"]).verdict()
        self.assertEqual(verdict, "NO DATA")

    def test_exclude_applies_across_several_paths(self):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "one"))
            os.makedirs(os.path.join(d, "two", "skip"))
            write(os.path.join(d, "one"), "test_ok.py", HONEST)
            write(os.path.join(d, "two", "skip"), "test_bad.py", VACUOUS)
            verdict, _ = audit_paths([os.path.join(d, "one"), os.path.join(d, "two")],
                                     exclude=["skip/*"]).verdict()
        self.assertEqual(verdict, "PASS")


class TestOneDirectoryWithSeveralFiles(unittest.TestCase):
    """`audit()`'s own accumulation loop (`result.n_tests += report.n_tests`,
    `result.n_files += 1`) is exercised by no fixture: the only multi-file
    test (`test_two_directories_merge_into_one_verdict`, above) merges two
    SEPARATE one-file directories through `AuditResult.merge`, a different
    method with its own `+=`. A single directory holding two or more test
    files runs this loop's body more than once in every existing test only
    here (audit/mutants/SuiteAudit.md, section 4, item 3)."""

    def test_counts_accumulate_across_every_file_not_just_the_last(self):
        with tempfile.TemporaryDirectory() as d:
            write(d, "test_a.py", "def test_a():\n    assert compute() == 1\n")
            write(d, "test_b.py", "def test_b():\n    assert compute() == 2\n")
            write(d, "test_c.py", "def test_c():\n    assert compute() == 3\n")
            result = audit(d)
        self.assertEqual(result.n_files, 3)
        self.assertEqual(result.n_tests, 3)
        self.assertEqual(result.verdict()[0], "PASS")

    def test_a_vacuous_file_among_honest_ones_still_fails_the_whole_run(self):
        # Guards the same accumulation, but for `findings`/`n_failing_tests`
        # rather than the bare counts: if the loop only kept the last
        # file's contribution, a vacuous file that is not alphabetically
        # last would vanish from the verdict entirely.
        with tempfile.TemporaryDirectory() as d:
            write(d, "test_a_bad.py", VACUOUS)
            write(d, "test_b_ok.py", HONEST)
            result = audit(d)
        self.assertEqual(result.n_files, 2)
        self.assertEqual(result.n_tests, 2)
        self.assertEqual(result.verdict()[0], "FAIL")


class TestOneBadFileDoesNotTruncateTheWholeWalk(unittest.TestCase):
    """A whole family of `continue`-in-a-loop lines in `audit.py` and
    `iter_test_files` exist specifically so that one problem file does not
    silently abandon every file that comes alphabetically after it. None of
    them is exercised by a directory that actually holds a good file AFTER
    a bad one (audit/mutants/SuiteAudit.md, section 4, item 4)."""

    def test_a_syntax_error_does_not_stop_later_files_from_being_audited(self):
        with tempfile.TemporaryDirectory() as d:
            write(d, "test_a_broken.py", "def test_x(:\n")
            write(d, "test_b_ok.py", HONEST)
            result = audit(d)
        self.assertEqual(len(result.unparsed), 1)
        self.assertEqual(result.n_files, 1)
        self.assertEqual(result.n_tests, 1)
        self.assertEqual(result.verdict()[0], "PASS")

    def test_a_null_byte_file_does_not_stop_later_files_from_being_audited(self):
        with tempfile.TemporaryDirectory() as d:
            write(d, "test_a_nul.py", b"def test_x():\n    assert True\x00\n")
            write(d, "test_b_ok.py", HONEST)
            result = audit(d)
        self.assertEqual(len(result.unparsed), 1)
        self.assertEqual(result.n_files, 1)
        self.assertEqual(result.verdict()[0], "PASS")

    def test_an_unreadable_file_does_not_stop_later_files_from_being_audited(self):
        # Simulates the OSError branch (a permission error, in practice)
        # without depending on this environment's actual file permissions.
        real_open = builtins.open

        def flaky_open(path, *a, **kw):
            if os.path.basename(path) == "test_a_unreadable.py":
                raise PermissionError("simulated: permission denied")
            return real_open(path, *a, **kw)

        with tempfile.TemporaryDirectory() as d:
            write(d, "test_a_unreadable.py", VACUOUS)
            write(d, "test_b_ok.py", HONEST)
            with mock_patch("builtins.open", side_effect=flaky_open):
                result = audit(d)
        self.assertEqual(len(result.unparsed), 1)
        self.assertEqual(result.n_files, 1)
        self.assertEqual(result.verdict()[0], "PASS")

    def test_a_non_test_file_does_not_stop_later_files_from_being_found(self):
        # iter_test_files:125 -- the filename filter's own `continue`.
        with tempfile.TemporaryDirectory() as d:
            write(d, "conftest.py", "x = 1\n")
            write(d, "test_ok.py", HONEST)
            result = audit(d)
        self.assertEqual(result.n_files, 1)
        self.assertEqual(result.verdict()[0], "PASS")

    def test_an_excluded_file_does_not_stop_later_files_from_being_found(self):
        # iter_test_files:129 -- the `excluded(...)` check's own `continue`.
        with tempfile.TemporaryDirectory() as d:
            write(d, "test_a_excluded.py", VACUOUS)
            write(d, "test_b_ok.py", HONEST)
            result = audit(d, exclude=["test_a_excluded.py"])
        self.assertEqual(result.n_files, 1)
        self.assertEqual(result.verdict()[0], "PASS")


class TestFailingTestIdentityAcrossClasses(unittest.TestCase):
    """`AuditResult.n_failing_tests` keys on `(file, test)`; two different
    `TestCase` methods that happen to share a bare method name in different
    classes must never collapse into one counted failure
    (audit/mutants/SuiteAudit.md, section 4, item 8)."""

    def test_same_named_methods_in_different_classes_both_count(self):
        src = """
class TestA(unittest.TestCase):
    def test_x(self):
        assert True

class TestB(unittest.TestCase):
    def test_x(self):
        assert True
"""
        with tempfile.TemporaryDirectory() as d:
            write(d, "test_dup.py", src)
            result = audit(d)
        self.assertEqual(result.n_failing_tests, 2)
        self.assertEqual(len(result.high), 2)


class TestAlternateTestFileNaming(unittest.TestCase):
    """`looks_like_tests`'s documented `*_test.py` convention (audit.py:95)
    is satisfied by no fixture -- every one uses `test_*.py`
    (audit/mutants/SuiteAudit.md, section 4, item 11)."""

    def test_a_trailing_test_py_file_is_discovered(self):
        with tempfile.TemporaryDirectory() as d:
            write(d, "compute_test.py", HONEST)
            result = audit(d)
        self.assertEqual(result.n_files, 1)
        self.assertEqual(result.verdict()[0], "PASS")


class TestExcludeByAnIntermediateDirectorySegment(unittest.TestCase):
    """`excluded()`'s candidates are prefixes of the relative path built from
    the root down (`excluded()`, audit.py:98-112); a pattern naming the
    OUTERMOST segment of a nested path must still match, exercising the
    multi-segment prefix list beyond the single-directory case the existing
    suite already covers (audit/mutants/SuiteAudit.md, section 4, item 12)."""

    def test_excluding_the_top_segment_of_a_nested_path_matches(self):
        self.assertTrue(excluded("fixtures/sub/test_deep.py", ["fixtures"]))

    def test_excluding_a_segment_that_is_not_a_prefix_does_not_match(self):
        # "sub" alone is never a candidate: candidates are built as
        # ever-longer prefixes starting from the root, never a bare middle
        # segment on its own.
        self.assertFalse(excluded("fixtures/sub/test_deep.py", ["sub"]))

    def test_excluding_the_top_segment_works_end_to_end(self):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "fixtures", "sub"))
            write(d, "test_ok.py", HONEST)
            write(os.path.join(d, "fixtures", "sub"), "test_deep.py", VACUOUS)
            trimmed = audit(d, exclude=["fixtures"])
        self.assertEqual((trimmed.n_files, trimmed.n_tests), (1, 1))
        self.assertEqual(trimmed.verdict()[0], "PASS")
