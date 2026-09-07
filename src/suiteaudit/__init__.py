# SPDX-License-Identifier: Apache-2.0
"""SuiteAudit: find the tests that cannot fail."""
from importlib.metadata import PackageNotFoundError, version

from .audit import AuditResult, audit, audit_paths
from .detectors import FileReport, Finding, analyse_file, analyse_source

try:
    # pyproject.toml is the single source of truth for the version.
    __version__ = version("suiteaudit")
except PackageNotFoundError:  # running from a source tree that is not installed
    __version__ = "0.0.0+uninstalled"

__all__ = ["audit", "audit_paths", "AuditResult", "analyse_source",
           "analyse_file", "FileReport", "Finding", "__version__"]
