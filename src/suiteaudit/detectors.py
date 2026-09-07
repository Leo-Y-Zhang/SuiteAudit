# SPDX-License-Identifier: Apache-2.0
"""Find tests that cannot fail.

Mutation testing answers this properly but pays for the answer by running the
suite once per mutant, which is why almost nobody runs it. Most lying tests do
not need that: they can be identified from the syntax tree alone, in
milliseconds, because the reason they cannot fail is written down in them.

The four shapes below cover the failure modes that matter, and the third is the
one that matters most in 2026: a test that builds a mock, hands it to nothing,
and then asserts on the mock. It exercises no system code at all. Assistants
produce this constantly, because a passing test is the reward signal and a mock
always passes.

Every detector here is written to be quiet rather than thorough. A linter that
cries wolf gets switched off, and a switched-off linter finds nothing, so where
a construct is ambiguous the rule is to say nothing.
"""
from __future__ import annotations

import ast
import io
import re
import tokenize
from dataclasses import dataclass, field

# Names that construct a test double. Matching on the constructor rather than
# on a naming convention: `client = MagicMock()` is a mock whatever it is
# called, and a variable called `mock_total` holding a real integer is not.
MOCK_FACTORIES = frozenset({
    "Mock", "MagicMock", "AsyncMock", "NonCallableMock", "NonCallableMagicMock",
    "create_autospec", "patch", "mock_open", "sentinel", "PropertyMock",
    "stub", "fake", "Spy", "Stub", "Fake",
})

# Assertion helpers that carry a real expectation about behaviour.
UNITTEST_ASSERTIONS = frozenset({
    "assertEqual", "assertNotEqual", "assertTrue", "assertFalse", "assertIs",
    "assertIsNot", "assertIsNone", "assertIsNotNone", "assertIn", "assertNotIn",
    "assertIsInstance", "assertNotIsInstance", "assertRaises", "assertRaisesRegex",
    "assertAlmostEqual", "assertNotAlmostEqual", "assertGreater", "assertGreaterEqual",
    "assertLess", "assertLessEqual", "assertCountEqual", "assertListEqual",
    "assertDictEqual", "assertSetEqual", "assertTupleEqual", "assertMultiLineEqual",
    "assertSequenceEqual", "assertWarns", "assertLogs", "assertNoLogs",
    "assertRegex", "assertNotRegex", "fail",
})

# Assertions that only inspect a mock's own call record. They verify that the
# test called the mock, which the test did, so they cannot fail for any reason
# to do with the code under test.
MOCK_SELF_ASSERTIONS = frozenset({
    "assert_called", "assert_called_once", "assert_called_with",
    "assert_called_once_with", "assert_any_call", "assert_has_calls",
    "assert_not_called", "assert_awaited", "assert_awaited_once",
    "assert_awaited_with", "assert_awaited_once_with",
})

# Builtins that cannot be the system under test. Calling one of these in a
# test body is not evidence that production code ran.
BUILTIN_CALLS = frozenset({
    "len", "str", "int", "float", "bool", "list", "dict", "set", "tuple",
    "frozenset", "range", "print", "isinstance", "issubclass", "getattr",
    "hasattr", "sorted", "reversed", "enumerate", "zip", "min", "max", "sum",
    "abs", "any", "all", "iter", "next", "repr", "type", "id", "format",
    "round", "map", "filter", "bytes", "bytearray", "divmod", "hash",
})

SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}

# `# suiteaudit: ignore` or `# suiteaudit: ignore[rule, rule]` on the flagged
# line or on the test's `def` line. Matched on real comment tokens, never on
# the text of a string literal.
SUPPRESS_RE = re.compile(r"#\s*suiteaudit:\s*ignore(?:\[([^\]]*)\])?")


@dataclass
class Finding:
    """One reason a test cannot fail."""
    rule: str
    severity: str
    test: str
    file: str
    line: int
    detail: str
    evidence: str = ""

    def as_dict(self) -> dict:
        return {
            "rule": self.rule, "severity": self.severity, "test": self.test,
            "file": self.file, "line": self.line, "detail": self.detail,
            "evidence": self.evidence,
        }


