"""Тесты для SandboxPresenter — без qtbot, pure Python.

Покрывает:
- test_check_source_disabled      — source плагин → disabled
- test_check_stitcher_disabled    — stitcher → disabled (hardcode multi-input)
- test_check_grayscale_ok         — grayscale → ok=True
- test_run_once_grayscale         — реальный numpy 10×10 BGR → не None
- test_run_once_no_registry       — ctx без registry → check_compatibility не падает
"""

from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np
import pytest


# ---------------------------------------------------------------------------
# Вспомогательные моки
# ---------------------------------------------------------------------------


class _MockEntry:
    """Mock для PluginEntry."""

    def __init__(
        self,
        name: str,
        category: str,
        plugin_class=None,
        inputs: list | None = None,
    ) -> None:
        self.name = name
        self.category = category
        self.plugin_class = plugin_class
        self.inputs = inputs or []


class _MockRegistry:
    """Mock для PluginRegistry."""

    def __init__(self, entries: list[_MockEntry]) -> None:
        self._entries = {e.name: e for e in entries}

    def get(self, name: str) -> _MockEntry | None:
        return self._entries.get(name)

    def list(self) -> list[_MockEntry]:
        return list(self._entries.values())


def _make_ctx(registry=None) -> MagicMock:
    """Собрать минимальный mock AppContext."""
    ctx = MagicMock()
    ctx.plugin_registry.return_value = registry
    return ctx


# ---------------------------------------------------------------------------
# Фикстуры с реальными плагинами
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module", autouse=True)
def _import_real_plugins():
    """Импортировать реальные плагины чтобы они зарегистрировались в PluginRegistry."""
    import importlib

    # Импорт триггерит @register_plugin декоратор
    importlib.import_module("Plugins.processing.grayscale.plugin")
    importlib.import_module("Plugins.processing.stitcher.plugin")


@pytest.fixture()
def real_registry():
    """PluginRegistry с реально зарегистрированными плагинами."""
    from multiprocess_framework.modules.process_module.plugins import PluginRegistry

    return PluginRegistry


@pytest.fixture()
def ctx_with_real_registry(real_registry):
    """AppContext с реальным PluginRegistry."""
    return _make_ctx(registry=real_registry)


# ---------------------------------------------------------------------------
# Тесты классификатора
# ---------------------------------------------------------------------------


class TestCheckCompatibility:
    """Тесты метода check_compatibility."""

    def test_check_source_disabled(self) -> None:
        """capture (category=source) → disabled с русской причиной."""
        from multiprocess_prototype.frontend.widgets.tabs.plugins.sandbox_presenter import SandboxPresenter

        # Создаём mock registry с source-плагином
        capture_entry = _MockEntry(name="capture", category="source")
        registry = _MockRegistry([capture_entry])
        ctx = _make_ctx(registry=registry)

        presenter = SandboxPresenter(ctx)
        result = presenter.check_compatibility("capture")

        assert result.ok is False
        assert result.reason  # причина непустая
        assert "ServicesTab" in result.reason or "источник" in result.reason.lower()

    def test_check_stitcher_disabled(self, ctx_with_real_registry) -> None:
        """stitcher → disabled (hardcode: семантика N:1 fan-in)."""
        from multiprocess_prototype.frontend.widgets.tabs.plugins.sandbox_presenter import SandboxPresenter

        presenter = SandboxPresenter(ctx_with_real_registry)
        result = presenter.check_compatibility("stitcher")

        assert result.ok is False
        # Причина должна содержать понятное объяснение
        assert result.reason
        assert "pipeline" in result.reason.lower() or "потоков" in result.reason

    def test_check_grayscale_ok(self, ctx_with_real_registry) -> None:
        """grayscale (processing, single-input) → ok=True."""
        from multiprocess_prototype.frontend.widgets.tabs.plugins.sandbox_presenter import SandboxPresenter

        presenter = SandboxPresenter(ctx_with_real_registry)
        result = presenter.check_compatibility("grayscale")

        assert result.ok is True
        assert result.reason == ""

    def test_check_runtime_disabled(self) -> None:
        """runtime категория → disabled."""
        from multiprocess_prototype.frontend.widgets.tabs.plugins.sandbox_presenter import SandboxPresenter

        # Mock entry с категорией runtime
        rt_entry = _MockEntry(name="chain_executor", category="runtime")
        registry = _MockRegistry([rt_entry])
        ctx = _make_ctx(registry=registry)

        presenter = SandboxPresenter(ctx)
        result = presenter.check_compatibility("chain_executor")

        assert result.ok is False
        assert "pipeline" in result.reason.lower() or "контекст" in result.reason

    def test_check_multi_input_port_disabled(self) -> None:
        """Плагин с len(inputs) > 1 → disabled."""
        from multiprocess_prototype.frontend.widgets.tabs.plugins.sandbox_presenter import SandboxPresenter

        # Создаём mock entry с 2 входными портами
        class FakePort:
            def __init__(self, name: str) -> None:
                self.name = name

        entry = _MockEntry(
            name="multi_blend",
            category="processing",
            inputs=[FakePort("frame_a"), FakePort("frame_b")],
        )
        registry = _MockRegistry([entry])
        ctx = _make_ctx(registry=registry)

        presenter = SandboxPresenter(ctx)
        result = presenter.check_compatibility("multi_blend")

        assert result.ok is False
        assert result.reason

    def test_check_unknown_plugin_disabled(self) -> None:
        """Незарегистрированный плагин → disabled (не None, не краш)."""
        from multiprocess_prototype.frontend.widgets.tabs.plugins.sandbox_presenter import SandboxPresenter

        ctx = _make_ctx(registry=_MockRegistry([]))
        presenter = SandboxPresenter(ctx)
        result = presenter.check_compatibility("nonexistent_plugin")

        assert result.ok is False
        assert result.reason

    def test_run_once_no_registry(self) -> None:
        """ctx без registry → check_compatibility не падает, возвращает ok=False."""
        from multiprocess_prototype.frontend.widgets.tabs.plugins.sandbox_presenter import SandboxPresenter

        # ctx.plugin_registry() вернёт None
        ctx = _make_ctx(registry=None)
        presenter = SandboxPresenter(ctx)

        # check_compatibility не должен бросать исключение
        result = presenter.check_compatibility("grayscale")
        assert result.ok is False
        assert result.reason


