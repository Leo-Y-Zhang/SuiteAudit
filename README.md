# SuiteAudit

Find the tests that cannot fail.

A test suite goes green. That is evidence of nothing until you know the tests
were capable of going red. SuiteAudit reads a suite and reports the tests that
could not have failed whatever the code did — and it does it from the syntax
tree, in milliseconds, without running anything.

## Why now

84% of developers use or plan to use AI coding tools, and 51% of professional
developers use them daily.[^so] Only 3.1% highly trust the output.

They are right not to. Veracode tested over 100 models on 80 coding tasks across
four languages and found **45% of the generated code introduced a known security
flaw** — a rate that has not improved as the models have.[^vc] A comparison of
over 500,000 Python and Java samples found LLM-written code simpler and more
repetitive than human-written code, but carrying **more high-risk
vulnerabilities**.[^cc]

The assistant also wrote the tests. That is the part nobody is checking. A
machine optimising for a green suite learns the cheapest route to green, and the
cheapest route is a mock asserting on itself.

[^so]: [Stack Overflow Developer Survey 2025 — AI](https://survey.stackoverflow.co/2025/ai), n = 33,662.
[^vc]: [Veracode, *2025 GenAI Code Security Report*](https://www.veracode.com/blog/ai-generated-code-security-risks/).
[^cc]: Cotroneo, Improta & Liguori, [*Human-Written vs. AI-Generated Code: A Large-Scale Study of Defects, Vulnerabilities, and Complexity*](https://arxiv.org/abs/2508.21634), arXiv:2508.21634, 2025.

## What it finds

| rule | severity | what it means |
|---|---|---|
| `empty-test` | high | body is empty or a docstring; always passes |
| `tautology` | high, or low beside real assertions | `assert True`, `assertEqual(2, 2)`, `assert x is x` |
| `mock-only` | high | every assertion inspects a mock the test itself built, and nothing but mocks and builtins is called; no production code runs |
| `no-assertion` | medium | runs code but asserts nothing, so it only catches crashes |

`mock-only` is the one that matters. It is the characteristic shape of a
generated test: construct a double, assert the double was called, go green.
No change to the system can break it.

`assert x == x` is deliberately not a tautology here. Equality calls `__eq__`,
which is user code and can be false (float NaN is not equal to itself), and a
project that generates `__eq__` tests exactly that. See "The release candidate
found two more" below.

## Use

```
pip install suiteaudit

suiteaudit check .              # audit a project
suiteaudit check tests/ lib/    # several paths, one verdict
suiteaudit check . --json       # machine-readable, for CI
suiteaudit explain mock-only    # what a rule means and when to ignore it
suiteaudit verify               # run the tool against itself (source checkout)
```

No dependencies — it has to install in someone else's CI on the first try.

### Exit codes

| exit | when |
|---|---|
| 0 | `PASS`, or `WARN` (medium and low findings only) unless `--fail-on any` |
| 1 | `FAIL` (a high-severity finding), or `NO DATA` (nothing was checked) |
| 2 | usage error |

`--fail-on never` always exits 0 and just reports. `NO DATA` fails by default
on purpose: a gate that passes because it found nothing to check is the
failure mode this tool exists to name.

### Setting a finding aside

```python
def test_collaborator_contract():  # suiteaudit: ignore[mock-only]
    ...
```

The comment goes on the test's `def` line or on the flagged line, and takes a
rule name, a comma-separated list, or nothing (every rule). Set-aside findings
are counted and listed in the report and in the JSON (`suppressed_count`,
`suppressed`), never silently dropped, and no suppression can turn `NO DATA`
into `PASS`.

### pre-commit

```yaml
repos:
  - repo: https://github.com/Leo-Y-Zhang/SuiteAudit
    rev: v0.1.0
    hooks:
      - id: suiteaudit
```

Only the changed test files are passed to the hook.

### GitHub Actions

```yaml
- uses: Leo-Y-Zhang/SuiteAudit@v0.1.0
  with:
    path: tests          # default: .
    fail-on: high        # high (default), any, never
```

## What it does not claim

A test with no finding has **not** been shown to work. It has been shown not to
be obviously incapable of failing. That is a weaker claim and the distinction is
the whole point: mutation testing answers the stronger question, at roughly the
cost of running your suite once per mutant, which is why almost nobody runs it.

This is the cheap check, on everything, first. The expensive one belongs
afterwards, on whatever still looks suspicious.

A run that parsed nothing reports `NO DATA`, never `PASS`. An empty result and a
clean result look identical otherwise, and that is exactly how a broken checker
goes unnoticed for months.

## The first real run found a bug in this tool

Pointed at three numeric codebases, it reported their tests as assertion-free.
They were not: they used `np.testing.assert_allclose` and `assert_array_equal`,
and the detector only knew unittest's assertion names — so numpy's entire
assertion family read as "not an assertion".

That is the failure mode that kills tools like this. A checker that cries wolf
gets switched off, and a switched-off checker finds nothing. Any callable named
`assert*` now counts, and four regression tests pin it.

Recorded here rather than quietly fixed, because a tool arguing that green
suites are weak evidence should be willing to say when its own output was wrong.

## The release candidate found two more

Before the first release, the tool was run against the test suites of three
popular Python projects: 1,552 tests. It reported 31 high-severity findings and
failed two of the three gates. Reading every flagged line, **30 of the 31 were
false positives**, from two rules:

- `tautology` flagged `C(1) == C(1)`, `hash(a) == hash(a)`, `i == i` and their
  relatives (26 findings, one project). Every one tests the project's own
  `__eq__` or `__hash__`. The rule now stops at what the language guarantees:
  constants, and `x is x`.
- `mock-only` flagged a test that patched a collaborator, **called the real
  function**, and then asserted the collaborator was used (a contract test).
  The rule looked only at the assertions. It now also requires that nothing
  except mocks, mock factories, assertion helpers and builtins was called.

The one true positive was a test whose body was a docstring. That is what
`empty-test` is for, and it stays flagged. The details are in
[CHANGELOG.md](CHANGELOG.md); the regression tests for every shape above are
in `tests/test_detectors.py`.

The same three suites after the fix, as printed by `python tools/case_study.py`
(it re-clones the pinned commits and re-measures, so the table can be checked
rather than believed):

| suite | commit | tests | findings | high | low | verdict |
|---|---|---|---|---|---|---|
| psf/requests | `dae7ef6` | 347 | 10 | 0 | 0 | WARN |
| pallets/click | `36baa15` | 538 | 3 | 0 | 0 | WARN |
| python-attrs/attrs | `8f76777` | 667 | 46 | 1 | 1 | FAIL |

Every remaining medium finding is `no-assertion` (a test that only catches
crashes). The one high finding is the docstring-only test. The one low finding
is `assert e1 is e1` inside a test that goes on to make real assertions: a dead
assertion, reported as such, and not a reason to fail a gate.

## Layout

| file | purpose |
|---|---|
| `src/suiteaudit/detectors.py` | the four rules and the suppression comments, AST-only |
| `src/suiteaudit/audit.py` | project walk, verdict, JSON report |
| `src/suiteaudit/__main__.py` | CLI |
| `tests/test_detectors.py` | detection cases, and the false-positive guards |
| `tests/test_audit.py` | the walk and the verdict: unparseable files, several paths, suppression |
| `tests/test_cli.py` | the exit-code contract |
| `action.yml`, `.pre-commit-hooks.yaml` | the GitHub Action and the pre-commit hook |
| `.github/workflows/release.yml` | tag-driven build, check and publish to PyPI (trusted publishing) |

Roughly half the test suite asserts that honest tests are **not** flagged.
That ratio is deliberate.

## Licence

Apache-2.0. Use it, fork it, ship it inside a commercial product — the licence
asks for attribution and nothing else, and section 3 grants you a patent licence
for it explicitly.

Contributions are taken under the [DCO](https://developercertificate.org/) —
`git commit -s`. See [CONTRIBUTING.md](CONTRIBUTING.md) for the bar a new rule
has to clear.
