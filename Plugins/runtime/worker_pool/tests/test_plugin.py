"""Тесты WorkerPoolPlugin: configure, process(), балансировка, команды, shutdown."""

from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np
import pytest

from Plugins.runtime.worker_pool.plugin import WorkerPoolPlugin


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------

def _make_mock_ctx(config: dict | None = None) -> MagicMock:
    """Создать mock PluginContext с нужными атрибутами."""
    ctx = MagicMock()
    ctx.config = config or {}
    ctx.log_info = MagicMock()
    ctx.log_error = MagicMock()
    ctx.command_manager = MagicMock()
    ctx.registers = None
    return ctx


def _make_bgr_frame(h: int = 100, w: int = 100, fill: int = 128) -> np.ndarray:
    """Создать BGR-кадр заданного размера, залитый значением fill."""
    return np.full((h, w, 3), fill, dtype=np.uint8)


def _make_item(fill: int = 128) -> dict:
    """Создать item с ключом frame."""
    return {"frame": _make_bgr_frame(fill=fill)}


def _grayscale_config() -> dict:
    """Конфиг для WorkerPoolPlugin с GrayscalePlugin как sub-plugin."""
    return {
        "pool_size": 2,
        "queue_timeout": 5.0,
        "balancing": "round_robin",
        "worker_plugin_class": (
            "Plugins.processing.grayscale.plugin.GrayscalePlugin"
        ),
        "worker_plugin_config": {},
    }


def _negative_config(pool_size: int = 2) -> dict:
    """Конфиг для WorkerPoolPlugin с NegativePlugin как sub-plugin."""
    return {
        "pool_size": pool_size,
        "queue_timeout": 5.0,
        "balancing": "round_robin",
        "worker_plugin_class": (
            "Plugins.processing.negative.plugin.NegativePlugin"
        ),
        "worker_plugin_config": {},
    }


def _make_started_plugin(config: dict) -> WorkerPoolPlugin:
    """Создать, сконфигурировать и запустить плагин."""
    plugin = WorkerPoolPlugin()
    ctx = _make_mock_ctx(config)
    plugin.configure(ctx)
    plugin.start(ctx)
    return plugin


# ---------------------------------------------------------------------------
# TestConfigure
# ---------------------------------------------------------------------------

class TestConfigure:
    def test_configure_defaults(self):
        """configure() без параметров устанавливает defaults."""
        plugin = WorkerPoolPlugin()
        plugin.configure(_make_mock_ctx({}))

        assert plugin._reg.pool_size == 4
        assert plugin._reg.queue_timeout == 5.0
        assert plugin._reg.balancing == "round_robin"
        assert plugin._reg.worker_plugin_class == ""
        assert plugin._worker_plugins == []
        assert plugin._total_processed == 0
        assert plugin._total_errors == 0

    def test_configure_custom_params(self):
        """configure() парсит все параметры из ctx.config."""
        plugin = WorkerPoolPlugin()
        plugin.configure(_make_mock_ctx({
            "pool_size": 8,
            "queue_timeout": 2.5,
            "balancing": "shortest_queue",
            "worker_plugin_class": "",
            "worker_plugin_config": {"key": "val"},
        }))

        assert plugin._reg.pool_size == 8
        assert plugin._reg.queue_timeout == 2.5
        assert plugin._reg.balancing == "shortest_queue"
        assert plugin._reg.worker_plugin_config == {"key": "val"}

    def test_configure_with_worker_plugin(self):
        """worker_plugin_class → создаётся pool_size экземпляров sub-plugin."""
        plugin = WorkerPoolPlugin()
        plugin.configure(_make_mock_ctx(_grayscale_config()))

        # pool_size=2 → 2 экземпляра GrayscalePlugin
        assert len(plugin._worker_plugins) == 2

    def test_configure_invalid_worker_class(self):
        """Невалидный worker_plugin_class → _worker_plugins пустой, нет исключения."""
        plugin = WorkerPoolPlugin()
        plugin.configure(_make_mock_ctx({
            "worker_plugin_class": "non.existent.module.SomePlugin",
        }))

        assert plugin._worker_plugins == []


# ---------------------------------------------------------------------------
# TestProcess
# ---------------------------------------------------------------------------

