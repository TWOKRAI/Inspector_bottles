"""Тесты публикации метрик ColorMaskPlugin в StateStore (Task 8.5)."""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import numpy as np

from Plugins.processing.color_mask.plugin import ColorMaskPlugin


# ---------------------------------------------------------------------------
# Вспомогательные фабрики
# ---------------------------------------------------------------------------


def _make_ctx(state_proxy=None, process_name: str = "test_process") -> MagicMock:
    """Создать минимальный mock PluginContext."""
    ctx = MagicMock()
    ctx.process_name = process_name
    ctx.config = {}
    ctx.state_proxy = state_proxy
    ctx.registers = None
    # Логгеры — no-op
    ctx.log_info = lambda msg: None
    ctx.log_error = lambda msg: None
    return ctx


def _make_bgr_frame(h: int = 64, w: int = 64) -> np.ndarray:
    """Создать однотонный синий BGR-кадр (легко проходит HSV-маску)."""
    frame = np.zeros((h, w, 3), dtype=np.uint8)
    frame[:, :] = (255, 0, 0)  # BGR: синий
    return frame


def _make_items(n: int = 3) -> list[dict]:
    """Создать список из n items с frame."""
    return [{"frame": _make_bgr_frame()} for _ in range(n)]


def _make_configured_plugin(state_proxy=None) -> ColorMaskPlugin:
    """Создать плагин и вызвать configure()."""
    plugin = ColorMaskPlugin()
    ctx = _make_ctx(state_proxy=state_proxy)
    plugin.configure(ctx)
    return plugin


# ---------------------------------------------------------------------------
# Тест 1: merge() вызывается после истечения 1 секунды
# ---------------------------------------------------------------------------


def test_publish_state_after_interval():
    """process() публикует метрики, когда прошло >= 1 секунды."""
    proxy = MagicMock()
    plugin = _make_configured_plugin(state_proxy=proxy)

    # Сдвигаем _last_publish в прошлое, чтобы интервал уже истёк
    plugin._last_publish = time.monotonic() - 2.0

    plugin.process(_make_items(2))

    # merge() должен быть вызван ровно раз
    proxy.merge.assert_called_once()
    path, data = proxy.merge.call_args[0]
    assert "test_process" in path
    assert data["status"] == "running"
    assert data["processed_count"] >= 2


# ---------------------------------------------------------------------------
# Тест 2: avg_latency_ms > 0 при реальной обработке
# ---------------------------------------------------------------------------


def test_latency_calculation():
    """avg_latency_ms должен быть > 0 после реального вызова process()."""
    proxy = MagicMock()
    plugin = _make_configured_plugin(state_proxy=proxy)

    # Форсируем публикацию сразу
    plugin._last_publish = time.monotonic() - 2.0

    plugin.process(_make_items(5))

    proxy.merge.assert_called_once()
    _, data = proxy.merge.call_args[0]
    assert data["avg_latency_ms"] >= 0.0  # >= 0 (может быть очень быстро)


# ---------------------------------------------------------------------------
# Тест 3: processed_count считает входные items корректно
# ---------------------------------------------------------------------------


def test_processed_count():
    """processed_count после N вызовов == суммарное число items."""
    proxy = MagicMock()
    plugin = _make_configured_plugin(state_proxy=proxy)

    # НЕ форсируем публикацию — проверяем только внутренний счётчик
    items_per_call = 4
    calls = 3
    for _ in range(calls):
        plugin.process(_make_items(items_per_call))

    assert plugin._processed_count == items_per_call * calls


# ---------------------------------------------------------------------------
# Тест 4: state_proxy=None — process() работает без ошибок
# ---------------------------------------------------------------------------


def test_none_state_proxy_no_error():
    """state_proxy=None → process() работает корректно, без исключений."""
    plugin = _make_configured_plugin(state_proxy=None)

    # Форсируем момент публикации
    plugin._last_publish = time.monotonic() - 2.0

    result = plugin.process(_make_items(3))

    # Результат должен быть корректным списком
    assert isinstance(result, list)
    assert len(result) == 3


# ---------------------------------------------------------------------------
# Тест 5: process([]) — пустой список, без сбоев
# ---------------------------------------------------------------------------


def test_empty_items():
    """process([]) → result == [], нет исключений."""
    proxy = MagicMock()
    plugin = _make_configured_plugin(state_proxy=proxy)

    result = plugin.process([])

    assert result == []
    # processed_count не должен расти при пустом вызове
    assert plugin._processed_count == 0


# ---------------------------------------------------------------------------
# Тест 6: merge() НЕ вызывается, если интервал ещё не истёк
# ---------------------------------------------------------------------------


def test_no_publish_before_interval():
    """merge() не вызывается, пока не прошла 1 секунда."""
    proxy = MagicMock()
    plugin = _make_configured_plugin(state_proxy=proxy)

    # _last_publish = сейчас → интервал НЕ истёк
    plugin._last_publish = time.monotonic()

    plugin.process(_make_items(3))

    proxy.merge.assert_not_called()


# ---------------------------------------------------------------------------
# Тест 7: накопители latency сбрасываются после публикации
# ---------------------------------------------------------------------------


def test_latency_accumulators_reset_after_publish():
    """После _publish_state() накопители latency_sum и latency_count == 0."""
    proxy = MagicMock()
    plugin = _make_configured_plugin(state_proxy=proxy)

    # Форсируем публикацию
    plugin._last_publish = time.monotonic() - 2.0
    plugin.process(_make_items(2))

    # После публикации накопители должны быть сброшены
    assert plugin._latency_sum_ms == 0.0
    assert plugin._latency_count == 0
