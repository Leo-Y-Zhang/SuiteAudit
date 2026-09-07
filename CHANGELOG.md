# Changelog

All notable changes to SuiteAudit are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/).

## [0.1.0] - 2026-09-06

The first release. Before tagging it, the release candidate was run against the
test suites of three popular Python projects (1,552 tests). It reported 31
high-severity findings and failed two of the three gates. On reading every
flagged line, 30 of the 31 were false positives. That is the failure mode this
project says is worse than a miss, so the two rules responsible were narrowed
and the release was held until they were.

### Changed

- `tautology` no longer flags `x == x`, `assertEqual(x, x)`, `C(1) == C(1)`,
  `hash(a) == hash(a)` or `list(k) == list(k)`. Equality calls `__eq__`, which
  is user code: float NaN is not equal to itself, and a project that generates
  `__eq__` tests exactly that reflexivity (26 of the 30 false positives). The
  rule now stops at what the language guarantees: constant expressions, and a
  bare name compared to itself with `is` (`assert x is x`, `assertIs(x, x)`).
- `tautology` is high severity only when every assertion in the test is a
  tautology, since only then can the test not fail. A dead `assert True`
  beside real assertions is reported at low severity and no longer fails the
  gate (it did, on `assert e1 is e1` in a test that went on to make real
  assertions).
- The `WARN` reason now covers low findings as well as `no-assertion`.
- `mock-only` now also requires that the test body calls nothing except mocks,
  mock factories, assertion helpers and plain builtins. A test that hands a
  mock to the system under test and then asserts the collaborator was called
  is a contract test; the previous rule looked only at the assertions and
  flagged one such test in a popular HTTP library.

### Added

- `# suiteaudit: ignore[rule]` (or `# suiteaudit: ignore`) on a test's `def`
  line or on the flagged line sets that finding aside. Set-aside findings are
  counted and listed in the report and the JSON (`suppressed_count`,
  `suppressed`); they never enter the verdict, and no suppression can turn
  NO DATA into PASS.
- `suiteaudit check` accepts several paths and merges them into one verdict,
  so pre-commit can pass it the changed test files.
- `suiteaudit --version`.
- `.pre-commit-hooks.yaml`, so the tool can be used as a pre-commit hook.
- `action.yml`, so the tool can be used as a GitHub Action.
- A release workflow that publishes to PyPI with trusted publishing.
- Tests for the project walk and the command line (the exit-code contract).

### Fixed

- A test file that was not UTF-8 crashed the whole run with a traceback.
  It is now recorded under `unparsed`, like a syntax error, and the other
  files are still checked. Source containing null bytes is handled the same
  way.
- `suiteaudit verify` from a wheel install raised `ImportError`; it now says
  that it needs a source checkout and exits 2.
- Four regression tests sat below the `if __name__ == "__main__"` guard in the
  test module and were skipped when the file was run directly.

### Not fixed, on purpose

- The remaining true positive from the release-candidate run (a test whose
  body is a docstring and nothing else) is exactly what `empty-test` exists
  for. It stays flagged.

[0.1.0]: https://github.com/Leo-Y-Zhang/SuiteAudit/releases/tag/v0.1.0
