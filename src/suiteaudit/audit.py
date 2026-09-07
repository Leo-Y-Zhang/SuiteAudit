# SPDX-License-Identifier: Apache-2.0
"""Walk a project, analyse its tests, and return a verdict.

The verdict is default-deny in one specific sense: a suite is not called sound
because nothing was found, it is called sound because tests were found, parsed,
and checked. A run that parsed nothing reports that, rather than a clean bill
of health -- an empty result and a passing result look identical otherwise, and
that is exactly how a broken checker goes unnoticed.
"""
from __future__ import annotations

import json
import os
from collections.abc import Iterable
from dataclasses import dataclass, field

from .detectors import Finding, analyse_file

DEFAULT_SKIP = {".git", ".venv", "venv", "__pycache__", "node_modules",
                ".tox", ".mypy_cache", ".pytest_cache", ".ruff_cache",
                "build", "dist", "site-packages", ".eggs"}


@dataclass
class AuditResult:
    findings: list[Finding] = field(default_factory=list)
    suppressed: list[Finding] = field(default_factory=list)
    n_tests: int = 0
    n_files: int = 0
    unparsed: list[tuple[str, str]] = field(default_factory=list)
    roots: list[str] = field(default_factory=list)

    @property
    def n_failing_tests(self) -> int:
        return len({(f.file, f.test) for f in self.findings})

    @property
    def high(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "high"]

    @property
    def score(self) -> float | None:
        """Share of tests with no finding against them. None if nothing parsed.

        Deliberately not called a pass rate: a test with no finding has not
        been proven to work, only found not to be obviously vacuous.
        """
        if self.n_tests == 0:
            return None
        return 1.0 - (self.n_failing_tests / self.n_tests)

    def verdict(self) -> tuple[str, str]:
        """Suppressed findings never enter the verdict, and a suppression can
        never turn NO DATA into anything else: the two NO DATA checks come
        first and look only at what was parsed."""
        if self.n_files == 0:
            return "NO DATA", "no test files were found to analyse"
        if self.n_tests == 0:
            return "NO DATA", f"{self.n_files} file(s) parsed, but no tests in them"
        if self.high:
            return "FAIL", (f"{len(self.high)} test(s) cannot fail for any "
                            f"reason to do with the code under test")
        if self.findings:
            return "WARN", (f"{self.n_failing_tests} test(s) carry a finding "
                            f"below high severity: they assert nothing, or "
                            f"carry a dead assertion beside real ones")
        return "PASS", (f"all {self.n_tests} tests carry an assertion that "
                        f"depends on the system under test")

    def as_dict(self) -> dict:
        verdict, reason = self.verdict()
        return {
            "verdict": verdict, "reason": reason,
            "files_analysed": self.n_files, "tests_found": self.n_tests,
            "tests_with_findings": self.n_failing_tests,
            "score": self.score,
            "unparsed": [{"file": f, "error": e} for f, e in self.unparsed],
            "findings": [f.as_dict() for f in self.findings],
            "suppressed_count": len(self.suppressed),
            "suppressed": [f.as_dict() for f in self.suppressed],
        }

    def merge(self, other: AuditResult) -> None:
        self.findings.extend(other.findings)
        self.suppressed.extend(other.suppressed)
        self.n_tests += other.n_tests
        self.n_files += other.n_files
        self.unparsed.extend(other.unparsed)
        self.roots.extend(other.roots)


def looks_like_tests(path: str) -> bool:
    base = os.path.basename(path)
    return base.startswith("test_") or base.endswith("_test.py")


def iter_test_files(root: str, skip: set[str] | None = None):
    skip = skip or DEFAULT_SKIP
    if os.path.isfile(root):
        yield root
        return
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in skip]
        for name in sorted(filenames):
            if name.endswith(".py") and looks_like_tests(name):
                yield os.path.join(dirpath, name)


def audit(root: str, skip: set[str] | None = None) -> AuditResult:
    """Audit one file or directory tree."""
    result = AuditResult(roots=[root])
    for path in iter_test_files(root, skip):
        shown = os.path.relpath(path, root) if os.path.isdir(root) else path
        try:
            with open(path, encoding="utf-8") as fh:
                source = fh.read()
        except OSError as exc:
            result.unparsed.append((path, str(exc)))
            continue
        except UnicodeDecodeError as exc:
            # A file that is not UTF-8 is a file the tool did not check, and
            # the report says so. It is not a reason to abandon every other
            # file in the run.
            result.unparsed.append((path, f"not utf-8: {exc}"))
            continue
        try:
            report = analyse_file(source, shown)
        except SyntaxError as exc:
            # Recorded, never swallowed. A file that failed to parse is not a
            # file with no problems.
            result.unparsed.append((path, f"syntax error: {exc}"))
            continue
        except ValueError as exc:
            # ast.parse raises ValueError for source containing null bytes.
            result.unparsed.append((path, f"unparseable: {exc}"))
            continue
        result.findings.extend(report.findings)
        result.suppressed.extend(report.suppressed)
        result.n_tests += report.n_tests
        result.n_files += 1
    return result


def audit_paths(paths: Iterable[str], skip: set[str] | None = None) -> AuditResult:
    """Audit several files or trees and merge the results into one verdict."""
    total = AuditResult()
    for path in paths:
        total.merge(audit(path, skip))
    return total


def to_json(result: AuditResult, indent: int = 1) -> str:
    return json.dumps(result.as_dict(), indent=indent)
