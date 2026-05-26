"""Тесты для WireMetricsModel, WireStatus, WireMetrics.

Проверяют:
- корректное хранение данных по ключу (src, tgt)
- разделение сигналов: сигналы испускаются ТОЛЬКО при явном вызове emit_*()
- очистку и удаление отдельных wire-записей
"""

from __future__ import annotations

import pytest

from multiprocess_prototype.frontend.widgets.tabs.pipeline.telemetry import (
    WireMetrics,
    WireMetricsModel,
    WireStatus,
)


# ---------------------------------------------------------------------------
# Фикстура модели
# ---------------------------------------------------------------------------


@pytest.fixture
def model(qtbot):
    """Создать экземпляр WireMetricsModel с QApplication (через qtbot)."""
    m = WireMetricsModel()
    return m


# ---------------------------------------------------------------------------
# Тесты хранения данных
# ---------------------------------------------------------------------------


class TestDataStorage:
    """Тесты корректного сохранения и чтения данных."""

    def test_update_status_stores_value(self, model):
        """update_status сохраняет запись с правильными полями."""
        model.update_status("a", "b", "ok", 123.0)
        result = model.get_status("a", "b")
        assert result is not None
        assert result.state == "ok"
        assert result.last_message_time == 123.0

    def test_update_metrics_stores_value(self, model):
        """update_metrics сохраняет запись с правильными полями."""
        model.update_metrics("proc1", "proc2", fps=30.0, latency_ms=15.5, buffer_fill=0.75)
        result = model.get_metrics("proc1", "proc2")
        assert result is not None
        assert result.fps == 30.0
        assert result.latency_ms == 15.5
        assert result.buffer_fill == 0.75

    def test_get_returns_none_for_unknown(self, model):
        """get_status и get_metrics возвращают None для неизвестного ключа."""
        assert model.get_status("nope", "nope") is None
        assert model.get_metrics("nope", "nope") is None

    def test_update_overrides_existing_entry(self, model):
        """Повторный вызов update_status перезаписывает предыдущую запись."""
        model.update_status("a", "b", "idle", 0.0)
        model.update_status("a", "b", "error", 999.0)
        result = model.get_status("a", "b")
        assert result is not None
        assert result.state == "error"
        assert result.last_message_time == 999.0

    def test_different_keys_stored_independently(self, model):
        """Разные ключи (src, tgt) хранятся независимо друг от друга."""
        model.update_status("a", "b", "ok", 1.0)
        model.update_status("c", "d", "error", 2.0)
        assert model.get_status("a", "b").state == "ok"
        assert model.get_status("c", "d").state == "error"


# ---------------------------------------------------------------------------
# Тесты сигналов
# ---------------------------------------------------------------------------


class TestSignals:
    """Тесты логики испускания сигналов."""

    def test_emit_statuses_signal(self, qtbot, model):
        """emit_statuses() испускает сигнал statuses_changed."""
        model.update_status("x", "y", "ok", 10.0)
        with qtbot.waitSignal(model.statuses_changed, timeout=500) as blocker:
            model.emit_statuses()
        payload = blocker.args[0]
        assert ("x", "y") in payload
        assert payload[("x", "y")].state == "ok"

    def test_emit_metrics_signal(self, qtbot, model):
        """emit_metrics() испускает сигнал metrics_changed."""
        model.update_metrics("p", "q", fps=25.0, latency_ms=8.0, buffer_fill=0.5)
        with qtbot.waitSignal(model.metrics_changed, timeout=500) as blocker:
            model.emit_metrics()
        payload = blocker.args[0]
        assert ("p", "q") in payload
        assert payload[("p", "q")].fps == 25.0

    def test_update_status_does_not_emit_signal(self, qtbot, model):
        """update_status() НЕ испускает сигнал statuses_changed."""
        with qtbot.waitSignal(model.statuses_changed, timeout=100, raising=False) as blocker:
            model.update_status("a", "b", "ok", 0.0)
        # Сигнал не должен был прийти
        assert not blocker.signal_triggered

    def test_update_metrics_does_not_emit_signal(self, qtbot, model):
        """update_metrics() НЕ испускает сигнал metrics_changed."""
        with qtbot.waitSignal(model.metrics_changed, timeout=100, raising=False) as blocker:
            model.update_metrics("a", "b", fps=1.0, latency_ms=1.0, buffer_fill=0.0)
        # Сигнал не должен был прийти
        assert not blocker.signal_triggered

    def test_emit_statuses_payload_is_deepcopy(self, qtbot, model):
        """Сигнал statuses_changed передаёт deepcopy — мутация после emit не влияет."""
        model.update_status("a", "b", "idle", 0.0)
        with qtbot.waitSignal(model.statuses_changed, timeout=500) as blocker:
            model.emit_statuses()
        payload = blocker.args[0]
        # Мутируем исходную модель после emit
        model.update_status("a", "b", "error", 99.0)
        # Перехваченный payload не должен измениться
        assert payload[("a", "b")].state == "idle"


# ---------------------------------------------------------------------------
# Тесты очистки и удаления
# ---------------------------------------------------------------------------


class TestClearAndRemove:
    """Тесты управления жизненным циклом данных."""

    def test_clear_resets_state(self, model):
        """clear() удаляет все записи из обоих словарей."""
        model.update_status("a", "b", "ok", 1.0)
        model.update_metrics("a", "b", fps=10.0, latency_ms=5.0, buffer_fill=0.2)
        model.clear()
        assert model.get_status("a", "b") is None
        assert model.get_metrics("a", "b") is None

    def test_remove_wire_removes_from_both_dicts(self, model):
        """remove_wire() удаляет записи из статусов и метрик одновременно."""
        model.update_status("src", "tgt", "ok", 42.0)
        model.update_metrics("src", "tgt", fps=20.0, latency_ms=3.0, buffer_fill=0.1)
        model.remove_wire("src", "tgt")
        assert model.get_status("src", "tgt") is None
        assert model.get_metrics("src", "tgt") is None

    def test_remove_wire_nonexistent_does_not_raise(self, model):
        """remove_wire() для несуществующего ключа не вызывает исключений."""
        # Не должно бросать KeyError
        model.remove_wire("ghost", "ghost")

    def test_clear_empty_model_does_not_raise(self, model):
        """clear() на пустой модели не вызывает исключений."""
        model.clear()  # Не должно упасть


# ---------------------------------------------------------------------------
# Тесты dataclass-ов
# ---------------------------------------------------------------------------


class TestDataclasses:
    """Тесты корректности дефолтных значений dataclass-ов."""

    def test_wire_status_defaults(self):
        """WireStatus создаётся с дефолтными значениями."""
        ws = WireStatus()
        assert ws.state == "idle"
        assert ws.last_message_time == 0.0

    def test_wire_metrics_defaults(self):
        """WireMetrics создаётся с нулевыми дефолтными значениями."""
        wm = WireMetrics()
        assert wm.fps == 0.0
        assert wm.latency_ms == 0.0
        assert wm.buffer_fill == 0.0
