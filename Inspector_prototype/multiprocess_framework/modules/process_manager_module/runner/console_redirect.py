"""Перенаправление stdout/stderr в очереди консоли (если задано в custom)."""

import sys
from typing import Any, Optional

from .class_loader import _ProcessLogger


def _setup_console_redirect(
    process_name: str,
    process_data: Any,
    log: _ProcessLogger,
) -> Optional[Any]:
    """
    Настроить ConsoleRedirector из custom.console_queues / console_queue.
    """
    if not (process_data and process_data.custom):
        return None
    custom = process_data.custom
    if "console_queues" not in custom and "console_queue" not in custom:
        return None

    try:
        from multiprocess_framework.modules.console_module import ConsoleRedirector

        if "console_queues" in custom:
            output_queues = custom["console_queues"]
            redirector = ConsoleRedirector(output_queues, process_name)
        else:
            output_queue = custom["console_queue"]
            redirector = ConsoleRedirector(output_queue, process_name)

        sys.stdout = redirector
        sys.stderr = redirector
        log.info("Console redirect enabled")
        return redirector
    except Exception as e:
        log.warning(f"Failed to setup console redirect: {e}")
        return None
