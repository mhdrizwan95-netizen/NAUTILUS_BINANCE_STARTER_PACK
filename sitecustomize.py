"""
Project-wide interpreter customizations.

Pytest's plugin autoload can pull in user-installed plugins that interfere with this
repository's tests. Disabling autoload keeps runs deterministic without requiring callers
to export PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 manually.
"""

import os

os.environ.setdefault("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
