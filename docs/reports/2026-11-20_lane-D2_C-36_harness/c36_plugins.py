"""C-36 harness plugins (scratchpad only). Loaded by dotted path inside a real GenericProcess child."""
import os
import time

from multiprocess_framework.modules.process_module.plugins.base import ProcessModulePlugin

_BURN_S = float(os.environ.get("C36_BURN_MS", "0")) / 1000.0


class C36Source(ProcessModulePlugin):
    """Source: produce() burns CPU in pure Python for C36_BURN_MS (models frame generation), yields nothing."""

    name = "c36_src"
    category = "source"

    def configure(self, ctx) -> None:
        pass

    def start(self, ctx) -> None:
        pass

    def produce(self) -> list:
        if _BURN_S > 0:
            end = time.perf_counter() + _BURN_S
            x = 0
            while time.perf_counter() < end:
                x += 1
        return []


class C36Proc(ProcessModulePlugin):
    """Processing plugin: its presence makes GenericProcess start DataReceiver (get(timeout=0.05) on data)."""

    name = "c36_proc"
    category = "processing"

    def configure(self, ctx) -> None:
        pass

    def start(self, ctx) -> None:
        pass

    def process(self, items: list) -> list:
        return items
