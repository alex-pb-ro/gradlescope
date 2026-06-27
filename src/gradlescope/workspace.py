"""Per-repo workspace under the user's home, so we never write into the analyzed
repository.

Layout (overridable with the ``GRADLESCOPE_HOME`` env var)::

    ~/.gradlescope/
      repos/
        <repo-name>-<hash8>/      # one workspace per analyzed repo
          site/                   # generated dashboard
          history.json            # score trend
          jobs/                   # streamed Gradle job logs
"""
from __future__ import annotations

import hashlib
import os
import re


def gradlescope_home() -> str:
    override = os.environ.get("GRADLESCOPE_HOME")
    if override:
        return os.path.abspath(os.path.expanduser(override))
    return os.path.join(os.path.expanduser("~"), ".gradlescope")


def repo_slug(root: str) -> str:
    """A stable, filesystem-safe id for a repo (name + short hash of its path)."""
    abs_root = os.path.abspath(root)
    base = os.path.basename(abs_root.rstrip(os.sep)) or "repo"
    safe = re.sub(r"[^A-Za-z0-9._-]", "-", base)
    digest = hashlib.sha1(abs_root.encode("utf-8")).hexdigest()[:8]
    return f"{safe}-{digest}"


def repo_workspace(root: str) -> str:
    return os.path.join(gradlescope_home(), "repos", repo_slug(root))


def default_site_dir(root: str) -> str:
    return os.path.join(repo_workspace(root), "site")
