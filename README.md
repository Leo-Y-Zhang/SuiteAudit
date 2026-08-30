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
| `tautology` | high | `assert True`, `assertEqual(2, 2)`, `assert x == x` |
| `mock-only` | high | every assertion inspects a mock the test itself built; no production code runs |
| `no-assertion` | medium | runs code but asserts nothing, so it only catches crashes |

`mock-only` is the one that matters. It is the characteristic shape of a
generated test: construct a double, assert the double was called, go green.
No change to the system can break it.

## Use

```
pip install -e .

suiteaudit check .              # audit a project
suiteaudit check . --json       # machine-readable, for CI
suiteaudit explain mock-only    # what a rule means and when to ignore it
suiteaudit verify               # run the tool against itself
```

Exits non-zero on a high-severity finding, so it can gate a pull request.
No dependencies — it has to install in someone else's CI on the first try.

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

## Layout

| file | purpose |
|---|---|
| `src/suiteaudit/detectors.py` | the four rules, AST-only |
| `src/suiteaudit/audit.py` | project walk, verdict, JSON report |
| `src/suiteaudit/__main__.py` | CLI |
| `tests/test_detectors.py` | detection cases, and the false-positive guards |

Roughly half the test suite asserts that honest tests are **not** flagged.
That ratio is deliberate.

## Licence

Apache-2.0. Use it, fork it, ship it inside a commercial product — the licence
asks for attribution and nothing else, and section 3 grants you a patent licence
for it explicitly.

Contributions are taken under the [DCO](https://developercertificate.org/) —
`git commit -s`. See [CONTRIBUTING.md](CONTRIBUTING.md) for the bar a new rule
has to clear.
