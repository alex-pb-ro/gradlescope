"""Machine-readable JSON report."""
from __future__ import annotations

import json

from gradlescope.result import AnalysisResult


def to_json(result: AnalysisResult, indent: int = 2) -> str:
    return json.dumps(result.to_dict(), indent=indent, sort_keys=False)