@dataclass
class TestFunction:
    name: str
    node: ast.FunctionDef | ast.AsyncFunctionDef
    file: str
    class_name: str | None = None

    @property
    def qualified(self) -> str:
        return f"{self.class_name}.{self.name}" if self.class_name else self.name


@dataclass
class SuiteReport:
    findings: list[Finding] = field(default_factory=list)
    n_tests: int = 0
    n_files: int = 0

    @property
    def failing_tests(self) -> set[str]:
        return {f"{f.file}::{f.test}" for f in self.findings}

    def sorted_findings(self) -> list[Finding]:
        return sorted(self.findings,
                      key=lambda f: (SEVERITY_ORDER.get(f.severity, 9),
                                     f.file, f.line))


def _is_test(node) -> bool:
    return (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name.startswith("test"))


def collect_tests(tree: ast.AST, path: str) -> list[TestFunction]:
    out: list[TestFunction] = []
    for node in tree.body:
        if _is_test(node):
            out.append(TestFunction(node.name, node, path))
        elif isinstance(node, ast.ClassDef):
            for sub in node.body:
                if _is_test(sub):
                    out.append(TestFunction(sub.name, sub, path, node.name))
    return out


def _calls(node: ast.AST):
    for n in ast.walk(node):
        if isinstance(n, ast.Call):
            yield n


def _attr_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Name):
        return node.id
    return None


def _root_name(node: ast.AST) -> str | None:
    """The leftmost name of a dotted expression: a.b.c() -> 'a'."""
    while isinstance(node, (ast.Attribute, ast.Subscript, ast.Call)):
        node = node.value if isinstance(node, (ast.Attribute, ast.Subscript)) \
            else node.func
    return node.id if isinstance(node, ast.Name) else None


def _is_assertion_name(name: str | None) -> bool:
    """Does a callable's name mark it as an assertion?

    The prefix test matters more than the whitelist. numpy, pandas and most
    scientific libraries expose `assert_allclose`, `assert_array_equal`,
    `assert_frame_equal` and dozens more, and a checker that knows only
    unittest's names declares all of them "not an assertion". That was not a
    hypothetical: the first real run of this tool reported false positives
    against three numeric codebases for exactly that reason, which is how a
    checker earns the reputation that gets it switched off.
    """
    if not name:
        return False
    return (name in UNITTEST_ASSERTIONS
            or name in MOCK_SELF_ASSERTIONS
            or name.startswith("assert"))


def _assertion_nodes(fn) -> list[ast.AST]:
    """Every real assertion in a test: bare `assert`, any assert-named helper
    from any library, and pytest.raises/warns."""
    found: list[ast.AST] = []
    for n in ast.walk(fn):
        if isinstance(n, ast.Assert):
            found.append(n)
        elif isinstance(n, ast.Call):
            name = _attr_name(n.func)
            if _is_assertion_name(name):
                found.append(n)
            elif name in {"raises", "warns", "deprecated_call"}:
                # pytest.raises(...) as a context manager is a real expectation
                found.append(n)
    return found


def _mock_variables(fn) -> set[str]:
    """Names bound to a test double inside this test.

    Only direct construction counts. Something returned from a fixture or an
    argument is not assumed to be a mock, because guessing there is how a
    detector starts producing findings nobody believes.
    """
    names: set[str] = set()
    for node in ast.walk(fn):
        targets = []
        value = None
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        elif isinstance(node, ast.withitem) and node.optional_vars is not None:
            targets, value = [node.optional_vars], node.context_expr
        if value is None:
            continue
        if not isinstance(value, ast.Call):
            continue
        factory = _attr_name(value.func)
        if factory not in MOCK_FACTORIES:
            continue
        for t in targets:
            if isinstance(t, ast.Name):
                names.add(t.id)
            elif isinstance(t, ast.Tuple):
                names.update(e.id for e in t.elts if isinstance(e, ast.Name))
    return names


