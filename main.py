"""Compat shim so lessons/ (which do `sys.path.insert` to repo root, not src/)
keep working after the app code moved to src/agents/.
"""

from agents.main import *  # noqa: F401,F403
from agents.main import agent, get_snapshot, main  # noqa: F401
