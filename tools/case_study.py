# SPDX-License-Identifier: Apache-2.0
"""Re-measure the release case study.

Clones three popular Python projects at pinned commits into a temporary
directory, audits their test suites with the SuiteAudit that is installed, and
prints the Markdown table that appears in the README. A number in the README
that this script does not reproduce is a number to distrust.

    python tools/case_study.py

Network access is needed for the clones. Nothing under the repository is
modified.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile

PINNED = [
    ("psf/requests", "dae7ef6"),
    ("pallets/click", "36baa15"),
    ("python-attrs/attrs", "8f76777"),
]


def clone(repo: str, sha: str, into: str) -> str:
    dest = os.path.join(into, repo.split("/")[1])
    subprocess.run(["git", "clone", "--quiet", "--filter=blob:none", "--no-checkout",
                    f"https://github.com/{repo}", dest], check=True)
    subprocess.run(["git", "-C", dest, "checkout", "--quiet", sha], check=True)
    return dest


def main() -> int:
    rows = []
    with tempfile.TemporaryDirectory() as tmp:
        for repo, sha in PINNED:
            dest = clone(repo, sha, tmp)
            proc = subprocess.run(
                [sys.executable, "-m", "suiteaudit", "check",
                 os.path.join(dest, "tests"), "--json"],
                capture_output=True, text=True)
            data = json.loads(proc.stdout)
            by_sev = {"high": 0, "medium": 0, "low": 0}
            for f in data["findings"]:
                by_sev[f["severity"]] = by_sev.get(f["severity"], 0) + 1
            rows.append((repo, sha, data["tests_found"], len(data["findings"]),
                         by_sev["high"], by_sev["low"], data["verdict"]))
            for f in data["findings"]:
                if f["severity"] != "medium":
                    print(f"  {repo} {f['severity']:<4} {f['rule']:<11} "
                          f"{f['file']}:{f['line']}  {f['evidence'][:60]}",
                          file=sys.stderr)
    print("| suite | commit | tests | findings | high | low | verdict |")
    print("|---|---|---|---|---|---|---|")
    for repo, sha, n, total, high, low, verdict in rows:
        print(f"| {repo} | `{sha}` | {n} | {total} | {high} | {low} | {verdict} |")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
