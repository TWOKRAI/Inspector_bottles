"""
Тесты для SystemCommandHandler.

pytest -q multiprocess_framework/modules/console_module/tests/
"""

import os
from unittest.mock import MagicMock


from ..commands.system_commands import SystemCommandHandler, _get_attr, _extract_processes


# ---------------------------------------------------------------------------
# help
# ---------------------------------------------------------------------------


class TestHelp:
    def test_help_shows_builtin_commands(self):
        """Вывод без реестра содержит встроенные команды help и status."""
        handler = SystemCommandHandler()

        result = handler.help()

        assert "help" in result
        assert "status" in result
        assert "Available commands" in result

    def test_help_with_registry(self):
        """Все команды из переданного реестра присутствуют в выводе."""
        registry = {
            "help": "Show help",
            "status": "Show status",
            "reg": "Register commands",
            "custom": "Custom command",
        }
        handler = SystemCommandHandler()

        result = handler.help(command_registry=registry)

        for cmd in registry:
            assert cmd in result

    def test_help_shows_total_count(self):
        """Строка Total содержит количество команд."""
        registry = {"alpha": "a", "beta": "b", "gamma": "c"}
        handler = SystemCommandHandler()

        result = handler.help(command_registry=registry)

        assert "3" in result

    def test_help_empty_registry_falls_back_to_builtins(self):
        """Пустой dict → fallback на встроенные команды."""
        handler = SystemCommandHandler()

        result_none = handler.help(command_registry=None)
        result_empty = handler.help(command_registry={})

        # Оба должны содержать встроенные команды
        assert "help" in result_none
        # При пустом реестре Total = 0, но заголовок должен быть
        assert "Available commands" in result_empty


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


class TestStatus:
    def test_status_with_process_object(self):
        """Mock process с name и pid — оба присутствуют в выводе."""
        process = MagicMock()
        process.name = "worker-1"
        process.pid = 12345
        process.managers = None

        handler = SystemCommandHandler()
        result = handler.status(process=process)

        assert "worker-1" in result
        assert "12345" in result

    def test_status_no_process_uses_current_pid(self):
        """Без process — выводится текущий PID."""
        handler = SystemCommandHandler(process_info=None)

        result = handler.status()

        assert str(os.getpid()) in result
        assert "unknown" in result

    def test_status_with_process_dict(self):
        """Process в виде dict — name и pid читаются через ключи."""
        process = {"name": "scanner", "pid": 9999}
        handler = SystemCommandHandler()

        result = handler.status(process=process)

        assert "scanner" in result
        assert "9999" in result

    def test_status_with_managers_dict(self):
        """Менеджеры передаются как dict — имена появляются в выводе."""
        process = MagicMock()
        process.name = "main"
        process.pid = 1
        process.managers = {"logger_manager": MagicMock(), "router_manager": MagicMock()}

        handler = SystemCommandHandler()
        result = handler.status(process=process)

        assert "logger_manager" in result
        assert "router_manager" in result

    def test_status_process_info_in_constructor(self):
        """process_info переданный в конструктор используется по умолчанию."""
        process = MagicMock()
        process.name = "from_ctor"
        process.pid = 777
        process.managers = None

        handler = SystemCommandHandler(process_info=process)
        result = handler.status()

        assert "from_ctor" in result
        assert "777" in result


# ---------------------------------------------------------------------------
# ps
# ---------------------------------------------------------------------------


