# SuiteAudit

A static-analysis tool that reads a Python test suite's AST and reports tests
that cannot fail no matter what the code does (empty-test, tautology,
mock-only, no-assertion), giving a default-deny PASS/WARN/FAIL/NO-DATA verdict
without executing anything. It runs purely on the standard library `ast`
module, has zero runtime dependencies by design (so it installs cleanly in
someone else's CI on code nobody here has seen), and is meant to be pointed at
its own tests as proof it can pass its own audit.

## Directory layout

- `src/suiteaudit/` — the package: `audit.py` (core AST analysis / verdict
  logic), `detectors.py` (the individual finding detectors), `__main__.py`
  (CLI entry point).
- `tests/` — `test_cli.py`, `test_audit.py`, `test_detectors.py`.
- `tools/` — `case_study.py`, which re-clones and re-audits real-world repos
  (requests, click, attrs, django, etc.) to reproduce the README's benchmark
  tables; needs network and is slow (skip in a time-boxed session).
- `action.yml` — composite GitHub Action wrapping the CLI.
- `docs/` — supporting docs (e.g. releasing).
- `.pre-commit-hooks.yaml` — lets other repos use SuiteAudit as a pre-commit
  hook.

## Install

```
python3 -m venv .venv
.venv/bin/pip install -e .
```
Zero runtime dependencies (`dependencies = []` in `pyproject.toml`). For
lint/build tooling: `.venv/bin/pip install -e '.[dev]'` (`ruff`, `build`,
`twine`).

## Lint / format

```
.venv/bin/ruff check .
```
Config: `line-length = 100`, `target-version = "py311"`,
`select = ["E", "F", "I", "UP", "B"]`, `ignore = ["E501"]`. No formatter or
mypy/type-checker is configured.

## Test

Full suite is fast (~0.1s, 160 tests) — just run it all:
```
python -m unittest discover -s tests -v
```
This is CI's exact command. Equivalent and cross-checked: `pytest -q`.
Fastest useful subset — a single file, e.g.:
```
python -m unittest tests.test_audit -v
```
or `pytest tests/test_audit.py -q`.

## Verification gate (source of truth)

The tool auditing its own tests is the gate it holds itself to:
```
suiteaudit check tests
```
(equivalently `.venv/bin/python -m suiteaudit check tests` if the console
script isn't on PATH). A clean run reports `0 of 160 tests carry a finding
(100.0% clean)`, `VERDICT: PASS`, exit 0. CI additionally proves the gate can
go red with three negative tests: a suite of nothing but `assert True` must
FAIL, a file containing only a `# suiteaudit: ignore` comment must still be
NO DATA/fail, and `--exclude` must flip a mixed tree's verdict from fail to
pass.

## Environment caveats (from audit)

- `tools/case_study.py` (both the "first" 3-suite and "second" 8-suite
  reproductions of the README's benchmark tables) needs network access to
  clone real GitHub repos and is slow — the 8-suite "second" run clones
  django/pytest/etc. at depth and comfortably exceeds a 5-minute budget. Skip
  both in a constrained session; only `case_study.py first` is fast enough to
  attempt (~small clones) if network is available.
- No GPU/OS-specific code paths; runs the same on Linux/macOS/Windows.

## CI / conventions

- `ci.yml` `test` job (py3.11 and py3.13 matrix): install, `ruff check .`,
  `python -m unittest discover -s tests -v`, then `suiteaudit check tests`
  (self-audit) and the three red-gate proofs above.
- A separate `wheel` job builds the sdist/wheel, `twine check`s it, and
  smoke-installs it into a fresh venv; an `action` job exercises the
  composite GitHub Action from this checkout.
- `release.yml` (tag-triggered, `v*`) publishes to PyPI via trusted
  publishing (OIDC) — does not run tests.
- No coverage floor is enforced; no mypy/type-checking is configured.
