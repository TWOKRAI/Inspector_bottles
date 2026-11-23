"""Проба 1.1a: потребитель minimal_app с медленным shutdown (4 с) — медленный ребёнок для PM."""

from __future__ import annotations

import time

from examples.minimal_app.plugins.console_consumer.plugin import ConsoleConsumerPlugin
from multiprocess_framework.modules.process_module.plugins import PluginContext, register_plugin


@register_plugin("slow_consumer", category="utility", description="Потребитель с медленным shutdown (проба)")
class SlowConsumerPlugin(ConsoleConsumerPlugin):
    name = "slow_consumer"

    def shutdown(self, ctx: PluginContext) -> None:
        time.sleep(4.0)
        super().shutdown(ctx)
