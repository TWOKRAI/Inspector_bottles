"""Тесты ChainExecutorPlugin: configure, process(), команды, shutdown."""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import numpy as np
import pytest

from multiprocess_framework.modules.process_module.plugins.base import PluginContext
from Plugins.chain_executor.plugin import ChainExecutorPlugin


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------

def _make_mock_ctx(config: dict | None = None) -> MagicMock:
    """Создать mock PluginContext для тестов."""
    ctx = MagicMock(spec=PluginContext)
    ctx.config = config or {}
    ctx.log_info = MagicMock()
    ctx.log_error = MagicMock()
    ctx.command_manager = MagicMock()
    ctx.registers = None
    return ctx


def _make_color_frame(h: int = 100, w: int = 100) -> np.ndarray:
    """Создать цветной BGR-кадр (не серый) для тестов."""
    return np.full((h, w, 3), [100, 150, 200], dtype=np.uint8)


def _make_items(frame: np.ndarray | None = None) -> list[dict]:
    """Создать list[dict] с кадром."""
    if frame is None:
        frame = _make_color_frame()
    return [{"frame": frame}]


# Полные пути к реальным плагинам
GRAYSCALE_CLASS = "Plugins.grayscale.plugin.GrayscalePlugin"
NEGATIVE_CLASS = "Plugins.negative.plugin.NegativePlugin"
FLIP_CLASS = "Plugins.flip.plugin.FlipPlugin"


def _grayscale_step(name: str = "gray") -> dict:
    """Конфиг шага grayscale."""
    return {"plugin_class": GRAYSCALE_CLASS, "plugin_name": name, "config": {}}


def _negative_step(name: str = "neg") -> dict:
    """Конфиг шага negative."""
    return {"plugin_class": NEGATIVE_CLASS, "plugin_name": name, "config": {}}


def _flip_step(name: str = "flip") -> dict:
    """Конфиг шага flip."""
    return {"plugin_class": FLIP_CLASS, "plugin_name": name, "config": {}}


# ---------------------------------------------------------------------------
# TestConfigure
# ---------------------------------------------------------------------------

class TestConfigure:
    def test_configure_empty(self):
        """Конфигурация без шагов — цепочка пустая, параметры по умолчанию."""
        plugin = ChainExecutorPlugin()
        ctx = _make_mock_ctx({})
        plugin.configure(ctx)

        assert plugin._steps == []
        assert plugin._reg.parallel is False
        assert plugin._reg.max_workers == 4
        assert plugin._reg.on_error == "skip"

    def test_configure_with_steps(self):
        """Конфигурация с шагами из config — шаги инициализированы."""
        plugin = ChainExecutorPlugin()
        ctx = _make_mock_ctx({
            "steps": [_grayscale_step("gray1")],
        })
        plugin.configure(ctx)

        assert len(plugin._steps) == 1
        assert plugin._steps[0]["name"] == "gray1"

    def test_configure_parallel_params(self):
        """parallel=True, max_workers=2, on_error=fail — параметры применены."""
        plugin = ChainExecutorPlugin()
        ctx = _make_mock_ctx({
            "parallel": True,
            "max_workers": 2,
            "on_error": "fail",
        })
        plugin.configure(ctx)

        assert plugin._reg.parallel is True
        assert plugin._reg.max_workers == 2
        assert plugin._reg.on_error == "fail"

    def test_configure_invalid_plugin_class(self):
        """Шаг с несуществующим классом — логируется ошибка, шаг пропускается."""
        plugin = ChainExecutorPlugin()
        ctx = _make_mock_ctx({
            "steps": [{"plugin_class": "nonexistent.module.BadPlugin", "plugin_name": "bad"}],
        })
        # Не должно бросать исключение
        plugin.configure(ctx)

        # Плохой шаг пропущен
        assert len(plugin._steps) == 0


# ---------------------------------------------------------------------------
# TestSequentialProcess
# ---------------------------------------------------------------------------

