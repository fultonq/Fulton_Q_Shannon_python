"""
pso_enrichment package.

Submodules here do `import config` (the project-root config.py), which only
resolves on sys.path automatically when the process was launched as
`python run.py` from the project root - that's how run.py works, but it's
fragile for any other entry point (an IDE running a submodule directly, a
test runner, `python -m pso_enrichment.pipeline` from elsewhere, etc.).
Guarantee the project root is importable the moment this package is
imported, regardless of how/where that happens.
"""

import sys
from pathlib import Path

_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