class TestProcess:
    def test_empty_items(self):
        """Пустой список items → возвращает пустой список."""
        plugin = _make_started_plugin(_grayscale_config())
        try:
            result = plugin.process([])
            assert result == []
        finally:
            plugin._pool.shutdown(wait=False)

    def test_no_worker_plugin(self):
        """Без worker_plugin_class → items возвращаются без изменений."""
        plugin = _make_started_plugin({"pool_size": 2})
        items = [_make_item(100), _make_item(200)]
        try:
            result = plugin.process(items)
            assert result == items
        finally:
            plugin._pool.shutdown(wait=False)

    def test_single_item_grayscale(self):
        """1 item через GrayscalePlugin → frame изменён (все каналы равны)."""
        plugin = _make_started_plugin(_grayscale_config())
        # Цветной кадр: R≠G≠B
        frame = np.zeros((50, 50, 3), dtype=np.uint8)
        frame[:, :, 0] = 50   # B
        frame[:, :, 1] = 100  # G
        frame[:, :, 2] = 150  # R
        items = [{"frame": frame}]
        try:
            result = plugin.process(items)
            assert len(result) == 1
            out_frame = result[0]["frame"]
            # После grayscale все 3 канала должны быть равны
            assert np.all(out_frame[:, :, 0] == out_frame[:, :, 1])
            assert np.all(out_frame[:, :, 1] == out_frame[:, :, 2])
        finally:
            plugin._pool.shutdown(wait=False)

    def test_multiple_items_negative(self):
        """4 items через NegativePlugin → все items обработаны (инвертированы)."""
        plugin = _make_started_plugin(_negative_config(pool_size=2))
        fill_values = [50, 100, 150, 200]
        items = [_make_item(v) for v in fill_values]
        try:
            result = plugin.process(items)
            assert len(result) == 4
            # Проверить, что каждый frame инвертирован
            for i, item in enumerate(result):
                expected_fill = 255 - fill_values[i]
                assert np.all(item["frame"] == expected_fill), (
                    f"item[{i}]: ожидался fill={expected_fill}, "
                    f"получен {item['frame'][0, 0, 0]}"
                )
        finally:
            plugin._pool.shutdown(wait=False)

    def test_order_preserved(self):
        """Порядок results соответствует порядку входных items."""
        plugin = _make_started_plugin(_negative_config(pool_size=4))
        # Кадры с уникальными значениями для идентификации порядка
        fill_values = [10, 20, 30, 40, 50, 60]
        items = [_make_item(v) for v in fill_values]
        try:
            result = plugin.process(items)
            assert len(result) == len(items)
            # После negative: 255 - v
            for i, (item, orig_fill) in enumerate(zip(result, fill_values)):
                expected = 255 - orig_fill
                actual = int(item["frame"][0, 0, 0])
                assert actual == expected, (
                    f"Нарушен порядок: result[{i}]={actual}, ожидался={expected}"
                )
        finally:
            plugin._pool.shutdown(wait=False)

    def test_error_handling_fallback(self):
        """Ошибка в worker → fallback на оригинальный item, счётчик ошибок растёт."""
        plugin = _make_started_plugin({"pool_size": 2})
        plugin._worker_plugins = [MagicMock()]
        # Настроить mock-plugin чтобы бросал исключение
        plugin._worker_plugins[0].process.side_effect = RuntimeError("test error")

        original_item = _make_item(77)
        try:
            result = plugin.process([original_item])
            assert len(result) == 1
            # Fallback: возвращается оригинальный item
            assert np.array_equal(result[0]["frame"], original_item["frame"])
            assert plugin._total_errors == 1
        finally:
            plugin._pool.shutdown(wait=False)

    def test_stats_incremented(self):
        """total_processed увеличивается после успешной обработки."""
        plugin = _make_started_plugin(_negative_config(pool_size=2))
        items = [_make_item(), _make_item(), _make_item()]
        try:
            plugin.process(items)
            assert plugin._total_processed == 3
            assert plugin._total_errors == 0
        finally:
            plugin._pool.shutdown(wait=False)

    def test_pool_not_started(self):
        """Без вызова start() → items возвращаются без изменений."""
        plugin = WorkerPoolPlugin()
        plugin.configure(_make_mock_ctx(_grayscale_config()))
        # _pool = None, не запускаем start()
        items = [_make_item()]
        result = plugin.process(items)
        assert result == items


# ---------------------------------------------------------------------------
# TestBalancing
# ---------------------------------------------------------------------------

