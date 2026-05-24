"""Re-export из framework (Phase 1A, Task A1)."""

import time  # noqa: F401 — нужен для unittest.mock.patch("...wire_monitor.time.time")
from multiprocess_framework.modules.frontend_module.bridge.wire_monitor import *  # noqa: F401, F403
from multiprocess_framework.modules.frontend_module.bridge.wire_monitor import __all__  # noqa: F401
