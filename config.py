"""Compat shim so lessons/ (which do `sys.path.insert` to repo root, not src/)
keep working after the app code moved to src/core/.
"""

from core.config import *  # noqa: F401,F403
from core.config import CONFIG_PATH, load_agent  # noqa: F401
