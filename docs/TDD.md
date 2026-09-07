# TDD: SuiteAudit 0.1.0

Technical design for the first installable release. The PRD is `PRD.md`; the
owner's release steps are `RELEASING.md`.

## What the release candidate measured (commit f96403d, 6 Sep 2026)

Three popular suites at pinned commits, audited with the 30 Aug code:

| suite | commit | tests | findings | high | verdict |
|---|---|---|---|---|---|
| psf/requests | dae7ef6 | 347 | 14 | 4 | FAIL |
| pallets/click | 36baa15 | 538 | 3 | 0 | WARN |
| python-attrs/attrs | 8f76777 | 667 | 71 | 27 | FAIL |

Of the 31 high findings, 30 were false on reading: 26 `tautology` findings of
the shape `C(1) == C(1)` / `hash(a) == hash(a)` / `i == i` (attrs tests its
generated `__eq__` and `__hash__`), 3 more of the same shape in requests, and 1
`mock-only` finding on a requests test that patched a collaborator, called the
real function, and asserted on the patch. The one true positive: attrs
`test_hash_deprecated`, a docstring-only body.

## Design decisions

1. **Tautology stops at what the language guarantees.** `x == x` calls
   `__eq__` (user code; false for NaN; the thing attrs tests), so it is not a
   tautology. `x is x` on a bare name is: identity is reflexive by the
   definition of `is`. `f(1) is f(1)`, `a.b is a.b` and `x[0] is x[0]` are not
   flagged either, because a call, a property or `__getitem__` may run and may
   return different objects. Implemented by replacing `_same_expression`
   (structural equality of the two ASTs) with `_same_name` (both sides one
   `ast.Name` with the same id) and applying it only to `is` / `assertIs`.
2. **Tautology severity depends on the whole test.** A test whose every
   assertion is fixed cannot fail: high. A dead `assert True` beside real
   assertions cannot make the test un-failable: low, with the reason in the
   detail. Found by the release candidate on attrs `test_auto_exc`
   (`assert e1 is e1` followed by real assertions), which would otherwise have
   failed attrs' gate on a true-but-harmless finding.
3. **Mock-only requires that nothing else was called.** `_calls_outside_mocks`
   walks the body statements (not the decorators) and returns true on any call
   whose root is not a mock variable, a mock factory, an assertion helper on
   `self`, or a plain builtin (`BUILTIN_CALLS`). If it returns true the rule
   says nothing: production code may have run, so the test may be a contract
   test. The same builtin list makes `len(m.calls)` count as touching only the
   mock inside an assertion.
4. **Suppression is a comment token, never a string.** `_suppressions` uses
   `tokenize` so `"# suiteaudit: ignore"` inside a string literal does not
   count. Findings suppressed on the flagged line or the test's `def` line go
   to `FileReport.suppressed`, are summed into `AuditResult.suppressed`, appear
   in the JSON as `suppressed` and `suppressed_count`, and never touch the
   verdict. NO DATA is decided before findings are consulted, so no comment
   can turn it into PASS.
5. **`analyse_file` is the new entry point; `analyse_source` stays.** The old
   `(findings, n_tests)` tuple is what the existing tests and any early
   adopter import, so it is kept as a wrapper.
6. **Several paths merge.** `audit_paths` merges `AuditResult`s (findings,
   suppressed, counts, unparsed, roots). `check` takes `nargs="*"` so
   pre-commit can pass filenames.
7. **No traceback reaches a user.** `audit()` records `UnicodeDecodeError` and
   `ValueError` (null bytes) under `unparsed` alongside `SyntaxError`.
   `verify` checks for `tests/` first and exits 2 with one line.
8. **Version has one source.** `pyproject.toml`; `__init__` reads it through
   `importlib.metadata`, falling back to `0.0.0+uninstalled` from a bare
   source tree. `--version` is argparse's version action.
9. **Release without a stored secret.** `release.yml` publishes through PyPI
   trusted publishing in a `pypi` environment with `id-token: write`; the tag
   must equal `v<version>` or the build job fails before anything is built.