def _is_constant_expr(node: ast.AST) -> bool:
    """True when an expression's value cannot depend on anything under test."""
    if isinstance(node, ast.Constant):
        return True
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        return all(_is_constant_expr(e) for e in node.elts)
    if isinstance(node, ast.Dict):
        # ast.Dict guarantees keys and values are the same length -- a `**x`
        # entry contributes a None key rather than a missing one -- so strict
        # documents the invariant instead of hiding a mismatch.
        return all(_is_constant_expr(k) and _is_constant_expr(v)
                   for k, v in zip(node.keys, node.values, strict=True)
                   if k is not None)
    if isinstance(node, ast.BinOp):
        return _is_constant_expr(node.left) and _is_constant_expr(node.right)
    if isinstance(node, ast.UnaryOp):
        return _is_constant_expr(node.operand)
    if isinstance(node, ast.Compare):
        return (_is_constant_expr(node.left)
                and all(_is_constant_expr(c) for c in node.comparators))
    return False


def _same_name(a: ast.AST, b: ast.AST) -> bool:
    """Both sides are the same plain variable.

    Only a bare name qualifies. `f(1) is f(1)` runs `f` twice and may well get
    two objects; `a.b is a.b` may run a property; `x[0] is x[0]` runs
    `__getitem__`. Each of those is user code and can legitimately differ, so
    none of them is a tautology.
    """
    return isinstance(a, ast.Name) and isinstance(b, ast.Name) and a.id == b.id


def _calls_outside_mocks(fn, mocks: set[str], assertions: list[ast.AST]) -> bool:
    """Does the test body call anything that is not a mock, a mock factory, an
    assertion helper or a plain builtin?

    If it does, production code may have run, and an assertion on the mock
    afterwards may be a genuine contract test. Decorators are not scanned:
    `@pytest.mark.parametrize` is not production code either.
    """
    assertion_ids = {id(a) for a in assertions}
    for stmt in fn.body:
        for n in ast.walk(stmt):
            if not isinstance(n, ast.Call) or id(n) in assertion_ids:
                continue
            name = _attr_name(n.func)
            root = _root_name(n.func)
            if name in MOCK_FACTORIES or root in MOCK_FACTORIES:
                continue
            if root in mocks:
                continue
            if root == "self" and _is_assertion_name(name):
                continue
            if isinstance(n.func, ast.Name) and n.func.id in BUILTIN_CALLS:
                continue
            return True
    return False


def _suppressions(source: str) -> dict[int, frozenset[str] | None]:
    """Line number -> rules suppressed there (None means every rule)."""
    out: dict[int, frozenset[str] | None] = {}
    try:
        for tok in tokenize.generate_tokens(io.StringIO(source).readline):
            if tok.type != tokenize.COMMENT:
                continue
            m = SUPPRESS_RE.match(tok.string)
            if not m:
                continue
            spec = m.group(1)
            if spec is None or not spec.strip():
                out[tok.start[0]] = None
            else:
                out[tok.start[0]] = frozenset(
                    r.strip() for r in spec.split(",") if r.strip())
    except (tokenize.TokenError, SyntaxError):
        # The source already parsed as Python, so this is a tokenizer corner
        # case; treating it as "no suppressions" is the conservative reading.
        pass
    return out


def _is_suppressed(finding: Finding, test: TestFunction,
                   sup: dict[int, frozenset[str] | None]) -> bool:
    for line in (finding.line, test.node.lineno):
        if line in sup:
            rules = sup[line]
            if rules is None or finding.rule in rules:
                return True
    return False


# ---------------------------------------------------------------- detectors

