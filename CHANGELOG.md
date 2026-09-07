# Changelog

All notable changes to SuiteAudit are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/).

## [0.1.0] - 2026-09-07

The first release. Before tagging it, the release candidate was run against the
test suites of three popular Python projects (1,552 tests). It reported 31
high-severity findings and failed two of the three gates. On reading every
flagged line, 30 of the 31 were false positives. That is the failure mode this
project says is worse than a miss, so the two rules responsible were narrowed
and the release was held until they were.

A second measurement against eight more suites (flask, httpx, rich, pydantic,
pytest, django, black, urllib3; 18,107 tests) then found four more shapes that
were flagged wrongly, in 16 of 36 high findings, and the release was held again
until those were fixed. The remaining 20 are empty tests by the rule's
definition: 18 are pytest's own example fixtures (left out with the new
`--exclude`), 2 are Django tests that are empty on purpose so that a
`setUpClass` runs.

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
- `tautology` no longer flags a constant assertion that is false. `assert
  False, "did not raise"` and `assert 0` are fail-markers: reaching the line
  is the failure, so a test that carries one can fail (13 findings across
  rich, pydantic and pytest). The rule now folds the constant itself, never
  through `eval`, and reports only the true ones; an expression that would
  cost real work to fold (`2 ** 10 ** 9`) is left undecided and unreported.
  `assertEqual(2, 3)`, `assertTrue(False)` and their relatives are treated
  the same way.
- `mock-only` no longer takes `httpx.patch(url)` for `mock.patch`. A factory
  name reached through an attribute counts only when the object it hangs off
  is the mock library: `mock`, `unittest.mock`, pytest-mock's `mocker`, or
  whatever name the file imported it under.
- Methods are collected as tests only from classes a test runner would
  collect: `Test*`, `*Test`, `*Tests`, `*TestCase`, or a subclass of a base
  with `Test` in its name (by name, or a class in the same file that is itself
  a test class). A plain helper class with a `test_method` used as fixture
  data in Django's suite is no longer reported. A base imported from
  elsewhere under a name without `Test` in it is not recognised, and its
  methods are missed rather than guessed at.
- `empty-test` is low severity instead of high when the empty body sits
  under a decorator the tool does not know (`@test_mutation(raises=False)` in
  Django wraps the whole test). Markers, skips, patches and settings
  overrides are known and do not lower it.

### Added

- `suiteaudit check --exclude GLOB` (repeatable) leaves out files whose path
  relative to the audited root matches the glob; the action has an `exclude`
  input for the same. Added for pytest's own suite, which keeps deliberately
  empty example tests under `testing/example_scripts/` as fixtures.
- `tools/case_study.py` now re-measures both the three original suites and
  the eight of the second measurement, and prints both README tables.
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
- Two Django tests whose bodies are empty on purpose, so that a mixin's
  `setUpClass` runs, stay flagged as `empty-test`. Their comments say what
  they are for; `# suiteaudit: ignore[empty-test]` says it to the tool.
- pytest's `no-assertion` count is high (501) because its tests check results
  with `result.stdout.fnmatch_lines(...)`, a helper that raises but is not
  named like an assertion. That is a medium finding by design and does not
  fail the gate; recognising project-specific assertion helpers is a
  configuration feature for a later release.

[0.1.0]: https://github.com/Leo-Y-Zhang/SuiteAudit/releases/tag/v0.1.0
