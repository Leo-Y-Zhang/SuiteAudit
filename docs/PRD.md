# PRD: SuiteAudit 0.1.0, the first installable release

## Problem

SuiteAudit exists to be run by strangers, in their own CI, on suites its
author has never seen. At the 30 Aug 2026 commit it could only be installed
from a source checkout, and when the release candidate was pointed at three
popular Python projects it failed two of their gates on findings that were
false. A gate that fails honest projects gets switched off, and a switched-off
gate finds nothing. The release is blocked until the tool clears its own bar.

## Users

- A maintainer adding one line to CI or pre-commit who wants a verdict they
  can trust on the first run, with no dependencies to negotiate.
- A reviewer of machine-written tests who wants the vacuous ones named, not
  a score.

## Goals

1. `pip install suiteaudit`, a pre-commit hook and a GitHub Action, all from
   one tagged release, published without any stored token.
2. Zero false positives at high severity on the three release-candidate
   suites (requests, click, attrs at their pinned commits) and on the eight
   suites of the second measurement (flask, httpx, rich, pydantic, pytest,
   django, black, urllib3), measured, with every remaining high finding
   confirmable by reading the flagged line.
3. An adopter can set a single finding aside without switching the gate off,
   and the report says how many were set aside.
4. No traceback reaches a user: an unreadable file is reported, not fatal;
   `verify` outside a checkout explains itself.

## Non-goals

- New rules. The four rules stay; the release only narrows them (two after
  the first measurement, three and the test discovery after the second).
- SARIF output, a config file, or a baseline file. Inline comments cover the
  first-release need; the rest waits for a user to ask.
- Executing the code under test. AST only, as before.

## Success measure

The eleven pinned suites, audited by the release: every high finding is a true
positive by reading. Before the first fix the three release-candidate suites
showed 31 high findings of which 30 were false; before the second, the eight
further suites showed 36 of which 16 were false. The acceptance bar is zero
false high findings, and both measurements are reproduced by
`tools/case_study.py`.

## Owner steps (the only ones)

PyPI account with 2FA, a pending trusted publisher, the `pypi` GitHub
environment, then a tag. Written out in `RELEASING.md`.