def detect_no_assertion(test: TestFunction) -> list[Finding]:
    """A test that asserts nothing.

    Only reports when the body does something, since an empty or `pass` body is
    caught by the stronger rule below. A test that merely calls the system is
    still a smoke test -- it fails if the call raises -- so this is medium, not
    high, and says so.
    """
    fn = test.node
    if _assertion_nodes(fn):
        return []
    body = [s for s in fn.body if not isinstance(s, ast.Pass)]
    body = [s for s in body
            if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant))]
    if not body:
        return []
    return [Finding(
        rule="no-assertion", severity="medium", test=test.qualified,
        file=test.file, line=fn.lineno,
        detail="runs code but asserts nothing; it can only fail by raising",
        evidence=f"{len(body)} statement(s), 0 assertions")]


def detect_empty_test(test: TestFunction) -> list[Finding]:
    """A test whose body does nothing at all. It cannot fail, ever."""
    fn = test.node
    meaningful = [s for s in fn.body
                  if not isinstance(s, ast.Pass)
                  and not (isinstance(s, ast.Expr)
                           and isinstance(s.value, ast.Constant))]
    if meaningful:
        return []
    return [Finding(
        rule="empty-test", severity="high", test=test.qualified,
        file=test.file, line=fn.lineno,
        detail="body is empty or only a docstring; this test always passes",
        evidence="no executable statements")]


def detect_tautology(test: TestFunction) -> list[Finding]:
    """Assertions whose truth is fixed by the language before any code under
    test runs: `assert True`, `assert 1 == 1`, `assertEqual(2, 2)`,
    `assert x is x`.

    `assert x == x` is deliberately NOT here. Equality calls `x.__eq__`, which
    is user code and can legitimately return False (float NaN does), and a
    project that generates `__eq__` tests exactly that reflexivity. The first
    release candidate flagged 26 such assertions in one popular suite and
    failed its gate; the rule now stops at what the language itself
    guarantees, which is identity.

    Severity is high only when EVERY assertion in the test is a tautology,
    because only then can the test not fail. A dead `assert True` inside a
    test with real assertions is reported at low severity: worth removing,
    not worth failing a gate over.
    """
    out: list[Finding] = []
    fn = test.node
    for node in ast.walk(fn):
        if isinstance(node, ast.Assert):
            t = node.test
            if _is_constant_expr(t):
                out.append(Finding(
                    rule="tautology", severity="high", test=test.qualified,
                    file=test.file, line=node.lineno,
                    detail="assertion is a constant expression; it cannot fail",
                    evidence=ast.unparse(t)[:80]))
            elif (isinstance(t, ast.Compare) and len(t.comparators) == 1
                  and isinstance(t.ops[0], ast.Is)
                  and _same_name(t.left, t.comparators[0])):
                out.append(Finding(
                    rule="tautology", severity="high", test=test.qualified,
                    file=test.file, line=node.lineno,
                    detail="a name is compared to itself with `is`; identity "
                           "is reflexive by definition",
                    evidence=ast.unparse(t)[:80]))
        elif isinstance(node, ast.Call):
            name = _attr_name(node.func)
            if name in {"assertEqual", "assertIs", "assertAlmostEqual"} \
                    and len(node.args) >= 2:
                a, b = node.args[0], node.args[1]
                if _is_constant_expr(a) and _is_constant_expr(b):
                    out.append(Finding(
                        rule="tautology", severity="high", test=test.qualified,
                        file=test.file, line=node.lineno,
                        detail="both arguments are constants; it cannot fail",
                        evidence=ast.unparse(node)[:80]))
                elif name == "assertIs" and _same_name(a, b):
                    out.append(Finding(
                        rule="tautology", severity="high", test=test.qualified,
                        file=test.file, line=node.lineno,
                        detail="a name is compared to itself with assertIs; "
                               "identity is reflexive by definition",
                        evidence=ast.unparse(node)[:80]))
            elif name in {"assertTrue", "assertFalse"} and node.args \
                    and _is_constant_expr(node.args[0]):
                out.append(Finding(
                    rule="tautology", severity="high", test=test.qualified,
                    file=test.file, line=node.lineno,
                    detail="argument is a constant; the assertion cannot fail",
                    evidence=ast.unparse(node)[:80]))
    if out and len(_assertion_nodes(fn)) > len(out):
        # The test also carries assertions that CAN fail, so the test itself
        # is not vacuous; the tautology is dead weight inside a real test.
        # That is worth a note, not a failed gate.
        for f in out:
            f.severity = "low"
            f.detail += "; the test can still fail through its other assertions"
    return out


