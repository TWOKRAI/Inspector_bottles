"""PluginTestBench — изолированное тестирование плагина без запуска процесса.

Использование:
    bench = PluginTestBench(ColorMaskPlugin, config={"h_min": 35, "h_max": 85})
    bench.configure()
    bench.start()

    # Проверить состояние
    assert bench.state == PluginState.RUNNING
    assert "set_hsv_range" in bench.registered_commands

    # Проверить метрики
    snap = bench.metrics_snapshot()
    assert snap["lifecycle"]["configure_ms"] > 0

    bench.shutdown()

Для плагинов с реальной обработкой (cv2):
    bench = PluginTestBench(ColorMaskPlugin, config={...})
    bench.configure()
    bench.start()
    # Подать кадр напрямую — через mock memory_manager
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from .base import PluginContext, PluginState, ProcessModulePlugin
from .metrics import PluginMetrics


class PluginTestBench:
    """Тестовый стенд для плагина — без ProcessModule, без multiprocessing.

    Создаёт mock-окружение (PluginContext с mock-менеджерами),
    позволяет прогнать lifecycle и проверить результат.
    """

    def __init__(
        self,
        plugin_class: type[ProcessModulePlugin],
        config: dict[str, Any] | None = None,
        process_name: str = "test_process",
    ) -> None:
        self.plugin = plugin_class()
        self.config = config or {}
        self.process_name = process_name
        self.metrics = PluginMetrics(self.plugin.name or plugin_class.__name__)

        # Mock-менеджеры
        self._mock_process = MagicMock()
        self._mock_process.name = process_name
        self._mock_process.worker_manager = MagicMock()
        self._mock_process.command_manager = MagicMock()
        self._mock_process.router_manager = MagicMock()
        self._mock_process.memory_manager = MagicMock()
        self._mock_process._log_info = lambda msg: None
        self._mock_process._log_error = lambda msg: None
        self._mock_process.send_message = MagicMock(return_value=True)
        self._mock_process.receive_message = MagicMock(return_value=None)

        # Mock IO
        self._mock_io = MagicMock()

        # Контекст
        self.ctx = PluginContext(
            process_name=process_name,
            config=self.config,
            process=self._mock_process,
            io=self._mock_io,
        )

        # Зарегистрированные команды (перехватываем из mock)
        self.registered_commands: dict[str, Any] = {}
        self._mock_process.command_manager.register_command = self._capture_command

    @property
    def state(self) -> PluginState:
        """Текущее состояние плагина."""
        return self.plugin.state

    def configure(self) -> PluginTestBench:
        """IDLE → READY."""
        with self.metrics.measure("configure"):
            self.plugin._do_configure(self.ctx)
        return self

    def start(self) -> PluginTestBench:
        """READY → RUNNING."""
        with self.metrics.measure("start"):
            self.plugin._do_start(self.ctx)
        return self

    def pause(self) -> PluginTestBench:
        """RUNNING → PAUSED."""
        self.plugin._do_pause(self.ctx)
        return self

    def resume(self) -> PluginTestBench:
        """PAUSED → RUNNING."""
        self.plugin._do_resume(self.ctx)
        return self

    def shutdown(self) -> PluginTestBench:
        """* → STOPPED."""
        with self.metrics.measure("shutdown"):
            self.plugin._do_shutdown(self.ctx)
        return self

    def metrics_snapshot(self) -> dict[str, Any]:
        """Снимок метрик."""
        return self.metrics.snapshot()

    def _capture_command(self, name: str, handler: Any) -> None:
        """Перехватчик для command_manager.register_command."""
        self.registered_commands[name] = handler