class TestBalancing:
    def test_round_robin_distribution(self):
        """Round-robin распределяет items последовательно по worker'ам."""
        plugin = WorkerPoolPlugin()
        plugin.configure(_make_mock_ctx({
            "pool_size": 3,
            "balancing": "round_robin",
        }))

        # Добавить 3 mock worker-плагина
        workers = [MagicMock() for _ in range(3)]
        for w in workers:
            w.process.return_value = [{"frame": _make_bgr_frame()}]
        plugin._worker_plugins = workers
        plugin.start(_make_mock_ctx({}))

        try:
            # Сбросить счётчик round_robin
            plugin._round_robin_idx = 0

            # Проверить выбор worker'а для 6 items (2 полных круга)
            selected = [plugin._select_worker(i) for i in range(6)]
            assert selected == [0, 1, 2, 0, 1, 2]
        finally:
            plugin._pool.shutdown(wait=False)

    def test_shortest_queue_fallback_to_round_robin(self):
        """shortest_queue — нет очередей у ThreadPoolExecutor, fallback позиционный."""
        plugin = WorkerPoolPlugin()
        plugin.configure(_make_mock_ctx({
            "pool_size": 3,
            "balancing": "shortest_queue",
        }))
        workers = [MagicMock() for _ in range(3)]
        plugin._worker_plugins = workers

        # shortest_queue: item_idx % len(workers)
        assert plugin._select_worker(0) == 0
        assert plugin._select_worker(1) == 1
        assert plugin._select_worker(2) == 2
        assert plugin._select_worker(3) == 0


# ---------------------------------------------------------------------------
# TestCommands
# ---------------------------------------------------------------------------

class TestCommands:
    def test_cmd_resize_pool_increases_size(self):
        """cmd_resize_pool увеличивает размер пула."""
        plugin = _make_started_plugin(_grayscale_config())  # pool_size=2
        try:
            response = plugin.cmd_resize_pool({"pool_size": 4})
            assert response["status"] == "ok"
            assert response["pool_size"] == 4
            assert plugin._reg.pool_size == 4
        finally:
            plugin._pool.shutdown(wait=False)

    def test_cmd_resize_pool_clamps_to_min(self):
        """cmd_resize_pool: значение 0 → clamp до 1."""
        plugin = _make_started_plugin({"pool_size": 2})
        try:
            response = plugin.cmd_resize_pool({"pool_size": 0})
            assert response["pool_size"] == 1
        finally:
            plugin._pool.shutdown(wait=False)

    def test_cmd_resize_pool_clamps_to_max(self):
        """cmd_resize_pool: значение >32 → clamp до 32."""
        plugin = _make_started_plugin({"pool_size": 2})
        try:
            response = plugin.cmd_resize_pool({"pool_size": 100})
            assert response["pool_size"] == 32
        finally:
            plugin._pool.shutdown(wait=False)

    def test_cmd_resize_pool_creates_missing_workers(self):
        """cmd_resize_pool: при увеличении pool_size создаются дополнительные worker plugins."""
        plugin = _make_started_plugin(_grayscale_config())  # pool_size=2, 2 workers
        initial_count = len(plugin._worker_plugins)
        assert initial_count == 2

        try:
            plugin.cmd_resize_pool({"pool_size": 4})
            # Должно стать 4 worker plugin instances
            assert len(plugin._worker_plugins) == 4
        finally:
            plugin._pool.shutdown(wait=False)

    def test_cmd_get_stats_initial(self):
        """cmd_get_stats сразу после configure возвращает нули."""
        plugin = _make_started_plugin(_grayscale_config())
        try:
            response = plugin.cmd_get_stats({})
            assert response["status"] == "ok"
            assert response["total_processed"] == 0
            assert response["total_errors"] == 0
            assert response["pool_size"] == 2
            assert response["workers_count"] == 2
        finally:
            plugin._pool.shutdown(wait=False)

    def test_cmd_get_stats_after_process(self):
        """cmd_get_stats после process() отражает обновлённые счётчики."""
        plugin = _make_started_plugin(_negative_config(pool_size=2))
        items = [_make_item(), _make_item()]
        try:
            plugin.process(items)
            response = plugin.cmd_get_stats({})
            assert response["total_processed"] == 2
            assert response["total_errors"] == 0
        finally:
            plugin._pool.shutdown(wait=False)


# ---------------------------------------------------------------------------
# TestShutdown
# ---------------------------------------------------------------------------

class TestShutdown:
    def test_shutdown_closes_pool(self):
        """shutdown() устанавливает _pool = None."""
        plugin = WorkerPoolPlugin()
        ctx = _make_mock_ctx(_grayscale_config())
        plugin.configure(ctx)
        plugin.start(ctx)

        assert plugin._pool is not None
        plugin.shutdown(ctx)
        assert plugin._pool is None

    def test_shutdown_idempotent(self):
        """Повторный вызов shutdown() не бросает исключений."""
        plugin = WorkerPoolPlugin()
        ctx = _make_mock_ctx({})
        plugin.configure(ctx)
        plugin.start(ctx)
        plugin.shutdown(ctx)
        # Второй shutdown — нет исключений
        plugin.shutdown(ctx)
        assert plugin._pool is None
