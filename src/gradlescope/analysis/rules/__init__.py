"""Built-in rules. Importing this package registers every rule."""
from gradlescope.analysis.rules import (  # noqa: F401
    caching,
    dependencies,
    graph_patterns,
    structure,
)
