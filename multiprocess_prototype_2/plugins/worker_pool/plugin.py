"""WorkerPoolPlugin -- параллельная обработка items через пул потоков.

Processing-плагин: process(items) → items — распределяет items по worker threads.
Каждый worker = отдельный экземпляр sub-plugin (thread safety через изоляцию).
Порядок результатов соответствует порядку входных items.
При ошибке в worker — fallback на оригинальный item.

V3_MY_PURE: plugin самодостаточен — создаёт локальный register
если RegistersManager недоступен. Все параметры ВСЕГДА через self._reg.
"""

from __future__ import annotations

import importlib
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from unittest.mock import MagicMock

from multiprocess_framework.modules.process_module.plugins.base import (
    PluginContext,
    ProcessModulePlugin,
)
from multiprocess_framework.modules.process_module.plugins.port import Port
from multiprocess_framework.modules.process_module.plugins.registry import register_plugin

from .registers import WorkerPoolRegisters

logger = logging.getLogger(__name__)


@register_plugin(
    "worker_pool",
    category="processing",
    description="Параллельная обработка items через пул потоков",
)
class WorkerPoolPlugin(ProcessModulePlugin):
    """Распределяет items по пулу потоков для параллельной обработки.

    Каждый поток имеет свой экземпляр sub-plugin — никаких shared state.
    Стратегии балансировки: round_robin (default), shortest_queue (fallback к round_robin).
    """

    name = "worker_pool"
    category = "processing"

    inputs = [
        Port(name="frame", dtype="image/bgr", shape="(H, W, 3)", description="Входные данные"),
    ]
    outputs = [
        Port(name="frame", dtype="image/bgr", shape="(H, W, 3)", description="Обработанные данные"),
    ]

    commands = {
        "resize_pool": "cmd_resize_pool",
        "get_stats": "cmd_get_stats",
    }

    # --- configure ---

    def configure(self, ctx: PluginContext) -> None:
        """Настройка: register managed (GUI) или локальный (defaults)."""
        cfg = ctx.config
        self._ctx = ctx

        # Register: managed (RegistersManager → GUI видит) или локальный
        self._reg = (
            ctx.registers.get_register(self.name) if ctx.registers is not None else None
        ) or WorkerPoolRegisters()

        # YAML overrides → синхронизируем в register
        for field in type(self._reg).model_fields:
            if field in cfg:
                setattr(self._reg, field, cfg[field])

        # Счётчики статистики (runtime-only, не в register)
        self._total_processed: int = 0
        self._total_errors: int = 0

        # Индекс для round-robin
        self._round_robin_idx: int = 0

        # Мьютекс для атомарного обновления счётчиков
        self._lock = threading.Lock()

        # Пул потоков — создаётся в start()
        self._pool: ThreadPoolExecutor | None = None

        # Создать по одному экземпляру sub-plugin на каждый worker
        self._worker_plugins: list[ProcessModulePlugin] = []
        if self._reg.worker_plugin_class:
            for _ in range(self._reg.pool_size):
                wp = self._create_worker_plugin()
                if wp is not None:
                    self._worker_plugins.append(wp)

        ctx.log_info(
            f"WorkerPoolPlugin: pool_size={self._reg.pool_size}, "
            f"balancing={self._reg.balancing}, "
            f"workers_created={len(self._worker_plugins)}"
        )

    # --- start / shutdown ---

    def start(self, ctx: PluginContext) -> None:
        """Запустить ThreadPoolExecutor."""
        self._pool = ThreadPoolExecutor(max_workers=self._reg.pool_size)
        ctx.log_info(f"WorkerPoolPlugin: pool запущен, max_workers={self._reg.pool_size}")

    def shutdown(self, ctx: PluginContext) -> None:
        """Остановить ThreadPoolExecutor, дождаться завершения задач."""
        if self._pool is not None:
            self._pool.shutdown(wait=True)
            self._pool = None
        ctx.log_info("WorkerPoolPlugin: pool остановлен")

    # --- process ---

    def process(self, items: list[dict]) -> list[dict]:
        """Распределить items по worker'ам и собрать результаты в порядке входа.

        Если пул не запущен или нет worker plugins — вернуть items без изменений.
        """
        if not items or self._pool is None or not self._worker_plugins:
            return items

        # Отправить каждый item в пул: сохранить future → индекс
        futures: dict = {}
        for i, item in enumerate(items):
            worker_idx = self._select_worker(i)
            plugin = self._worker_plugins[worker_idx]
            future = self._pool.submit(self._process_single, plugin, item)
            futures[future] = i

        # Собрать результаты в правильном порядке
        results: list[dict | None] = [None] * len(items)
        for future in as_completed(futures):
            idx = futures[future]
            try:
                result = future.result(timeout=self._reg.queue_timeout)
                results[idx] = result
                with self._lock:
                    self._total_processed += 1
            except Exception as exc:
                logger.error(f"WorkerPoolPlugin: ошибка обработки item[{idx}]: {exc}")
                results[idx] = items[idx]  # fallback: оригинальный item без изменений
                with self._lock:
                    self._total_errors += 1

        # Убрать None (на случай сбоя индексирования) и вернуть
        return [r for r in results if r is not None]

    # --- вспомогательные методы ---

    def _select_worker(self, item_idx: int) -> int:
        """Выбрать индекс worker по стратегии балансировки.

        round_robin — последовательно по кругу.
        shortest_queue — для ThreadPoolExecutor недоступен, fallback к round_robin.
        """
        if self._reg.balancing == "round_robin":
            idx = self._round_robin_idx % len(self._worker_plugins)
            self._round_robin_idx += 1
            return idx

        # shortest_queue — fallback к позиционному round_robin
        return item_idx % len(self._worker_plugins)

    def _process_single(self, plugin: ProcessModulePlugin, item: dict) -> dict:
        """Обработать один item через plugin.process([item]).

        Возвращает первый элемент результата или оригинальный item при пустом списке.
        """
        result = plugin.process([item])
        if isinstance(result, list) and len(result) > 0:
            return result[0]
        return item

    def _create_worker_plugin(self) -> ProcessModulePlugin | None:
        """Создать и сконфигурировать экземпляр sub-plugin.

        Использует importlib для загрузки класса по полному пути.
        Возвращает None при ошибке импорта или конфигурирования.
        """
        if not self._reg.worker_plugin_class:
            return None
        try:
            module_path, class_name = self._reg.worker_plugin_class.rsplit(".", 1)
            module = importlib.import_module(module_path)
            plugin_cls = getattr(module, class_name)
            instance: ProcessModulePlugin = plugin_cls()

            # Создать mock-контекст для sub-plugin (реальный ctx недоступен на этом этапе)
            mock_ctx = MagicMock(spec=PluginContext)
            mock_ctx.config = self._reg.worker_plugin_config
            mock_ctx.log_info = lambda msg: logger.info(f"[worker] {msg}")
            mock_ctx.log_error = lambda msg: logger.error(f"[worker] {msg}")
            mock_ctx.registers = None
            mock_ctx.command_manager = MagicMock()

            instance.configure(mock_ctx)
            return instance
        except Exception as exc:
            logger.error(f"WorkerPoolPlugin: ошибка создания worker plugin: {exc}")
            return None

    # --- команды ---

    def cmd_resize_pool(self, data: dict) -> dict:
        """Изменить размер пула потоков в runtime.

        Принимает pool_size (1..32). Пересоздаёт ThreadPoolExecutor.
        Добавляет недостающие экземпляры sub-plugin если нужно.
        """
        new_size = max(1, min(32, int(data.get("pool_size", self._reg.pool_size))))

        # Остановить текущий пул без ожидания завершения задач
        if self._pool is not None:
            self._pool.shutdown(wait=False)

        self._reg.pool_size = new_size
        self._pool = ThreadPoolExecutor(max_workers=self._reg.pool_size)

        # Дополнить список worker plugin instances если их стало меньше
        if self._reg.worker_plugin_class:
            while len(self._worker_plugins) < self._reg.pool_size:
                wp = self._create_worker_plugin()
                if wp is not None:
                    self._worker_plugins.append(wp)

        logger.info(f"WorkerPoolPlugin: pool resized to {self._reg.pool_size}")
        return {"status": "ok", "pool_size": self._reg.pool_size}

    def cmd_get_stats(self, data: dict) -> dict:
        """Вернуть статистику обработки."""
        return {
            "status": "ok",
            "pool_size": self._reg.pool_size,
            "total_processed": self._total_processed,
            "total_errors": self._total_errors,
            "workers_count": len(self._worker_plugins),
        }