class TestSequentialProcess:
    def test_empty_chain(self):
        """Пустая цепочка — items возвращаются без изменений."""
        plugin = ChainExecutorPlugin()
        plugin.configure(_make_mock_ctx({}))

        frame = _make_color_frame()
        items = _make_items(frame)
        result = plugin.process(items)

        assert len(result) == 1
        assert np.array_equal(result[0]["frame"], frame)

    def test_single_step_grayscale(self):
        """Один шаг (grayscale) — кадр стал серым (все каналы одинаковые)."""
        plugin = ChainExecutorPlugin()
        plugin.configure(_make_mock_ctx({
            "steps": [_grayscale_step()],
        }))

        frame = _make_color_frame()
        result = plugin.process(_make_items(frame))

        assert len(result) == 1
        out_frame = result[0]["frame"]
        # После grayscale все три канала одинаковые
        assert out_frame.ndim == 3
        assert np.all(out_frame[:, :, 0] == out_frame[:, :, 1])
        assert np.all(out_frame[:, :, 1] == out_frame[:, :, 2])

    def test_two_steps_grayscale_negative(self):
        """Два шага (grayscale → negative) — оба применены последовательно."""
        plugin = ChainExecutorPlugin()
        plugin.configure(_make_mock_ctx({
            "steps": [_grayscale_step(), _negative_step()],
        }))

        frame = _make_color_frame()
        result = plugin.process(_make_items(frame))

        assert len(result) == 1
        out_frame = result[0]["frame"]

        # grayscale: [100,150,200] → gray ≈ 145 (BGR2GRAY), gray_bgr = [145,145,145]
        # negative: 255 - 145 = 110
        # Результат должен быть серым (все каналы одинаковые) и инвертированным
        assert np.all(out_frame[:, :, 0] == out_frame[:, :, 1])

        # Результат должен отличаться от исходного кадра
        assert not np.array_equal(out_frame, frame)

    def test_error_skip(self):
        """Ошибка в шаге + on_error=skip — цепочка продолжает с текущими items."""
        plugin = ChainExecutorPlugin()
        plugin.configure(_make_mock_ctx({"on_error": "skip"}))

        # Добавляем "сломанный" шаг напрямую
        broken_plugin = MagicMock()
        broken_plugin.process.side_effect = RuntimeError("Тестовая ошибка")
        plugin._steps.append({"name": "broken", "plugin": broken_plugin, "config": {}})

        # Добавляем рабочий шаг после сломанного
        import importlib
        mod = importlib.import_module(
            "Plugins.grayscale.plugin"
        )
        gray_plugin = mod.GrayscalePlugin()
        mock_ctx = MagicMock(spec=PluginContext)
        mock_ctx.config = {}
        mock_ctx.log_info = lambda m: None
        mock_ctx.log_error = lambda m: None
        mock_ctx.registers = None
        mock_ctx.command_manager = MagicMock()
        gray_plugin.configure(mock_ctx)
        plugin._steps.append({"name": "gray", "plugin": gray_plugin, "config": {}})

        frame = _make_color_frame()
        result = plugin.process(_make_items(frame))

        # Цепочка продолжилась после ошибки — grayscale применён
        assert len(result) == 1
        out_frame = result[0]["frame"]
        assert np.all(out_frame[:, :, 0] == out_frame[:, :, 1])

    def test_error_fail(self):
        """Ошибка в шаге + on_error=fail — цепочка останавливается."""
        plugin = ChainExecutorPlugin()
        plugin.configure(_make_mock_ctx({"on_error": "fail"}))

        # Первый шаг — сломан
        broken_plugin = MagicMock()
        broken_plugin.process.side_effect = RuntimeError("Тестовая ошибка")
        plugin._steps.append({"name": "broken", "plugin": broken_plugin, "config": {}})

        # Второй шаг — grayscale (не должен выполниться)
        second_plugin = MagicMock()
        second_plugin.process.return_value = [{"frame": np.zeros((100, 100, 3), dtype=np.uint8)}]
        plugin._steps.append({"name": "second", "plugin": second_plugin, "config": {}})

        frame = _make_color_frame()
        result = plugin.process(_make_items(frame))

        # Второй шаг НЕ вызван — цепочка остановилась
        second_plugin.process.assert_not_called()

        # Результат — исходный frame (до ошибки)
        assert len(result) == 1
        assert np.array_equal(result[0]["frame"], frame)

    def test_multiple_items(self):
        """Несколько items в батче — все обработаны."""
        plugin = ChainExecutorPlugin()
        plugin.configure(_make_mock_ctx({
            "steps": [_grayscale_step()],
        }))

        frames = [_make_color_frame() for _ in range(3)]
        items = [{"frame": f} for f in frames]
        result = plugin.process(items)

        assert len(result) == 3
        for item in result:
            out = item["frame"]
            # Все каналы одинаковые (grayscale)
            assert np.all(out[:, :, 0] == out[:, :, 1])


