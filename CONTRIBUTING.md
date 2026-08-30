# Contributing to SuiteAudit

## The bar

**A false positive is worse than a miss.** A checker that flags honest tests
gets switched off, and a switched-off checker finds nothing. If a rule is
ambiguous about a construct, it says nothing. Roughly half this project's test
suite asserts that good tests are *not* flagged, and that ratio is deliberate —
please keep it.

**Break it first.** A test that has never been observed failing is decoration.
If you add one, break the detector on purpose and confirm the test notices.

**Report what the tool does, not what it should do.** The first real run of this
tool produced false positives against three codebases. That is written into the
README rather than quietly patched, because a project arguing that green suites
are weak evidence has to be willing to say when its own output was wrong.

## Adding a rule

A rule earns its place by answering yes to all four:

1. Can the finding be confirmed by reading the flagged lines, with no other context?
2. Is there a construct that looks similar and must *not* be flagged? Write that test first.
3. Does `suiteaudit explain <rule>` have an honest answer for "when is it fine to ignore this"? Every rule has one.
4. Does it run without executing the code under test?

## Before opening anything

```bash
python -m unittest discover -s tests -v
suiteaudit check tests     # the tool must pass its own audit
ruff check .
```

## DCO, not a CLA

Contributions are accepted under the [Developer Certificate of
Origin](https://developercertificate.org/). Sign off each commit:

```bash
git commit -s -m "your message"
```

A contributor licence agreement needs a named legal entity to assign rights to.
This project is maintained under a pseudonymous account, so the DCO does the
necessary job instead: you assert you have the right to contribute what you are
contributing, under the project's licence.
