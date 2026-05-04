"""Тесты для ShmDashboardPanel.

Проверяют acceptance criteria Task 5.1:
  - Создание без ошибок
  - update_metrics с данными → строка с progressbar
  - buffer_fill=0.7 → progressbar 70%, жёлтый цвет
  - buffer_fill=0.9 → progressbar 90%, красный
  - clear() → все строки удалены, placeholder виден
  - Повторный update с тем же key → обновляет, не дублирует

Запуск:
    python -m pytest multiprocess_prototype/tests/unit/test_shm_dashboard_panel.py -v
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QLabel, QProgressBar


# ---------------------------------------------------------------------------
# Фикстура QApplication (создаётся один раз на сессию)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def qapp():
    """Создать или вернуть существующий QApplication для тестов."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


# ---------------------------------------------------------------------------
# Загрузка модуля напрямую (обход circular imports)
# ---------------------------------------------------------------------------

_BASE = Path(__file__).resolve().parents[3]
_PANEL_PATH = (
    _BASE / "multiprocess_prototype" / "frontend" / "widgets"
    / "tabs_setting" / "constructor_tab" / "panels" / "shm_dashboard_panel.py"
)


def _load_panel_module():
    """Загрузить shm_dashboard_panel напрямую по пути."""
    module_name = "_shm_dashboard_panel_direct"
    if module_name in sys.modules:
        return sys.modules[module_name]
    spec = importlib.util.spec_from_file_location(module_name, _PANEL_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


_panel_module = _load_panel_module()
ShmDashboardPanel = _panel_module.ShmDashboardPanel
_WireMetricsRow = _panel_module._WireMetricsRow


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------

def _get_progressbar(row: "_WireMetricsRow") -> QProgressBar:
    """Найти QProgressBar в строке _WireMetricsRow."""
    bars = row.findChildren(QProgressBar)
    assert bars, "QProgressBar не найден в _WireMetricsRow"
    return bars[0]


def _get_stylesheet_color(row: "_WireMetricsRow") -> str:
    """Извлечь цвет из stylesheet QProgressBar::chunk."""
    bar = _get_progressbar(row)
    return bar.styleSheet()


# ---------------------------------------------------------------------------
# Тесты _WireMetricsRow
# ---------------------------------------------------------------------------

class TestWireMetricsRow:
    """Тесты для отдельной строки метрик."""

    def test_creates_without_error(self, qapp):
        """Строка создаётся без ошибок."""
        row = _WireMetricsRow("test_wire")
        assert row is not None

    def test_progressbar_initial_value(self, qapp):
        """Изначально progressbar = 0."""
        row = _WireMetricsRow("wire_a")
        bar = _get_progressbar(row)
        assert bar.value() == 0

    def test_update_sets_value(self, qapp):
        """update() корректно устанавливает значение progressbar."""
        row = _WireMetricsRow("wire_b")
        row.update(fps=30.0, latency_ms=5.0, buffer_fill=0.5)
        bar = _get_progressbar(row)
        assert bar.value() == 50

    def test_yellow_color_at_70_percent(self, qapp):
        """buffer_fill=0.7 → progressbar 70%, жёлтый цвет #ff9800."""
        row = _WireMetricsRow("wire_c")
        row.update(fps=25.0, latency_ms=3.0, buffer_fill=0.7)
        bar = _get_progressbar(row)
        assert bar.value() == 70
        assert "#ff9800" in bar.styleSheet()

    def test_red_color_at_90_percent(self, qapp):
        """buffer_fill=0.9 → progressbar 90%, красный цвет #f44336."""
        row = _WireMetricsRow("wire_d")
        row.update(fps=10.0, latency_ms=15.0, buffer_fill=0.9)
        bar = _get_progressbar(row)
        assert bar.value() == 90
        assert "#f44336" in bar.styleSheet()

    def test_green_color_below_60_percent(self, qapp):
        """buffer_fill=0.4 → зелёный цвет #4caf50."""
        row = _WireMetricsRow("wire_e")
        row.update(fps=60.0, latency_ms=1.0, buffer_fill=0.4)
        bar = _get_progressbar(row)
        assert bar.value() == 40
        assert "#4caf50" in bar.styleSheet()

    def test_clamp_above_100_percent(self, qapp):
        """buffer_fill > 1.0 → clamp до 100%."""
        row = _WireMetricsRow("wire_f")
        row.update(fps=1.0, latency_ms=1.0, buffer_fill=1.5)
        bar = _get_progressbar(row)
        assert bar.value() == 100

    def test_clamp_below_0_percent(self, qapp):
        """buffer_fill < 0.0 → clamp до 0%."""
        row = _WireMetricsRow("wire_g")
        row.update(fps=1.0, latency_ms=1.0, buffer_fill=-0.5)
        bar = _get_progressbar(row)
        assert bar.value() == 0

    def test_metrics_label_text(self, qapp):
        """update() формирует текст fps и latency корректно."""
        row = _WireMetricsRow("wire_h")
        row.update(fps=29.7, latency_ms=4.567, buffer_fill=0.5)
        # Ищем QLabel с метриками (не wire_key label)
        labels = row.findChildren(QLabel)
        metrics_labels = [l for l in labels if "fps" in l.text()]
        assert metrics_labels, "Метка с fps не найдена"
        text = metrics_labels[0].text()
        assert "30fps" in text  # 29.7 округляется до 30
        assert "4.6ms" in text  # 4.567 → 4.6


# ---------------------------------------------------------------------------
# Тесты ShmDashboardPanel
# ---------------------------------------------------------------------------

class TestShmDashboardPanel:
    """Тесты для панели мониторинга SHM Dashboard."""

    def test_creates_without_error(self, qapp):
        """ShmDashboardPanel() создаётся без ошибок."""
        panel = ShmDashboardPanel()
        assert panel is not None

    def test_placeholder_visible_initially(self, qapp):
        """Изначально placeholder не скрыт (isHidden=False), scroll area скрыта."""
        panel = ShmDashboardPanel()
        placeholder_labels = [
            w for w in panel.findChildren(QLabel)
            if "Нет активных" in w.text()
        ]
        assert placeholder_labels, "Placeholder не найден"
        # isHidden() отражает явное скрытие независимо от родительского окна
        assert not placeholder_labels[0].isHidden()

    def test_update_metrics_creates_row(self, qapp):
        """update_metrics с данными → строка с progressbar создаётся."""
        panel = ShmDashboardPanel()
        panel.update_metrics({
            "camera_wire": {"fps": 30.0, "latency_ms": 2.0, "buffer_fill": 0.5}
        })
        assert "camera_wire" in panel._rows

    def test_update_metrics_hides_placeholder(self, qapp):
        """update_metrics → placeholder явно скрыт (isHidden=True)."""
        panel = ShmDashboardPanel()
        panel.update_metrics({
            "wire_1": {"fps": 15.0, "latency_ms": 5.0, "buffer_fill": 0.3}
        })
        placeholder_labels = [
            w for w in panel.findChildren(QLabel)
            if "Нет активных" in w.text()
        ]
        assert placeholder_labels[0].isHidden()

    def test_update_metrics_70_percent_yellow(self, qapp):
        """buffer_fill=0.7 → progressbar 70%, жёлтый цвет."""
        panel = ShmDashboardPanel()
        panel.update_metrics({
            "test_wire": {"fps": 25.0, "latency_ms": 3.0, "buffer_fill": 0.7}
        })
        row = panel._rows["test_wire"]
        bar = _get_progressbar(row)
        assert bar.value() == 70
        assert "#ff9800" in bar.styleSheet()

    def test_update_metrics_90_percent_red(self, qapp):
        """buffer_fill=0.9 → progressbar 90%, красный цвет."""
        panel = ShmDashboardPanel()
        panel.update_metrics({
            "test_wire": {"fps": 5.0, "latency_ms": 20.0, "buffer_fill": 0.9}
        })
        row = panel._rows["test_wire"]
        bar = _get_progressbar(row)
        assert bar.value() == 90
        assert "#f44336" in bar.styleSheet()

    def test_clear_removes_all_rows(self, qapp):
        """clear() → все строки удалены."""
        panel = ShmDashboardPanel()
        panel.update_metrics({
            "wire_a": {"fps": 10.0, "latency_ms": 1.0, "buffer_fill": 0.2},
            "wire_b": {"fps": 20.0, "latency_ms": 2.0, "buffer_fill": 0.4},
        })
        assert len(panel._rows) == 2

        panel.clear()
        assert len(panel._rows) == 0

    def test_clear_shows_placeholder(self, qapp):
        """clear() → placeholder явно не скрыт (isHidden=False)."""
        panel = ShmDashboardPanel()
        panel.update_metrics({
            "wire_x": {"fps": 5.0, "latency_ms": 1.0, "buffer_fill": 0.1}
        })
        panel.clear()
        placeholder_labels = [
            w for w in panel.findChildren(QLabel)
            if "Нет активных" in w.text()
        ]
        assert not placeholder_labels[0].isHidden()

    def test_repeated_update_no_duplicate(self, qapp):
        """Повторный update с тем же key → обновляет, не дублирует."""
        panel = ShmDashboardPanel()
        panel.update_metrics({
            "wire_dup": {"fps": 10.0, "latency_ms": 1.0, "buffer_fill": 0.3}
        })
        panel.update_metrics({
            "wire_dup": {"fps": 20.0, "latency_ms": 2.0, "buffer_fill": 0.8}
        })

        # Строка должна быть ровно одна
        assert len(panel._rows) == 1

        # Значение должно быть обновлено
        row = panel._rows["wire_dup"]
        bar = _get_progressbar(row)
        assert bar.value() == 80

    def test_multiple_wires_sorted(self, qapp):
        """Несколько wire-каналов сортируются по wire_key."""
        panel = ShmDashboardPanel()
        panel.update_metrics({
            "z_wire": {"fps": 1.0, "latency_ms": 1.0, "buffer_fill": 0.1},
            "a_wire": {"fps": 2.0, "latency_ms": 2.0, "buffer_fill": 0.2},
            "m_wire": {"fps": 3.0, "latency_ms": 3.0, "buffer_fill": 0.3},
        })
        assert set(panel._rows.keys()) == {"z_wire", "a_wire", "m_wire"}

    def test_update_with_object_data(self, qapp):
        """update_metrics поддерживает объекты с атрибутами (не только dict)."""

        class FakeMetrics:
            fps = 42.0
            latency_ms = 7.5
            buffer_fill = 0.65

        panel = ShmDashboardPanel()
        panel.update_metrics({"obj_wire": FakeMetrics()})
        row = panel._rows["obj_wire"]
        bar = _get_progressbar(row)
        assert bar.value() == 65

    def test_buffer_fill_clamped_over_1(self, qapp):
        """buffer_fill > 1.0 → clamp до 100% в панели."""
        panel = ShmDashboardPanel()
        panel.update_metrics({
            "overflow_wire": {"fps": 1.0, "latency_ms": 1.0, "buffer_fill": 2.0}
        })
        row = panel._rows["overflow_wire"]
        bar = _get_progressbar(row)
        assert bar.value() == 100
