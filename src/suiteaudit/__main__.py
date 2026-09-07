# SPDX-License-Identifier: Apache-2.0
"""SuiteAudit CLI.

  suiteaudit check [PATH ...] [--fail-on high|any|never] [--json]
      Find the tests in each PATH that cannot fail, and say why. Exits
      non-zero when the verdict is FAIL or NO DATA, so it can gate a pull
      request. Several paths are merged into one verdict.

  suiteaudit explain RULE
      What a rule means, why it is worth acting on, and the honest case for
      ignoring it. Every rule has one.

  suiteaudit verify
      Run SuiteAudit's own suite, then run SuiteAudit against it. A tool that
      told you your tests were vacuous while its own were would not deserve a
      hearing. Needs a source checkout.

Exit codes: 0 for PASS (and for WARN unless --fail-on any), 1 for FAIL and
for NO DATA, 2 for a usage error. A finding can be set aside with a comment
`# suiteaudit: ignore[rule]` on the flagged line or on the test's def line;
set-aside findings are counted and reported, never silently dropped.

The claim is narrow on purpose. A test with no finding has not been shown to
work -- only shown not to be obviously incapable of failing. Mutation testing
answers the stronger question, at roughly the cost of running your suite once
per mutant, which is why this exists: the cheap check first, on everything, and
the expensive one afterwards on whatever still looks suspicious.
"""
from __future__ import annotations

import argparse
import os
import sys

from . import __version__
from .detectors import SEVERITY_ORDER

RULE_HELP = {
    "empty-test": (
        "The test body is empty, or contains only a docstring.",
        "It always passes, in every version of the code, forever. It is a "
        "placeholder that reads as coverage.",
        "None. If it is a deliberate placeholder, mark it skipped so that it "
        "reports as skipped rather than as passing.",
    ),
    "tautology": (
        "The assertion's truth is fixed by the language before the code under "
        "test runs: `assert True`, `assertEqual(2, 2)`, `assert x is x`. "
        "`assert x == x` is not flagged: equality calls `__eq__`, which is "
        "user code and can legitimately be false.",
        "It cannot distinguish working code from broken code, which is the "
        "only thing a test is for.",
        "A deliberate smoke check that the test file imports and runs at all. "
        "Rare, and better written as an explicit import test.",
    ),
    "mock-only": (
        "Every assertion in the test inspects a mock the test itself built, "
        "and nothing except mocks, mock factories, assertion helpers and plain "
        "builtins is called.",
        "No production code runs, so no change to the system can break it. "
        "This is the characteristic shape of a machine-written test: a double "
        "is constructed, the double is asserted on, the suite goes green.",
        "A contract test whose only job is that a collaborator is invoked in a "
        "particular way is not flagged as long as the system under test is "
        "actually called. If the rule fires, nothing was.",
    ),
    "no-assertion": (
        "The test runs code but asserts nothing.",
        "It can only fail by raising, so it catches crashes and nothing else. "
        "That is worth something, which is why this is a warning and not a "
        "failure.",
        "Deliberate smoke tests, and tests whose whole purpose is that a call "
        "does not raise. Both are defensible; say so in the test name, or "
        "mark the test `# suiteaudit: ignore[no-assertion]`.",
    ),
}


def cmd_check(args) -> int:
    from .audit import audit_paths, to_json
    result = audit_paths(args.paths)

    if args.json:
        print(to_json(result))
    else:
        _print_report(result, args.limit)

    verdict, _ = result.verdict()
    if args.fail_on == "never":
        return 0
    if args.fail_on == "any":
        return 1 if result.findings or verdict == "NO DATA" else 0
    return 1 if verdict in {"FAIL", "NO DATA"} else 0


