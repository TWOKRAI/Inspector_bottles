"""BeltWriterPlugin — фикстура тестера Task 2.0 (independent RED).

Пишет ``sim.belt.encoder`` в реактивное дерево состояния по команде
``trigger_set`` (таймингом владеет тест, не сам плагин — иначе гонка с
подпиской reader'а). Путь ``sim.belt.*`` нигде не посеян (посев по умолчанию —
только ``processes``, Task 1.0 / ADR-APP-007) — «set по пути вне посева
проходит» проверяется самим фактом, что запись доходит.

Также публикует уровень ``belt_fps`` (ADR-PM-038, ``ctx.publish_metric``) —
адаптация REDS-критерия «heartbeat кладёт метрику плагина в дерево»
(``processes.<w>.state.plugins.<w>.<name>``) под фикстуру без камеры line_sim
(см. отчёт тестера).
"""

from __future__ import annotations

from multiprocess_framework.modules.process_module.plugins import (
    PluginContext,
    ProcessModulePlugin,
    register_plugin,
)


@register_plugin("belt_writer", category="utility", description="Фикстура Task 2.0: пишет sim.belt.encoder по команде")
class BeltWriterPlugin(ProcessModulePlugin):
    """Пишет ``sim.belt.encoder`` через ``ctx.state_proxy.set`` по команде извне."""

    name = "belt_writer"
    category = "utility"
    inputs: list = []
    outputs: list = []

    #: Авто-регистрация в CommandManager (ProcessModulePlugin._auto_register_commands).
    commands = {"trigger_set": "cmd_trigger_set"}

    def configure(self, ctx: PluginContext) -> None:
        self._ctx = ctx

    def start(self, ctx: PluginContext) -> None:
        # Публикуем уровень один раз — heartbeat подхватит на своём такте
        # (гейт `_state_proxy`, ADR-PM-038); значение неизменно намеренно —
        # тест ждёт появления листа в дереве, а не его изменения.
        ctx.publish_metric("belt_fps", 30)

    def cmd_trigger_set(self, _data: dict) -> dict:
        """Команда извне (backend_ctl/тест) — момент записи под контролем теста."""
        if self._ctx.state_proxy is None:
            return {"status": "error", "reason": "ctx.state_proxy is None"}
        self._ctx.state_proxy.set("sim.belt.encoder", {"value": 42})
        return {"status": "ok"}

    def shutdown(self, ctx: PluginContext) -> None:
        pass
