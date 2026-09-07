# SPDX-License-Identifier: Apache-2.0
"""Re-measure the release case study.

Clones eleven popular Python projects at pinned commits into a temporary
directory, audits their test suites with the SuiteAudit that is installed, and
prints the Markdown tables that appear in the README. A number in the README
that this script does not reproduce is a number to distrust.

    python tools/case_study.py            # both tables
    python tools/case_study.py first      # the three suites of the first measurement
    python tools/case_study.py second     # the eight suites of the second

Network access is needed for the clones. Nothing under the repository is
modified.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile

# (repository, commit, test directory, --exclude globs)
FIRST = [
    ("psf/requests", "dae7ef6", "tests", ()),
    ("pallets/click", "36baa15", "tests", ()),
    ("python-attrs/attrs", "8f76777", "tests", ()),
]
# pytest keeps deliberately empty example tests under testing/example_scripts/
# as fixtures for its own collection tests; they are left out, which is what
# --exclude is for. Everything else is audited whole.
SECOND = [
    ("pallets/flask", "d318b68", "tests", ()),
    ("encode/httpx", "b5addb6", "tests", ()),
    ("Textualize/rich", "9d8f9a3", "tests", ()),
    ("pydantic/pydantic", "2261ae1", "tests", ()),
    ("pytest-dev/pytest", "431f3e1", "testing", ("example_scripts/*",)),
    ("django/django", "177fb98", "tests", ()),
    ("psf/black", "20622e1", "tests", ()),
    ("urllib3/urllib3", "278d98d", "test", ()),
]


def clone(repo: str, sha: str, into: str) -> str:
    dest = os.path.join(into, repo.split("/")[1])
    subprocess.run(["git", "clone", "--quiet", "--filter=blob:none", "--no-checkout",
                    f"https://github.com/{repo}", dest], check=True)
    subprocess.run(["git", "-C", dest, "checkout", "--quiet", sha], check=True)
    return dest


def measure(suites, tmp: str) -> list[tuple]:
    rows = []
    for repo, sha, tests, exclude in suites:
        dest = clone(repo, sha, tmp)
        argv = [sys.executable, "-m", "suiteaudit", "check",
                os.path.join(dest, tests), "--json"]
        for glob in exclude:
            argv += ["--exclude", glob]
        proc = subprocess.run(argv, capture_output=True, text=True)
        data = json.loads(proc.stdout)
        by_sev = {"high": 0, "medium": 0, "low": 0}
        for f in data["findings"]:
            by_sev[f["severity"]] = by_sev.get(f["severity"], 0) + 1
        label = repo + (" (excluding " + ", ".join(exclude) + ")" if exclude else "")
        rows.append((label, sha, data["tests_found"], len(data["findings"]),
                     by_sev["high"], by_sev["low"], data["verdict"]))
        for f in data["findings"]:
            if f["severity"] != "medium":
                print(f"  {repo} {f['severity']:<4} {f['rule']:<11} "
                      f"{f['file']}:{f['line']}  {f['evidence'][:60]}",
                      file=sys.stderr)
    return rows


def print_table(rows) -> None:
    print("| suite | commit | tests | findings | high | low | verdict |")
    print("|---|---|---|---|---|---|---|")
    for label, sha, n, total, high, low, verdict in rows:
        print(f"| {label} | `{sha}` | {n} | {total} | {high} | {low} | {verdict} |")


def main(argv: list[str]) -> int:
    which = argv[0] if argv else "both"
    if which not in {"first", "second", "both"}:
        print(__doc__, file=sys.stderr)
        return 2
    with tempfile.TemporaryDirectory() as tmp:
        if which in {"first", "both"}:
            print("First measurement (three suites):")
            print_table(measure(FIRST, tmp))
        if which in {"second", "both"}:
            print("\nSecond measurement (eight suites):")
            print_table(measure(SECOND, tmp))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