def detect_mock_only(test: TestFunction) -> list[Finding]:
    """Every assertion in the test inspects a mock the test itself built.

    This is the characteristic shape of a machine-written test: construct a
    double, assert the double was called, go green. It exercises no production
    code, so no change to the system can ever break it.

    Reported only when *all* assertions are of this kind, and only when the
    body calls nothing but mocks, mock factories, assertion helpers and plain
    builtins. A test that checks a mock's call record and then also checks a
    real result is doing something; so is a test that hands the mock to the
    system under test and then asserts the collaborator was called. That
    second shape is a contract test, and the first release candidate flagged
    one in a popular suite because it only looked at the assertions. If any
    other callable runs, production code may have run, and the rule says
    nothing.
    """
    fn = test.node
    assertions = _assertion_nodes(fn)
    if not assertions:
        return []
    mocks = _mock_variables(fn)
    if not mocks:
        return []
    if _calls_outside_mocks(fn, mocks, assertions):
        return []

    def touches_only_mocks(node: ast.AST) -> bool:
        names = {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}
        # ignore the assertion helper's own receiver (`self` in unittest) and
        # plain builtins: `len(m.calls)` still inspects nothing but the mock.
        names.discard("self")
        names.difference_update(BUILTIN_CALLS)
        if not names:
            return False
        return names.issubset(mocks)

    for a in assertions:
        if isinstance(a, ast.Call):
            recv = _root_name(a.func)
            name = _attr_name(a.func)
            if name in MOCK_SELF_ASSERTIONS and recv in mocks:
                continue
            args_only_mocks = a.args and all(touches_only_mocks(x) for x in a.args)
            if args_only_mocks:
                continue
            return []
        if isinstance(a, ast.Assert):
            if touches_only_mocks(a.test):
                continue
            return []
        return []

    return [Finding(
        rule="mock-only", severity="high", test=test.qualified,
        file=test.file, line=fn.lineno,
        detail="every assertion inspects a mock created in this test; "
               "no production code is exercised",
        evidence=f"mocks: {', '.join(sorted(mocks))}")]


DETECTORS = (detect_empty_test, detect_tautology, detect_mock_only,
             detect_no_assertion)


@dataclass
class FileReport:
    """What one test file yielded: the findings that stand, the findings a
    `# suiteaudit: ignore` comment set aside, and how many tests were seen."""
    findings: list[Finding] = field(default_factory=list)
    suppressed: list[Finding] = field(default_factory=list)
    n_tests: int = 0


def analyse_file(source: str, path: str) -> FileReport:
    """Analyse one test file. Raises SyntaxError if it does not parse."""
    tree = ast.parse(source, filename=path)
    tests = collect_tests(tree, path)
    sup = _suppressions(source) if "suiteaudit" in source else {}
    report = FileReport(n_tests=len(tests))
    for test in tests:
        found = detect_empty_test(test)
        if not found:
            # An empty test is already the strongest verdict; the weaker rules
            # would only restate it.
            for detector in DETECTORS[1:]:
                found.extend(detector(test))
        for f in found:
            if sup and _is_suppressed(f, test, sup):
                report.suppressed.append(f)
            else:
                report.findings.append(f)
    return report


def analyse_source(source: str, path: str) -> tuple[list[Finding], int]:
    """Return (findings, number of tests) for one test file.

    Suppressed findings are not in the list; use `analyse_file` to see them.
    """
    report = analyse_file(source, path)
    return report.findings, report.n_tests