# ---------------------------------------------------------------------------
# Тесты run_once
# ---------------------------------------------------------------------------


class TestRunOnce:
    """Тесты метода run_once."""

    def test_run_once_grayscale(self, ctx_with_real_registry) -> None:
        """Реальный numpy 10×10 BGR через grayscale → результат не None, правильная форма."""
        from multiprocess_prototype.frontend.widgets.tabs.plugins.sandbox_presenter import SandboxPresenter

        presenter = SandboxPresenter(ctx_with_real_registry)

        # BGR кадр 10×10
        frame = np.zeros((10, 10, 3), dtype=np.uint8)
        frame[:, :] = (100, 150, 200)  # BGR-цвет

        result = presenter.run_once("grayscale", frame, {})

        assert result is not None
        assert isinstance(result, np.ndarray)
        # GrayscalePlugin возвращает 3-канальный BGR (Gray→BGR)
        assert result.shape == (10, 10, 3)

    def test_run_once_no_registry(self) -> None:
        """run_once без registry → возвращает None без исключения."""
        from multiprocess_prototype.frontend.widgets.tabs.plugins.sandbox_presenter import SandboxPresenter

        ctx = _make_ctx(registry=None)
        presenter = SandboxPresenter(ctx)

        frame = np.zeros((10, 10, 3), dtype=np.uint8)
        result = presenter.run_once("grayscale", frame, {})

        assert result is None

    def test_run_once_nonexistent_plugin_returns_none(self, ctx_with_real_registry) -> None:
        """run_once для несуществующего плагина → None без краша."""
        from multiprocess_prototype.frontend.widgets.tabs.plugins.sandbox_presenter import SandboxPresenter

        presenter = SandboxPresenter(ctx_with_real_registry)
        frame = np.zeros((10, 10, 3), dtype=np.uint8)

        result = presenter.run_once("nonexistent_plugin_xyz", frame, {})

        assert result is None

    def test_run_once_exception_returns_none(self, real_registry) -> None:
        """Если plugin.configure() бросает — run_once возвращает None, не краш."""
        from multiprocess_prototype.frontend.widgets.tabs.plugins.sandbox_presenter import SandboxPresenter

        # Создаём плагин-класс который бросает в configure()
        class _BreakingPlugin:
            name = "breaking"
            category = "processing"
            inputs = []
            outputs = []
            commands = {}

            def __init__(self):
                pass

            def configure(self, ctx):
                raise RuntimeError("Намеренная ошибка для теста")

            def process(self, items):
                return items

        # Добавляем в registry mock entry поверх реального registry
        entry = _MockEntry(
            name="breaking_test",
            category="processing",
            plugin_class=_BreakingPlugin,
        )
        mock_registry = MagicMock()
        mock_registry.get.return_value = entry

        ctx = _make_ctx(registry=mock_registry)
        presenter = SandboxPresenter(ctx)
        frame = np.zeros((5, 5, 3), dtype=np.uint8)

        # Не должно бросить исключение
        result = presenter.run_once("breaking_test", frame, {})
        assert result is None
