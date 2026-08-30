# SPDX-License-Identifier: Apache-2.0
"""SuiteAudit: find the tests that cannot fail."""
from .audit import AuditResult, audit
from .detectors import Finding, analyse_source

__all__ = ["audit", "AuditResult", "analyse_source", "Finding"]
__version__ = "0.1.0"