def _print_report(result, limit: int) -> None:
    verdict, reason = result.verdict()
    print("SuiteAudit  " + "  ".join(os.path.abspath(p) for p in result.roots))
    print(f"  {result.n_files} test file(s), {result.n_tests} test(s)")
    if result.unparsed:
        print(f"  {len(result.unparsed)} file(s) could NOT be parsed "
              f"and were not checked:")
        for f, e in result.unparsed[:5]:
            print(f"    {f}: {e}")

    findings = sorted(result.findings,
                      key=lambda f: (SEVERITY_ORDER.get(f.severity, 9), f.file, f.line))
    if findings:
        print(f"\n  {'severity':<9} {'rule':<13} {'location':<34} why")
        print(f"  {'-' * 9} {'-' * 13} {'-' * 34} {'-' * 30}")
        for f in findings[:limit]:
            loc = f"{f.file}:{f.line}"
            print(f"  {f.severity:<9} {f.rule:<13} {loc:<34} {f.detail}")
            if f.evidence:
                print(f"  {'':<9} {'':<13} {'':<34} {f.evidence}")
        if len(findings) > limit:
            print(f"  ... and {len(findings) - limit} more "
                  f"(raise --limit to see them)")

    score = result.score
    print()
    if result.suppressed:
        print(f"  {len(result.suppressed)} finding(s) set aside by "
              f"'# suiteaudit: ignore' comments (not counted)")
    if score is not None:
        print(f"  {result.n_failing_tests} of {result.n_tests} tests carry a "
              f"finding ({score:.1%} clean)")
    print(f"  VERDICT: {verdict} - {reason}")
    if verdict == "PASS":
        print("  This means no test was found that obviously cannot fail. It "
              "does not mean the tests are good.")


def cmd_explain(args) -> int:
    rule = args.rule
    if rule not in RULE_HELP:
        print(f"unknown rule: {rule}", file=sys.stderr)
        print(f"known rules: {', '.join(sorted(RULE_HELP))}", file=sys.stderr)
        return 2
    what, why, when_ok = RULE_HELP[rule]
    print(f"{rule}\n")
    print(f"  what it means\n    {what}\n")
    print(f"  why it matters\n    {why}\n")
    print(f"  when it is fine to ignore\n    {when_ok}")
    return 0


def _checkout_root() -> str:
    """The repository root when running from a source tree."""
    return os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))


VERIFY_NEEDS_CHECKOUT = ("verify needs a source checkout of SuiteAudit (its "
                         "tests/ directory is not shipped in the wheel); run "
                         "it from the repository root")


def _verify_preflight(root: str) -> str | None:
    """None when `verify` can run from `root`, else the reason it cannot."""
    if not os.path.isdir(os.path.join(root, "tests")):
        return VERIFY_NEEDS_CHECKOUT
    return None


def cmd_verify(args) -> int:
    """Prove the tool on itself, in the order that actually proves something."""
    import unittest

    from .audit import audit

    here = _checkout_root()
    problem = _verify_preflight(here)
    if problem:
        print(problem, file=sys.stderr)
        return 2
    print("1. SuiteAudit's own test suite")
    suite = unittest.TestLoader().discover(os.path.join(here, "tests"))
    ok = unittest.TextTestRunner(verbosity=1).run(suite)
    if not ok.wasSuccessful():
        return 1

    print("\n2. SuiteAudit audited by SuiteAudit")
    result = audit(os.path.join(here, "tests"))
    verdict, reason = result.verdict()
    print(f"   {result.n_tests} tests, verdict {verdict} - {reason}")
    for f in result.findings:
        print(f"   {f.severity} {f.rule} {f.file}:{f.line} {f.detail}")
    return 0 if verdict == "PASS" else 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="suiteaudit", description=__doc__.split("\n\n")[0],
        formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    p.add_argument("--version", action="version",
                   version=f"suiteaudit {__version__}")
    sub = p.add_subparsers(dest="command")

    c = sub.add_parser("check", help="find tests that cannot fail")
    c.add_argument("paths", nargs="*", default=["."], metavar="PATH",
                   help="files or directories to audit (default: .)")
    c.add_argument("--fail-on", choices=("high", "any", "never"), default="high",
                   help="exit non-zero on: high-severity findings (default), "
                        "any finding, or never; NO DATA always exits non-zero "
                        "unless --fail-on never")
    c.add_argument("--json", action="store_true")
    c.add_argument("--limit", type=int, default=40)
    c.set_defaults(func=cmd_check)

    e = sub.add_parser("explain", help="what a rule means and when to ignore it")
    e.add_argument("rule")
    e.set_defaults(func=cmd_explain)

    sub.add_parser("verify", help="run the tool against itself").set_defaults(
        func=cmd_verify)
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help()
        return 2
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