# ---------------------------------------------------------------------------
# TestParallelProcess
# ---------------------------------------------------------------------------

class TestParallelProcess:
    def test_parallel_execution(self):
        """parallel=True — все шаги выполнены, результаты собраны."""
        plugin = ChainExecutorPlugin()
        plugin.configure(_make_mock_ctx({
            "parallel": True,
            "max_workers": 2,
            "steps": [_grayscale_step("gray"), _negative_step("neg")],
        }))
        plugin.start(_make_mock_ctx())

        frame = _make_color_frame()
        result = plugin.process(_make_items(frame))

        # Параллельно: grayscale + negative, результаты мержатся (extend)
        # 1 item × 2 шага = 2 items в результате
        assert len(result) == 2

        plugin.shutdown(_make_mock_ctx())

    def test_parallel_pool_created(self):
        """start() с parallel=True создаёт ThreadPoolExecutor."""
        plugin = ChainExecutorPlugin()
        plugin.configure(_make_mock_ctx({
            "parallel": True,
            "max_workers": 3,
        }))

        assert plugin._pool is None
        plugin.start(_make_mock_ctx())
        assert plugin._pool is not None

        plugin.shutdown(_make_mock_ctx())

    def test_parallel_fallback_on_no_pool(self):
        """parallel=True без pool (до start) — использует sequential."""
        plugin = ChainExecutorPlugin()
        plugin.configure(_make_mock_ctx({
            "parallel": True,
            "steps": [_grayscale_step()],
        }))
        # pool не создан (start не вызван)
        assert plugin._pool is None

        frame = _make_color_frame()
        result = plugin.process(_make_items(frame))

        # Sequential fallback: 1 item → 1 item
        assert len(result) == 1


# ---------------------------------------------------------------------------
# TestCommands
# ---------------------------------------------------------------------------

