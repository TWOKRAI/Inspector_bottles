"""PluginOperationStep — мост pipeline-движка к chain_module (C6d инкремент 1).

Адаптер ``IExecutionStep``: оборачивает один processing-плагин в шаг цепочки,
исполняемой ``ChainRunnable``. Делегирует вызов СТРОГО через ``PluginRunner``
(единый шов io-debug + FW_PORT_VALIDATE), а НЕ ``plugin.process()`` напрямую —
иначе pre/post-хуки наблюдения и port-валидация молча отключились бы для
chain-исполняемых плагинов (риск №2 дизайна §6).

Разрез ответственности (дизайн §5(d) инкремент 1, вариант 2):
    - адаптер сам ловит исключение плагина, тегирует ``inspection_status =
      "not_inspected"`` (pass-through — items продолжают течь, как в старом
      ``PipelineExecutor._execute_chain``) и репортит фейл наружу через
      ``on_fail``-колбэк;
    - ``on_error`` шага в chain ВСЕГДА ``"skip"`` — ``apply_on_error_policy``
      chain_module не задействуется (0 правок в chain_module/core/error_policy.py);
    - вся breaker-семантика (consecutive_fails / bypass / auto_reset /
      critical→suspect) остаётся в ``PipelineExecutor``.

Дом — ``process_module/generic/`` (мост движка к chain, НЕ домен): chain_module
не знает про плагины/``PluginRunner``; ``process_module`` знает про chain_module
(framework-internal импорт разрешён). Обратного импорта chain_module→process_module
НЕТ.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from ..plugins.base import ProcessModulePlugin
    from .plugin_runner import PluginRunner


@dataclass
class PipelineStepNode:
    """Минимальный дескриптор ноды (``IStepNode``) для RunnableStep.

    В processing-pipeline chain используется только как последовательный проход,
    ветвление (``inputs``) не задействуется — список пуст. ``node_id`` /
    ``operation_ref`` = имя плагина: нужны лишь если ``apply_on_error_policy``
    когда-либо сработает (в текущем разрезе не срабатывает — адаптер ловит
    исключение сам, on_error всегда skip).
    """

    node_id: str
    operation_ref: str
    inputs: list = field(default_factory=list)


class PluginOperationStep:
    """``IExecutionStep``-адаптер одного плагина для ``ChainRunnable``."""

    def __init__(
        self,
        plugin: ProcessModulePlugin,
        runner: PluginRunner,
        on_success: Callable[[str], None],
        on_fail: Callable[[str, Exception], None],
        log_error: Callable[[str], None] | None = None,
    ) -> None:
        self._plugin = plugin
        self._runner = runner
        self._on_success = on_success
        self._on_fail = on_fail
        self._log_error = log_error or (lambda msg: None)

    def execute(self, data: Any, context: Any) -> Any:
        """Прогнать items через плагин. ``data`` — ``list[dict]`` items; ``context`` игнор.

        Пустой батч — плагин НЕ вызывается и счётчики fails НЕ трогаются: это
        эквивалент старого ``if not items: break`` (последующие шаги тоже увидят
        пустой список и станут no-op, ни один плагин после опустошения не вызван).
        """
        items = data
        if not items:
            return items
        try:
            outputs = self._runner.call_process(self._plugin, items)
        except Exception as exc:  # noqa: BLE001 — error-policy pass-through (Q7), как в старом цикле
            self._log_error(f"PipelineExecutor: {self._plugin.name}.process() error: {exc}")
            for item in items:
                item["inspection_status"] = "not_inspected"
            self._on_fail(self._plugin.name, exc)
            return items  # pass-through: помеченные items текут дальше
        self._on_success(self._plugin.name)
        return outputs

    def configure(self, params: dict) -> None:
        """Часть контракта ``IExecutionStep``; плагин конфигурируется своим циклом."""
        return None


__all__ = ["PluginOperationStep", "PipelineStepNode"]
