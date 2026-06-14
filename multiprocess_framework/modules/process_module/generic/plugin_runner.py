"""PluginRunner — единый шов вызова plugin.process()/produce() + pre/post-хуки.

Все вызовы плагинов в data-плоскости (PipelineExecutor.chain, SourceProducer.loop)
идут ЧЕРЕЗ этот раннер. Это даёт ОДНУ точку наблюдения за in/out плагина —
io-debug (Этап 5: summary входа/выхода в карточку ноды), метрики, диагностика —
вместо дублирования логики в двух воркерах.

Что раннер НЕ делает (намеренно):
- НЕ ловит исключения plugin.process/produce — error policy остаётся у вызывающего
  (circuit breaker в PipelineExecutor; обработка NotImplementedError в SourceProducer).
  Раннер прозрачен: исключение плагина пробрасывается как раньше.
- НЕ дублирует frame_trace — process/produce уже обёрнуты в ProcessModulePlugin
  .__init_subclass__ (frame_trace.traced). Раннер добавляет только hook-семантику.

Хуки опциональны. Пустой набор → overhead = два прохода по пустым спискам (наносекунды,
требование Этапа 4: < 0.1 мс на hot path). Хук, бросивший исключение, изолируется
(try/except + log) — кривой наблюдатель не должен ронять data-плоскость.

Семантика хуков:
    pre-hook(plugin, method, inputs)           — до вызова (inputs до мутации плагином)
    post-hook(plugin, method, inputs, outputs) — после успешного вызова

``method`` — "process" | "produce". Для produce ``inputs`` = None (источник без входа).
io-debug снимает summary входа в pre-hook (плагины часто мутируют item in-place),
выхода — в post-hook.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from ..plugins.base import ProcessModulePlugin

# pre-hook:  (plugin, method, inputs) -> None
PreHook = Callable[["ProcessModulePlugin", str, "list[dict] | None"], None]
# post-hook: (plugin, method, inputs, outputs) -> None
PostHook = Callable[["ProcessModulePlugin", str, "list[dict] | None", "list[dict]"], None]


class PluginRunner:
    """Единый вызыватель плагинов с pre/post-хуками наблюдения.

    Args:
        log_error: callback для изоляции ошибок хуков (хук не роняет data-плоскость).
    """

    def __init__(self, log_error: Callable[[str], None] | None = None) -> None:
        self._pre_hooks: list[PreHook] = []
        self._post_hooks: list[PostHook] = []
        self._log_error = log_error or (lambda msg: None)

    # ------------------------------------------------------------------ #
    #  Регистрация наблюдателей (Этап 5: io-debug publisher)              #
    # ------------------------------------------------------------------ #

    def add_pre_hook(self, hook: PreHook) -> None:
        """Зарегистрировать pre-хук (вызывается до plugin.process/produce)."""
        self._pre_hooks.append(hook)

    def add_post_hook(self, hook: PostHook) -> None:
        """Зарегистрировать post-хук (вызывается после успешного вызова)."""
        self._post_hooks.append(hook)

    # ------------------------------------------------------------------ #
    #  Вызовы плагина (единственная точка в data-плоскости)              #
    # ------------------------------------------------------------------ #

    def call_process(self, plugin: "ProcessModulePlugin", items: list[dict]) -> list[dict]:
        """Вызвать plugin.process(items) с хуками. Исключение плагина пробрасывается.

        Bypass: если plugin.enabled == False — process() НЕ вызывается, кадр идёт
        насквозь (outputs = входные items). Хуки наблюдения всё равно срабатывают
        (io-debug видит ноду как pass-through). Нужно, чтобы выключить «тяжёлую»/
        зависающую ноду (напр. circle_detector) и спокойно тюнить остальную цепочку.
        """
        self._run_pre(plugin, "process", items)
        if getattr(plugin, "enabled", True):
            outputs = plugin.process(items)
        else:
            outputs = items  # bypass: кадр без обработки
        self._run_post(plugin, "process", items, outputs)
        return outputs

    def call_produce(self, plugin: "ProcessModulePlugin") -> list[dict]:
        """Вызвать plugin.produce() с хуками. Исключение плагина пробрасывается."""
        self._run_pre(plugin, "produce", None)
        outputs = plugin.produce()
        self._run_post(plugin, "produce", None, outputs)
        return outputs

    # ------------------------------------------------------------------ #
    #  Внутреннее: изоляция хуков                                         #
    # ------------------------------------------------------------------ #

    def _run_pre(self, plugin: "ProcessModulePlugin", method: str, inputs: list[dict] | None) -> None:
        for hook in self._pre_hooks:
            try:
                hook(plugin, method, inputs)
            except Exception as e:  # noqa: BLE001 — наблюдатель не должен ронять pipeline
                self._log_error(f"PluginRunner pre-hook error ({plugin.name}.{method}): {e}")

    def _run_post(
        self,
        plugin: "ProcessModulePlugin",
        method: str,
        inputs: list[dict] | None,
        outputs: list[dict],
    ) -> None:
        for hook in self._post_hooks:
            try:
                hook(plugin, method, inputs, outputs)
            except Exception as e:  # noqa: BLE001 — наблюдатель не должен ронять pipeline
                self._log_error(f"PluginRunner post-hook error ({plugin.name}.{method}): {e}")