class TestCommands:
    def _configured_plugin(self, extra_cfg: dict | None = None) -> ChainExecutorPlugin:
        """Создать и сконфигурировать плагин."""
        plugin = ChainExecutorPlugin()
        cfg = extra_cfg or {}
        plugin.configure(_make_mock_ctx(cfg))
        return plugin

    def test_cmd_add_step(self):
        """cmd_add_step добавляет шаг в цепочку."""
        plugin = self._configured_plugin()
        assert len(plugin._steps) == 0

        response = plugin.cmd_add_step(_grayscale_step("g1"))

        assert response["status"] == "ok"
        assert response["steps_count"] == 1
        assert plugin._steps[0]["name"] == "g1"

    def test_cmd_add_step_invalid(self):
        """cmd_add_step с несуществующим классом — status=error."""
        plugin = self._configured_plugin()
        response = plugin.cmd_add_step({
            "plugin_class": "bad.module.BadPlugin",
            "plugin_name": "bad",
        })

        assert response["status"] == "error"
        assert response["steps_count"] == 0

    def test_cmd_remove_step(self):
        """cmd_remove_step удаляет шаг по имени."""
        plugin = self._configured_plugin({
            "steps": [_grayscale_step("g1"), _negative_step("n1")],
        })
        assert len(plugin._steps) == 2

        response = plugin.cmd_remove_step({"name": "g1"})

        assert response["status"] == "ok"
        assert response["removed"] == 1
        assert response["steps_count"] == 1
        assert plugin._steps[0]["name"] == "n1"

    def test_cmd_remove_step_not_found(self):
        """cmd_remove_step с несуществующим именем — removed=0."""
        plugin = self._configured_plugin({
            "steps": [_grayscale_step("g1")],
        })

        response = plugin.cmd_remove_step({"name": "no_such_step"})

        assert response["status"] == "ok"
        assert response["removed"] == 0
        assert response["steps_count"] == 1

    def test_cmd_reorder_steps(self):
        """cmd_reorder_steps меняет порядок шагов."""
        plugin = self._configured_plugin({
            "steps": [
                _grayscale_step("g1"),
                _negative_step("n1"),
                _flip_step("f1"),
            ],
        })
        assert [s["name"] for s in plugin._steps] == ["g1", "n1", "f1"]

        response = plugin.cmd_reorder_steps({"order": ["f1", "g1", "n1"]})

        assert response["status"] == "ok"
        assert response["order"] == ["f1", "g1", "n1"]

    def test_cmd_reorder_steps_partial(self):
        """cmd_reorder_steps с частичным списком — остаток добавляется в конец."""
        plugin = self._configured_plugin({
            "steps": [
                _grayscale_step("g1"),
                _negative_step("n1"),
                _flip_step("f1"),
            ],
        })

        response = plugin.cmd_reorder_steps({"order": ["n1"]})

        # n1 первый, остальные — в конец в исходном порядке
        assert response["order"][0] == "n1"
        assert set(response["order"]) == {"g1", "n1", "f1"}

    def test_cmd_get_steps(self):
        """cmd_get_steps возвращает список имён и конфигов шагов."""
        plugin = self._configured_plugin({
            "steps": [_grayscale_step("g1"), _negative_step("n1")],
        })

        response = plugin.cmd_get_steps({})

        assert response["status"] == "ok"
        assert len(response["steps"]) == 2
        assert response["steps"][0]["name"] == "g1"
        assert response["steps"][1]["name"] == "n1"
        # config должен быть dict
        assert isinstance(response["steps"][0]["config"], dict)


# ---------------------------------------------------------------------------
# TestShutdown
# ---------------------------------------------------------------------------

class TestShutdown:
    def test_shutdown_cleans_pool(self):
        """shutdown закрывает ThreadPoolExecutor и обнуляет _pool."""
        plugin = ChainExecutorPlugin()
        plugin.configure(_make_mock_ctx({"parallel": True, "max_workers": 2}))
        plugin.start(_make_mock_ctx())

        assert plugin._pool is not None
        plugin.shutdown(_make_mock_ctx())

        assert plugin._pool is None

    def test_shutdown_no_pool(self):
        """shutdown без pool (sequential режим) — не падает."""
        plugin = ChainExecutorPlugin()
        plugin.configure(_make_mock_ctx({}))

        # Не должно бросать исключение
        plugin.shutdown(_make_mock_ctx())

    def test_shutdown_calls_substep_shutdown(self):
        """shutdown вызывает shutdown на каждом sub-plugin."""
        plugin = ChainExecutorPlugin()
        plugin.configure(_make_mock_ctx({}))

        # Добавляем mock sub-plugin
        mock_sub = MagicMock()
        plugin._steps.append({"name": "mock_step", "plugin": mock_sub, "config": {}})

        plugin.shutdown(_make_mock_ctx())

        # sub-plugin.shutdown вызван
        mock_sub.shutdown.assert_called_once()
