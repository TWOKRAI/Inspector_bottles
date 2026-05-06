"""ChainExecutorPlugin -- последовательное/параллельное выполнение цепочки плагинов.

Processing-плагин: process(items) -> items — прогоняет через цепочку sub-plugins.

Последовательный режим (по умолчанию):
    items → шаг1 → шаг2 → ... → шагN → items

Параллельный режим (parallel=True):
    items → [шаг1, шаг2, ..., шагN] (каждый получает копию) → мерж результатов
"""

from __future__ import annotations

import copy
import importlib
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from unittest.mock import MagicMock

from multiprocess_framework.modules.process_module.plugins.base import (
    PluginContext,
    ProcessModulePlugin,
)
from multiprocess_framework.modules.process_module.plugins.port import Port
from multiprocess_framework.modules.process_module.plugins.registry import register_plugin

logger = logging.getLogger(__name__)


@register_plugin(
    "chain_executor",
    category="processing",
    description="Последовательное/параллельное выполнение цепочки плагинов",
)
class ChainExecutorPlugin(ProcessModulePlugin):
    """Оркестратор цепочки sub-plugins.

    Каждый шаг — экземпляр другого ProcessModulePlugin.
    Шаги добавляются через конфиг (steps) или команду add_step.
    """

    name = "chain_executor"
    category = "processing"

    inputs = [
        Port(
            name="frame",
            dtype="image/bgr",
            shape="(H, W, 3)",
            description="Входные данные",
        ),
    ]
    outputs = [
        Port(
            name="frame",
            dtype="image/bgr",
            shape="(H, W, 3)",
            description="Обработанные данные",
        ),
    ]

    commands = {
        "add_step": "cmd_add_step",
        "remove_step": "cmd_remove_step",
        "reorder_steps": "cmd_reorder_steps",
        "get_steps": "cmd_get_steps",
    }

    # --- Жизненный цикл ---

    def configure(self, ctx: PluginContext) -> None:
        """Настройка цепочки: параметры + инициализация шагов из конфига."""
        cfg = ctx.config
        self._ctx = ctx
        self._parallel = cfg.get("parallel", False)
        self._max_workers = cfg.get("max_workers", 4)
        self._on_error = cfg.get("on_error", "skip")

        # Список шагов: [{"name": str, "plugin": ProcessModulePlugin, "config": dict}]
        self._steps: list[dict] = []

        # ThreadPoolExecutor для параллельного режима (создаётся в start)
        self._pool: ThreadPoolExecutor | None = None

        # Инициализировать шаги из конфига
        steps_config = cfg.get("steps", [])
        for step_cfg in steps_config:
            self._init_step(step_cfg)

        ctx.log_info(
            f"ChainExecutorPlugin: {len(self._steps)} шагов, "
            f"parallel={self._parallel}, on_error={self._on_error}"
        )

    def start(self, ctx: PluginContext) -> None:
        """Запуск: создать ThreadPoolExecutor если параллельный режим."""
        if self._parallel and self._max_workers > 1:
            self._pool = ThreadPoolExecutor(max_workers=self._max_workers)
            ctx.log_info(
                f"ChainExecutorPlugin: ThreadPoolExecutor запущен, "
                f"max_workers={self._max_workers}"
            )

    def shutdown(self, ctx: PluginContext) -> None:
        """Остановка: закрыть пул + завершить все sub-plugins."""
        if self._pool:
            self._pool.shutdown(wait=False)
            self._pool = None

        # Корректно завершить каждый sub-plugin
        for step in self._steps:
            try:
                mock_ctx = MagicMock(spec=PluginContext)
                step["plugin"].shutdown(mock_ctx)
            except Exception:
                pass  # sub-plugin мог не реализовать shutdown — игнорируем

    # --- Внутренняя инициализация шага ---

    def _init_step(self, step_cfg: dict) -> bool:
        """Инициализировать один шаг цепочки из dict-конфига.

        Args:
            step_cfg: {"plugin_class": "full.path.PluginClass",
                        "plugin_name": "step_name",   # необязательно
                        "config": {...}}               # необязательно

        Returns:
            True если шаг успешно добавлен, False при ошибке.
        """
        plugin_class_path = step_cfg.get("plugin_class", "")
        step_name = step_cfg.get(
            "plugin_name", plugin_class_path.split(".")[-1] if plugin_class_path else "unknown"
        )
        sub_config = step_cfg.get("config", {})

        if not plugin_class_path:
            logger.error("ChainExecutorPlugin: step без plugin_class — пропущен")
            return False

        try:
            # Динамический импорт класса плагина
            module_path, class_name = plugin_class_path.rsplit(".", 1)
            module = importlib.import_module(module_path)
            plugin_cls = getattr(module, class_name)

            # Создать экземпляр и сконфигурировать с mock ctx
            plugin_instance = plugin_cls()
            mock_ctx = MagicMock(spec=PluginContext)
            mock_ctx.config = sub_config
            mock_ctx.log_info = lambda msg: logger.info(f"[{step_name}] {msg}")
            mock_ctx.log_error = lambda msg: logger.error(f"[{step_name}] {msg}")
            mock_ctx.registers = None
            mock_ctx.command_manager = MagicMock()
            plugin_instance.configure(mock_ctx)

            self._steps.append({
                "name": step_name,
                "plugin": plugin_instance,
                "config": sub_config,
            })
            logger.info(f"ChainExecutorPlugin: шаг '{step_name}' добавлен")
            return True

        except Exception as e:
            logger.error(
                f"ChainExecutorPlugin: ошибка инициализации шага '{step_name}': {e}"
            )
            return False

    # --- Обработка ---

    def process(self, items: list[dict]) -> list[dict]:
        """Прогнать items через цепочку шагов.

        НЕ @for_each — работает с batch list[dict].
        """
        if not self._steps:
            return items

        if self._parallel and self._pool and len(self._steps) > 1:
            return self._process_parallel(items)

        return self._process_sequential(items)

    def _process_sequential(self, items: list[dict]) -> list[dict]:
        """Последовательное выполнение: items → шаг1 → шаг2 → ..."""
        current = items
        for step in self._steps:
            try:
                result = step["plugin"].process(current)
                if isinstance(result, list):
                    current = result
                elif result is not None:
                    # Одиночный dict — завернуть в список
                    current = [result]
                # result is None → оставляем current без изменений (skip step)
            except Exception as e:
                logger.error(
                    f"ChainExecutorPlugin: ошибка в шаге '{step['name']}': {e}"
                )
                if self._on_error == "fail":
                    # Остановить цепочку, вернуть что есть
                    break
                # on_error == "skip" → продолжаем с текущими items
        return current

    def _process_parallel(self, items: list[dict]) -> list[dict]:
        """Параллельное выполнение: каждый шаг получает копию items.

        Результаты всех шагов объединяются (extend).
        Если все шаги упали — возвращаем исходный items.
        """
        futures: dict = {}
        for step in self._steps:
            # Каждый шаг работает с независимой копией
            items_copy = copy.deepcopy(items)
            future = self._pool.submit(step["plugin"].process, items_copy)
            futures[future] = step["name"]

        # Собрать результаты всех завершившихся futures
        all_results: list[dict] = []
        for future in as_completed(futures):
            step_name = futures[future]
            try:
                result = future.result(timeout=10)
                if isinstance(result, list):
                    all_results.extend(result)
                elif result is not None:
                    all_results.append(result)
            except Exception as e:
                logger.error(
                    f"ChainExecutorPlugin: ошибка в параллельном шаге '{step_name}': {e}"
                )

        # Если все упали — вернуть исходный items (graceful degradation)
        return all_results if all_results else items

    # --- Команды ---

    def cmd_add_step(self, data: dict) -> dict:
        """Добавить шаг в цепочку.

        Args:
            data: {"plugin_class": "...", "plugin_name": "...", "config": {...}}

        Returns:
            {"status": "ok"|"error", "steps_count": int}
        """
        success = self._init_step(data)
        return {
            "status": "ok" if success else "error",
            "steps_count": len(self._steps),
        }

    def cmd_remove_step(self, data: dict) -> dict:
        """Удалить шаг по имени.

        Args:
            data: {"name": "step_name"}

        Returns:
            {"status": "ok", "removed": int, "steps_count": int}
        """
        name = data.get("name", "")
        before = len(self._steps)
        self._steps = [s for s in self._steps if s["name"] != name]
        removed = before - len(self._steps)
        return {
            "status": "ok",
            "removed": removed,
            "steps_count": len(self._steps),
        }

    def cmd_reorder_steps(self, data: dict) -> dict:
        """Переупорядочить шаги по списку имён.

        Шаги отсутствующие в order — добавляются в конец в исходном порядке.

        Args:
            data: {"order": ["name1", "name2", ...]}

        Returns:
            {"status": "ok", "order": ["name1", "name2", ...]}
        """
        order = data.get("order", [])
        name_map = {s["name"]: s for s in self._steps}
        # Шаги в указанном порядке
        new_steps = [name_map[n] for n in order if n in name_map]
        # Шаги не упомянутые в order — добавить в конец
        remaining = [s for s in self._steps if s["name"] not in order]
        self._steps = new_steps + remaining
        return {
            "status": "ok",
            "order": [s["name"] for s in self._steps],
        }

    def cmd_get_steps(self, data: dict) -> dict:
        """Получить текущий список шагов.

        Returns:
            {"status": "ok", "steps": [{"name": str, "config": dict}, ...]}
        """
        return {
            "status": "ok",
            "steps": [
                {"name": s["name"], "config": s["config"]}
                for s in self._steps
            ],
        }