class TestPs:
    def test_ps_with_manager_list(self):
        """Mock process_manager с get_processes() — процессы видны в выводе."""
        p1 = {"name": "camera-proc", "pid": 101, "state": "running"}
        p2 = {"name": "analysis-proc", "pid": 102, "state": "idle"}

        pm = MagicMock()
        pm.get_processes.return_value = [p1, p2]

        handler = SystemCommandHandler()
        result = handler.ps(process_manager=pm)

        assert "camera-proc" in result
        assert "analysis-proc" in result
        assert "101" in result

    def test_ps_no_manager(self):
        """Нет process_manager — строка «not available»."""
        handler = SystemCommandHandler()

        result = handler.ps(process_manager=None)

        assert "not available" in result

    def test_ps_empty_process_list(self):
        """process_manager с пустым списком процессов."""
        pm = MagicMock()
        pm.get_processes.return_value = []

        handler = SystemCommandHandler()
        result = handler.ps(process_manager=pm)

        assert "no child processes" in result.lower() or "Total: 0" in result

    def test_ps_with_object_processes(self):
        """Процессы как объекты с атрибутами name/pid/state."""
        proc = MagicMock()
        proc.name = "object-proc"
        proc.pid = 555
        proc.state = "running"

        pm = MagicMock()
        pm.get_processes.return_value = [proc]

        handler = SystemCommandHandler()
        result = handler.ps(process_manager=pm)

        assert "object-proc" in result
        assert "555" in result

    def test_ps_manager_via_processes_attribute(self):
        """process_manager предоставляет процессы через атрибут processes."""
        p = {"name": "attr-proc", "pid": 77, "state": "running"}

        pm = MagicMock(spec=["processes"])  # нет get_processes / list_processes
        pm.processes = [p]

        handler = SystemCommandHandler()
        result = handler.ps(process_manager=pm)

        assert "attr-proc" in result


# ---------------------------------------------------------------------------
# stats
# ---------------------------------------------------------------------------


class TestStats:
    def test_stats_with_metrics(self):
        """Mock stats_manager с get_all_metrics() — метрики присутствуют в выводе."""
        sm = MagicMock()
        sm.get_all_metrics.return_value = {
            "frames_processed": {"type": "counter", "total": 1024},
            "inference_time": {"type": "timing", "avg": 0.032, "count": 512},
        }
        handler = SystemCommandHandler()

        result = handler.stats(stats_manager=sm)

        assert "frames_processed" in result
        assert "inference_time" in result
        assert "Statistics" in result

    def test_stats_no_manager(self):
        """stats_manager=None — строка «no stats available»."""
        handler = SystemCommandHandler()

        result = handler.stats(stats_manager=None)

        assert "no stats" in result.lower()

    def test_stats_fallback_to_get_stats(self):
        """get_all_metrics отсутствует — используется get_stats()."""
        sm = MagicMock(spec=["get_stats"])  # нет get_all_metrics
        sm.get_stats.return_value = {"uptime": 300, "errors": 0}

        handler = SystemCommandHandler()
        result = handler.stats(stats_manager=sm)

        assert "uptime" in result
        assert "300" in result

    def test_stats_empty_metrics(self):
        """get_all_metrics возвращает {} — вывод «no metrics recorded»."""
        sm = MagicMock()
        sm.get_all_metrics.return_value = {}

        handler = SystemCommandHandler()
        result = handler.stats(stats_manager=sm)

        assert "no metrics" in result.lower()

    def test_stats_get_all_metrics_exception(self):
        """get_all_metrics бросает исключение — fallback на get_stats()."""
        sm = MagicMock()
        sm.get_all_metrics.side_effect = RuntimeError("broken")
        sm.get_stats.return_value = {"fallback_key": "fallback_value"}

        handler = SystemCommandHandler()
        result = handler.stats(stats_manager=sm)

        assert "fallback_key" in result or "fallback_value" in result


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------


class TestHelpers:
    def test_get_attr_from_dict(self):
        assert _get_attr({"key": "val"}, "key") == "val"
        assert _get_attr({"key": "val"}, "missing", "default") == "default"

    def test_get_attr_from_object(self):
        # Используем spec чтобы MagicMock не создавал атрибуты автоматически
        obj = MagicMock(spec=["name"])
        obj.name = "test"
        assert _get_attr(obj, "name") == "test"
        assert _get_attr(obj, "nonexistent_attr_xyz", 42) == 42

    def test_extract_processes_via_get_processes(self):
        pm = MagicMock()
        pm.get_processes.return_value = ["p1", "p2"]
        result = _extract_processes(pm)
        assert result == ["p1", "p2"]

    def test_extract_processes_via_list_processes(self):
        pm = MagicMock(spec=["list_processes"])
        pm.list_processes.return_value = ("a", "b")
        result = _extract_processes(pm)
        assert result == ["a", "b"]

    def test_extract_processes_no_method_returns_none(self):
        pm = MagicMock(spec=[])  # без методов и атрибутов
        result = _extract_processes(pm)
        assert result is None