## Test plan and evidence

Every new behaviour has a test that was observed not passing against the
old code before the fix was written.

- **Differential, old detectors vs new** (script in the session scratchpad,
  old module loaded from `git show f96403d:src/suiteaudit/detectors.py`):

  | case | old | new |
  |---|---|---|
  | `C(1) == C(1)` | tautology | (none) |
  | `hash(C(1)) == hash(C(1))` | tautology | (none) |
  | `list(keys) == list(keys)` | tautology | (none) |
  | `for i in items: assert i == i` | tautology | (none) |
  | `assertEqual(got, got)` | tautology | (none) |
  | contract test: `notify(sender, ..)` then `sender.send.assert_called_once_with(..)` | mock-only | (none) |
  | `with patch(..) as m:` calling the SUT inside | mock-only | (none) |
  | `assert got is got` | tautology | tautology |
  | mock built, called, asserted on, nothing else | mock-only | mock-only |
  | `assert True` | tautology | tautology |

- **New test modules against the old `src/` (via `git stash push -- src/`):**
  `Ran 16 tests ... FAILED (failures=3, errors=5)`; the detector module's new
  imports made `test_detectors.py` and `test_audit.py` fail to load at all.
- **Gate on the new code:** `ruff check .` clean; `python -m unittest discover
  -s tests` -> `Ran 88 tests ... OK` (was 33); `suiteaudit check tests` ->
  `PASS`, 88 tests; `assert True` suite -> exit 1; ignore-comment-only file
  -> exit 1 (NO DATA); `python -m build` -> wheel + sdist, `twine check`
  PASSED both; fresh venv `pip install dist/*.whl` -> `suiteaudit 0.1.0`,
  `check tests` PASS, `verify` from outside the checkout -> exit 2 with the
  one-line message.
- **The three suites, after the fix:**

  | suite | tests | findings | high | low | verdict |
  |---|---|---|---|---|---|
  | requests | 347 | 10 (all no-assertion) | 0 | 0 | WARN |
  | click | 538 | 3 (all no-assertion) | 0 | 0 | WARN |
  | attrs | 667 | 46 | 1 | 1 | FAIL |

  The one high finding is the true positive (`test_hash_deprecated`,
  docstring-only). The one low finding is `assert e1 is e1` in
  `test_auto_exc`. Zero false high findings, which was the acceptance bar.

- **Positive / negative / boundary coverage:** `tests/test_detectors.py`
  (rules fire; every false-positive shape above does not; suppression per
  rule, all rules, wrong rule, string literal, other test), `tests/test_audit.py`
  (NO DATA on empty dir and on test-less file; latin-1 and null-byte files
  recorded not fatal; syntax error recorded; two paths merge; zero paths NO
  DATA; suppression counted, wrong-rule suppression still FAIL, comment-only
  file NO DATA), `tests/test_cli.py` (exit codes for PASS/WARN/FAIL/NO DATA
  under each `--fail-on`; two paths; JSON `suppressed_count`; `--version`;
  `verify` preflight; `explain` for every rule).

## CI

`test` (3.11 and 3.13): lint, unit tests, audit itself, prove the gate goes
red on `assert True`, prove an ignore-only file is NO DATA. `wheel`: build,
twine check, fresh-venv install and run, `verify` from the wheel must exit 2
with the message. `action`: the composite action from this checkout
(`source: local`) audits `tests`. Each proving step was observed failing when
its condition was inverted during development (exit code checks flipped).

## Rollback

A bad release is yanked on PyPI (`pip install suiteaudit==0.1.0` then refuses
by default; pinned installs still resolve) and the GitHub release is marked
pre-release or deleted; the tag is left in place so the history is honest. A
bad rule change is reverted by commit; the differential script above is the
regression check.

## Open questions

- `assertEqual(x, x)` and `assert x == x` are now silent. If a project wants
  them flagged, that is a new opt-in rule, not a reversal.
- SARIF and a baseline file are deferred until a user asks.
