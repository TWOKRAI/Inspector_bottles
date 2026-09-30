# -*- coding: utf-8 -*-
"""E2E-тесты sandbox-сценария — Task 6.5 (Phase 6).

Финальная верификация всей цепочки sandbox:
- color_mask full pipeline (SandboxPresenter.run_once)
- grayscale full pipeline (SandboxPresenter.run_once)
- stitcher: кнопка «Тест» disabled в UI (qtbot)
- sandbox widget: apply grayscale через QThread (qtbot)
- sandbox widget: show_error не краш (qtbot)

Acceptance criteria из phase-6-plugin-sandbox.md, Task 6.5.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np
import pytest

from ._helpers import make_plugins_services


# ---------------------------------------------------------------------------
# Вспомогательные моки (аналог test_sandbox_presenter.py / test_sandbox_widget.py)
# ---------------------------------------------------------------------------


class _MockEntry:
    """Mock для PluginEntry."""

    def __init__(
        self,
        name: str,
        category: str,
        plugin_class=None,
        inputs: list | None = None,
        register_classes: list | None = None,
        description: str = "",
    ) -> None:
        self.name = name
        self.category = category
        self.plugin_class = plugin_class
        self.inputs = inputs or []
        self.register_classes = register_classes or []
        self.description = description
        self.outputs = []


class _MockRegistry:
    """Mock для PluginRegistry."""

    def __init__(self, entries: list[_MockEntry]) -> None:
        self._entries = {e.name: e for e in entries}

    def get(self, name: str) -> _MockEntry | None:
        return self._entries.get(name)

    def list(self) -> list[_MockEntry]:
        return list(self._entries.values())

    def filter(self, category: str | None = None) -> list[_MockEntry]:
        if category:
            return [e for e in self._entries.values() if e.category == category]
        return list(self._entries.values())


def _make_ctx(registry=None, service_registry=None):
    """AppServices с raw PluginRegistry / ServiceRegistry через bridge."""
    return make_plugins_services(registry=registry, service_registry=service_registry)


# ---------------------------------------------------------------------------
# Импорт реальных плагинов (модульная автофикстура)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module", autouse=True)
def _import_real_plugins():
    """Импортировать реальные плагины чтобы они зарегистрировались в PluginRegistry."""
    import importlib

    importlib.import_module("Plugins.processing.grayscale.plugin")
    importlib.import_module("Plugins.processing.color_mask.plugin")
    importlib.import_module("Plugins.processing.hsv_mask.plugin")
    importlib.import_module("Plugins.processing.blob_detector.plugin")
    importlib.import_module("Plugins.processing.stitcher.plugin")


@pytest.fixture(scope="module")
def all_real_plugins(_import_real_plugins):
    """Импортировать ВСЕ Plugins/**/plugin.py (тот же importlib-механизм) — полный реальный реестр."""
    import importlib
    from pathlib import Path

    import Plugins

    root = Path(Plugins.__path__[0])
    for plugin_file in sorted(root.rglob("plugin.py")):
        rel = plugin_file.relative_to(root).with_suffix("").parts
        importlib.import_module(".".join(("Plugins", *rel)))


@pytest.fixture(scope="module")
def real_registry():
    """PluginRegistry с реально зарегистрированными плагинами (grayscale, color_mask, stitcher)."""
    from multiprocess_framework.modules.process_module.plugins import PluginRegistry

    return PluginRegistry


@pytest.fixture(scope="module")
def ctx_with_real_registry(real_registry):
    """AppContext с реальным PluginRegistry и без сервис-реестра."""
    return _make_ctx(registry=real_registry, service_registry=None)


# ---------------------------------------------------------------------------
# Fixture: minimal_bgr_frame
# ---------------------------------------------------------------------------


@pytest.fixture()
def minimal_bgr_frame() -> np.ndarray:
    """Создать минимальный тестовый BGR-кадр 50×50 с заполненными пикселями.

    Не всё чёрное — закрашены яркие зоны чтобы проверить трансформацию
    (grayscale, color_mask) и убедиться что результат не пустой.

    Структура кадра:
    - Верхняя половина: ярко-красный (BGR: 0, 0, 255) — попадает в color_mask с H≈0
    - Нижняя половина: ярко-зелёный (BGR: 0, 255, 0) — попадает в color_mask с H≈60
    """
    frame = np.zeros((50, 50, 3), dtype=np.uint8)
    # Верхняя половина — ярко-красный (BGR)
    frame[:25, :] = (0, 0, 255)
    # Нижняя половина — ярко-зелёный (BGR)
    frame[25:, :] = (0, 255, 0)
    return frame


# ---------------------------------------------------------------------------
# Тест 1: color_mask full pipeline
# ---------------------------------------------------------------------------


class TestColorMaskFullPipeline:
    """E2E: SandboxPresenter.run_once для color_mask."""

    def test_color_mask_full_pipeline(
        self,
        ctx_with_real_registry,
        minimal_bgr_frame,
    ) -> None:
        """color_mask с широким HSV-диапазоном → результат не None, shape (H, W, 3).

        ColorMaskPlugin кладёт в item["mask"] одноканальную маску (кадр не меняет);
        песочница берёт первый image/*-выход плагина (mask) и сама переводит
        gray → BGR, чтобы вид всегда получал (H, W, 3).
        """
        from multiprocess_prototype.frontend.widgets.tabs.plugins.sandbox_presenter import SandboxPresenter

        presenter = SandboxPresenter(ctx_with_real_registry)
        config = {
            "h_min": 0,
            "h_max": 179,
            "s_min": 0,
            "s_max": 255,
            "v_min": 0,
            "v_max": 255,
        }
        result = presenter.run_once("color_mask", minimal_bgr_frame, config)

        assert result is not None, "color_mask должен вернуть результат, не None"
        assert isinstance(result, np.ndarray)
        # Песочница конвертирует gray-маску в BGR
        assert result.shape == (50, 50, 3), f"Ожидали shape (50, 50, 3), получили {result.shape}"

    def test_color_mask_sandbox_shows_the_mask_not_the_frame(
        self,
        ctx_with_real_registry,
        minimal_bgr_frame,
    ) -> None:
        """Красная половина попадает в H 0..10 (белая), зелёная — нет (чёрная).

        Раньше песочница показывала result["frame"] — вход без изменений.
        """
        from multiprocess_prototype.frontend.widgets.tabs.plugins.sandbox_presenter import SandboxPresenter

        config = {"h_min": 0, "h_max": 10, "s_min": 10, "s_max": 255, "v_min": 10, "v_max": 255}
        out = SandboxPresenter(ctx_with_real_registry).run_once("color_mask", minimal_bgr_frame, config)

        assert out.shape == (50, 50, 3)
        assert out[5, 25].tolist() == [255, 255, 255]
        assert out[45, 25].tolist() == [0, 0, 0]

    def test_hsv_mask_sandbox_shows_the_mask_not_the_frame(
        self,
        ctx_with_real_registry,
        minimal_bgr_frame,
    ) -> None:
        """То же для hsv_mask: первый image/*-выход — mask."""
        from multiprocess_prototype.frontend.widgets.tabs.plugins.sandbox_presenter import SandboxPresenter

        config = {"h_min": 0, "h_max": 10, "s_min": 10, "s_max": 255, "v_min": 10, "v_max": 255}
        out = SandboxPresenter(ctx_with_real_registry).run_once("hsv_mask", minimal_bgr_frame, config)

        assert out.shape == (50, 50, 3)
        assert out[5, 25].tolist() == [255, 255, 255]
        assert out[45, 25].tolist() == [0, 0, 0]

    def test_blob_detector_sandbox_output_key_is_frame_not_mask(
        self,
        ctx_with_real_registry,
        minimal_bgr_frame,
    ) -> None:
        """Выбор ключа вывода: у blob_detector первый image/*-выход — frame, не mask.

        Guard: зелёная нижняя половина видна (не показана маска). Совместимость
        плагина с песочницей проверяет test_blob_detector_is_sandbox_compatible.
        """
        from multiprocess_prototype.frontend.widgets.tabs.plugins.sandbox_presenter import SandboxPresenter

        config = {"h_min": 0, "h_max": 10, "s_min": 10, "s_max": 255, "v_min": 10, "v_max": 255, "draw_contours": False}
        out = SandboxPresenter(ctx_with_real_registry).run_once("blob_detector", minimal_bgr_frame, config)

        assert out.shape == (50, 50, 3)
        assert out[45, 25].tolist() == [0, 255, 0]

    def test_blob_detector_is_sandbox_compatible(self, ctx_with_real_registry) -> None:
        """blob_detector: необязательный вход mask не закрывает песочницу (регрессия T1)."""
        from multiprocess_prototype.frontend.widgets.tabs.plugins.sandbox_presenter import SandboxPresenter

        result = SandboxPresenter(ctx_with_real_registry).check_compatibility("blob_detector")

        assert result.ok is True, result.reason
        assert result.reason == ""

    def test_color_mask_result_not_empty(
        self,
        ctx_with_real_registry,
        minimal_bgr_frame,
    ) -> None:
        """color_mask с полным диапазоном → результирующий массив не нулевой.

        Поскольку входной кадр содержит яркие пиксели, mask при H=[0..179] не пустая.
        """
        from multiprocess_prototype.frontend.widgets.tabs.plugins.sandbox_presenter import SandboxPresenter

        presenter = SandboxPresenter(ctx_with_real_registry)
        config = {
            "h_min": 0,
            "h_max": 179,
            "s_min": 0,
            "s_max": 255,
            "v_min": 0,
            "v_max": 255,
        }
        result = presenter.run_once("color_mask", minimal_bgr_frame, config)

        assert result is not None
        # При полном диапазоне (0..179 HSV) яркий кадр даст ненулевую маску
        # Проверяем что хотя бы часть пикселей ненулевая
        assert np.any(result > 0), "color_mask с полным диапазоном должна дать ненулевые пиксели"

    def test_color_mask_narrow_hue_no_crash(
        self,
        ctx_with_real_registry,
        minimal_bgr_frame,
    ) -> None:
        """color_mask с h_max < h_min → результат не None (не crash), нормальное поведение.

        Edge case из плана: узкий/инвертированный диапазон даёт чёрную маску — не ошибка.
        """
        from multiprocess_prototype.frontend.widgets.tabs.plugins.sandbox_presenter import SandboxPresenter

        presenter = SandboxPresenter(ctx_with_real_registry)
        config = {
            "h_min": 150,
            "h_max": 10,  # h_max < h_min → маска может быть чёрной, но не crash
            "s_min": 0,
            "s_max": 255,
            "v_min": 0,
            "v_max": 255,
        }
        # Не должно бросать исключения
        result = presenter.run_once("color_mask", minimal_bgr_frame, config)
        # result может быть None (если plugin вернул None) или numpy array — оба допустимы
        # Главное — нет краша
        assert result is None or isinstance(result, np.ndarray)


# ---------------------------------------------------------------------------
# Тест 2: grayscale full pipeline
# ---------------------------------------------------------------------------


class TestGrayscaleFullPipeline:
    """E2E: SandboxPresenter.run_once для grayscale."""

    def test_grayscale_full_pipeline(
        self,
        ctx_with_real_registry,
        minimal_bgr_frame,
    ) -> None:
        """grayscale → результат не None, shape == (50, 50, 3).

        GrayscalePlugin возвращает 3-канальный BGR (Gray→BGR) для совместимости.
        """
        from multiprocess_prototype.frontend.widgets.tabs.plugins.sandbox_presenter import SandboxPresenter

        presenter = SandboxPresenter(ctx_with_real_registry)
        result = presenter.run_once("grayscale", minimal_bgr_frame, {})

        assert result is not None, "grayscale должен вернуть результат, не None"
        assert isinstance(result, np.ndarray)
        # GrayscalePlugin → gray_bgr = cvtColor(gray, GRAY2BGR) → (H, W, 3)
        assert result.shape == minimal_bgr_frame.shape, (
            f"Ожидали shape {minimal_bgr_frame.shape}, получили {result.shape}"
        )

    def test_grayscale_channels_equal(
        self,
        ctx_with_real_registry,
        minimal_bgr_frame,
    ) -> None:
        """Граyscale результат: все 3 канала одинаковы (GRAY→BGR дублирует).

        Проверяем что B==G==R (характеристика grayscale-конвертации).
        """
        from multiprocess_prototype.frontend.widgets.tabs.plugins.sandbox_presenter import SandboxPresenter

        presenter = SandboxPresenter(ctx_with_real_registry)
        result = presenter.run_once("grayscale", minimal_bgr_frame, {})

        assert result is not None
        # B==G==R для grayscale-кадра (после GRAY2BGR)
        np.testing.assert_array_equal(result[:, :, 0], result[:, :, 1])
        np.testing.assert_array_equal(result[:, :, 1], result[:, :, 2])


# ---------------------------------------------------------------------------
# Тест 3: stitcher disabled в UI
# ---------------------------------------------------------------------------


class TestStitcherDisabledInUI:
    """Проверка: кнопка «Тест» для stitcher — disabled с непустым tooltip."""

    def test_stitcher_is_disabled_in_ui(self, qtbot) -> None:
        """stitcher → кнопка «Тест» disabled, tooltip непустой (qtbot).

        Создаём mock registry с stitcher и проверяем состояние кнопки
        через _PluginSection.action_buttons() — как это делает реальный UI.
        """
        from multiprocess_prototype.frontend.widgets.tabs.plugins._sections import _PluginSection

        # Mock ctx с stitcher в реестре (processing, но hardcode multi-input)
        stitcher_entry = _MockEntry(
            name="stitcher",
            category="processing",
            description="Сшивка кадров",
        )
        registry = _MockRegistry([stitcher_entry])
        ctx = _make_ctx(registry=registry)

        # Создаём секцию с callback (иначе кнопка disabled по умолчанию)
        dummy_cb = MagicMock()
        section = _PluginSection(ctx, "stitcher", "stitcher", open_sandbox_cb=dummy_cb)
        buttons = section.action_buttons()

        assert len(buttons) == 1, "Должна быть ровно одна кнопка «Тест»"
        btn = buttons[0]
        qtbot.addWidget(btn)

        # Кнопка должна быть disabled для stitcher (hardcode multi-input в SandboxPresenter)
        assert not btn.isEnabled(), "Кнопка «Тест» для stitcher должна быть disabled (семантика multi-input)"
        # Tooltip должен объяснять причину
        assert btn.toolTip(), "Tooltip для disabled stitcher должен быть непустым"

    def test_stitcher_disabled_with_real_registry(
        self,
        qtbot,
        ctx_with_real_registry,
    ) -> None:
        """stitcher из реального PluginRegistry → кнопка disabled с tooltip."""
        from multiprocess_prototype.frontend.widgets.tabs.plugins._sections import _PluginSection

        dummy_cb = MagicMock()
        section = _PluginSection(
            ctx_with_real_registry,
            "stitcher",
            "stitcher",
            open_sandbox_cb=dummy_cb,
        )
        buttons = section.action_buttons()

        assert len(buttons) == 1
        btn = buttons[0]
        qtbot.addWidget(btn)

        assert not btn.isEnabled()
        assert btn.toolTip()
        # Tooltip должен содержать русскую причину
        tooltip = btn.toolTip()
        assert len(tooltip) > 5, f"Tooltip слишком короткий: {tooltip!r}"


# ---------------------------------------------------------------------------
# Тест 4: sandbox widget apply grayscale через QThread
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Правило совместимости на реальном реестре: «от одного кадра» И «без побочных эффектов»
# ---------------------------------------------------------------------------

_SIDE_EFFECT_OR_CONTEXT_CATEGORIES = {"source", "runtime", "control", "io", "output", "sink", "calibration"}


class TestCompatibilityRuleRealRegistry:
    """check_compatibility на полном реальном реестре (все Plugins/**/plugin.py)."""

    def test_every_non_processing_context_category_is_disabled(self, all_real_plugins, ctx_with_real_registry) -> None:
        """Любой плагин категорий source/runtime/control/io/output/sink/calibration → ok=False."""
        from multiprocess_framework.modules.process_module.plugins import PluginRegistry
        from multiprocess_prototype.frontend.widgets.tabs.plugins.sandbox_presenter import SandboxPresenter

        presenter = SandboxPresenter(ctx_with_real_registry)
        entries = [e for e in PluginRegistry.list() if e.category in _SIDE_EFFECT_OR_CONTEXT_CATEGORIES]

        assert entries, "в реальном реестре нет ни одного плагина этих категорий — тест пуст"
        # Категории io/output/sink/calibration должны быть представлены (иначе тест не ловит их удаление).
        assert {"io", "sink", "calibration"} <= {e.category for e in entries}
        opened = [e.name for e in entries if presenter.check_compatibility(e.name).ok]
        assert opened == [], f"побочные эффекты/контекст, но открыты в песочнице: {opened}"

    @pytest.mark.parametrize("name", ["frame_saver", "robot_io"])
    def test_side_effect_plugins_disabled_because_of_side_effects(
        self, all_real_plugins, ctx_with_real_registry, name
    ) -> None:
        """frame_saver (sink) и robot_io (io): отказ именно из-за побочных эффектов.

        Старое правило `len(inputs) > 1` тоже закрывало их (случайно, по числу входов) —
        поэтому проверяем причину, а не только ok=False.
        """
        from multiprocess_prototype.frontend.widgets.tabs.plugins.sandbox_presenter import SandboxPresenter

        result = SandboxPresenter(ctx_with_real_registry).check_compatibility(name)

        assert result.ok is False
        assert "пишет наружу" in result.reason

    def test_single_input_sink_no_longer_passes_by_accident(self, all_real_plugins, ctx_with_real_registry) -> None:
        """mjpeg_sink (sink, единственный вход frame) раньше проходил правило по числу входов."""
        from multiprocess_prototype.frontend.widgets.tabs.plugins.sandbox_presenter import SandboxPresenter

        assert SandboxPresenter(ctx_with_real_registry).check_compatibility("mjpeg_sink").ok is False

    def test_required_non_bgr_input_disables_plugin(self, all_real_plugins, ctx_with_real_registry) -> None:
        """blob_filter: единственный обязательный вход mask не image/bgr → ok=False, причина называет порт."""
        from multiprocess_prototype.frontend.widgets.tabs.plugins.sandbox_presenter import SandboxPresenter

        result = SandboxPresenter(ctx_with_real_registry).check_compatibility("blob_filter")

        assert result.ok is False
        assert "mask" in result.reason

    @pytest.mark.parametrize("name", ["flip", "negative"])
    def test_region_named_bgr_input_keeps_plugin_open(self, all_real_plugins, ctx_with_real_registry, name) -> None:
        """flip/negative: порт назван "region", но это image/bgr = item["frame"] → открыты (имя порта — метка графа)."""
        from multiprocess_prototype.frontend.widgets.tabs.plugins.sandbox_presenter import SandboxPresenter

        result = SandboxPresenter(ctx_with_real_registry).check_compatibility(name)

        assert result.ok is True, result.reason

    def test_flip_run_once_flips_rows(self, all_real_plugins, ctx_with_real_registry) -> None:
        """run_once(flip): первая строка результата == последняя строка входа."""
        from multiprocess_prototype.frontend.widgets.tabs.plugins.sandbox_presenter import SandboxPresenter

        frame = np.arange(6 * 4 * 3, dtype=np.uint8).reshape(6, 4, 3)
        out = SandboxPresenter(ctx_with_real_registry).run_once("flip", frame, {})

        assert out is not None
        assert out[0].tolist() == frame[-1].tolist()
        assert out[-1].tolist() == frame[0].tolist()

    def test_negative_run_once_inverts(self, all_real_plugins, ctx_with_real_registry) -> None:
        """run_once(negative): результат == 255 - вход."""
        from multiprocess_prototype.frontend.widgets.tabs.plugins.sandbox_presenter import SandboxPresenter

        frame = np.arange(6 * 4 * 3, dtype=np.uint8).reshape(6, 4, 3)
        out = SandboxPresenter(ctx_with_real_registry).run_once("negative", frame, {})

        assert out is not None
        assert out.tolist() == (255 - frame).tolist()

    def test_optional_non_frame_input_keeps_plugin_open(self, all_real_plugins, ctx_with_real_registry) -> None:
        """circle_detector: frame и mask оба необязательные, image/bgr среди входов есть → открыт."""
        from multiprocess_prototype.frontend.widgets.tabs.plugins.sandbox_presenter import SandboxPresenter

        assert SandboxPresenter(ctx_with_real_registry).check_compatibility("circle_detector").ok is True


class TestSandboxWidgetApplyGrayscale:
    """E2E: PluginSandboxWidget._on_apply_clicked через QThread → after_label заполнен."""

    def test_sandbox_widget_apply_grayscale(
        self,
        qtbot,
        ctx_with_real_registry,
        minimal_bgr_frame,
    ) -> None:
        """Устанавливаем _current_frame, вызываем _on_apply_clicked → after_label не пустой.

        run_once выполняется в QThreadPool (_SandboxWorker).
        Ждём через qtbot.waitUntil — сигнала нет напрямую, проверяем состояние.
        """
        from PySide6.QtWidgets import QApplication

        from multiprocess_prototype.frontend.widgets.tabs.plugins.sandbox import PluginSandboxWidget
        from multiprocess_prototype.frontend.widgets.tabs.plugins.sandbox_presenter import SandboxPresenter

        presenter = SandboxPresenter(ctx_with_real_registry)
        widget = PluginSandboxWidget(presenter, "grayscale", services=ctx_with_real_registry)
        qtbot.addWidget(widget)

        # Устанавливаем кадр напрямую (минуя QFileDialog)
        widget._current_frame = minimal_bgr_frame.copy()
        widget._btn_apply.setEnabled(True)

        # Применяем — асинхронно через QThreadPool
        widget._on_apply_clicked()

        # Ждём пока after_label заполнится (worker завершится и сигнал придёт)
        def _after_label_filled() -> bool:
            QApplication.processEvents()
            px = widget.after_label.pixmap()
            return px is not None and not px.isNull()

        qtbot.waitUntil(_after_label_filled, timeout=3000)

        # Финальная проверка
        assert widget.after_label.pixmap() is not None
        assert not widget.after_label.pixmap().isNull(), (
            "after_label должен содержать непустой pixmap после apply grayscale"
        )

    def test_sandbox_widget_apply_sets_running_state(
        self,
        qtbot,
        ctx_with_real_registry,
        minimal_bgr_frame,
    ) -> None:
        """После _on_apply_clicked кнопка сначала disabled (running), затем снова enabled.

        Проверяем что set_running(True) вызывается и по завершении кнопка возвращается.
        """
        from PySide6.QtWidgets import QApplication

        from multiprocess_prototype.frontend.widgets.tabs.plugins.sandbox import PluginSandboxWidget
        from multiprocess_prototype.frontend.widgets.tabs.plugins.sandbox_presenter import SandboxPresenter

        presenter = SandboxPresenter(ctx_with_real_registry)
        widget = PluginSandboxWidget(presenter, "grayscale", services=ctx_with_real_registry)
        qtbot.addWidget(widget)

        widget._current_frame = minimal_bgr_frame.copy()
        widget._btn_apply.setEnabled(True)

        widget._on_apply_clicked()

        # После завершения worker'а кнопка должна вернуться в состояние enabled
        def _button_enabled_again() -> bool:
            QApplication.processEvents()
            return widget._btn_apply.isEnabled()

        qtbot.waitUntil(_button_enabled_again, timeout=3000)
        assert widget._btn_apply.isEnabled()
        assert widget._btn_apply.text() == "Применить"


# ---------------------------------------------------------------------------
# Тест 5: show_error не краш
# ---------------------------------------------------------------------------


class TestSandboxNoErrorCrash:
    """Проверка: show_error не падает, label видим."""

    def test_sandbox_no_crash_on_bad_file(
        self,
        qtbot,
        ctx_with_real_registry,
    ) -> None:
        """widget.show_error('тест') → не падает, error label видим.

        Тест эмулирует ситуацию когда файл изображения повреждён или недоступен.
        """
        from multiprocess_prototype.frontend.widgets.tabs.plugins.sandbox import PluginSandboxWidget
        from multiprocess_prototype.frontend.widgets.tabs.plugins.sandbox_presenter import SandboxPresenter

        presenter = SandboxPresenter(ctx_with_real_registry)
        widget = PluginSandboxWidget(presenter, "grayscale", services=ctx_with_real_registry)
        qtbot.addWidget(widget)

        # Изначально error label скрыт
        assert widget._lbl_error.isHidden()

        # Вызываем show_error — не должно падать
        widget.show_error("тест")

        # Label должен стать видимым (isHidden() — не зависит от show() родителя)
        assert not widget._lbl_error.isHidden(), "Error label должен быть видим после show_error"
        assert "тест" in widget._lbl_error.text()

    def test_show_error_russian_message(
        self,
        qtbot,
        ctx_with_real_registry,
    ) -> None:
        """show_error с русской строкой → корректно отображается."""
        from multiprocess_prototype.frontend.widgets.tabs.plugins.sandbox import PluginSandboxWidget
        from multiprocess_prototype.frontend.widgets.tabs.plugins.sandbox_presenter import SandboxPresenter

        presenter = SandboxPresenter(ctx_with_real_registry)
        widget = PluginSandboxWidget(presenter, "grayscale", services=ctx_with_real_registry)
        qtbot.addWidget(widget)

        msg = "Не удалось прочитать изображение — файл повреждён"
        widget.show_error(msg)

        assert not widget._lbl_error.isHidden()
        assert msg in widget._lbl_error.text()

    def test_show_error_then_hide(
        self,
        qtbot,
        ctx_with_real_registry,
    ) -> None:
        """show_error('') после show_error('msg') → label скрывается (не crash)."""
        from multiprocess_prototype.frontend.widgets.tabs.plugins.sandbox import PluginSandboxWidget
        from multiprocess_prototype.frontend.widgets.tabs.plugins.sandbox_presenter import SandboxPresenter

        presenter = SandboxPresenter(ctx_with_real_registry)
        widget = PluginSandboxWidget(presenter, "grayscale", services=ctx_with_real_registry)
        qtbot.addWidget(widget)

        # Показываем ошибку
        widget.show_error("ошибка файла")
        assert not widget._lbl_error.isHidden()

        # Прячем пустой строкой
        widget.show_error("")
        assert widget._lbl_error.isHidden(), "show_error('') должен скрыть label"
