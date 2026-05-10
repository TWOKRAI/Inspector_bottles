"""Unit-тесты для DisplayRouter.is_anyone_subscribed (Task 9.8).

Покрывает:
  - subscribe_preview → is_anyone_subscribed возвращает True.
  - unsubscribe_preview → is_anyone_subscribed возвращает False.
  - is_anyone_subscribed для display-окон (через _frame_callbacks).
  - Неизвестный канал → False.
  - dispatch_preview_frame доставляет кадр callback'у.
  - Потокобезопасность: параллельные subscribe/unsubscribe/check.
"""

from __future__ import annotations

import sys
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# sys.path для плоских импортов
_V3_ROOT = Path(__file__).resolve().parents[2]
if str(_V3_ROOT) not in sys.path:
    sys.path.insert(0, str(_V3_ROOT))


# Пути для патчинга
_SUBSCRIBE_PATH = "frontend.managers.display_router.subscribe_to_camera"
_UNSUBSCRIBE_PATH = "frontend.managers.display_router.unsubscribe_from_camera"


def _make_router() -> "DisplayRouter":
    """Создать DisplayRouter с мок-зависимостями."""
    from frontend.managers.display_router import DisplayRouter

    return DisplayRouter(MagicMock(), MagicMock(), MagicMock())


# ===========================================================================
# Тесты is_anyone_subscribed
# ===========================================================================


class TestIsAnyoneSubscribed:
    """Тесты для is_anyone_subscribed API."""

    def test_no_subscribers_returns_false(self):
        """Нет подписчиков → False."""
        dr = _make_router()
        assert dr.is_anyone_subscribed("node_preview.abc123") is False

    def test_after_subscribe_preview_returns_true(self):
        """subscribe_preview → is_anyone_subscribed = True."""
        dr = _make_router()
        dr.subscribe_preview("node_preview.abc123", lambda frame: None)
        assert dr.is_anyone_subscribed("node_preview.abc123") is True

    def test_after_unsubscribe_preview_returns_false(self):
        """subscribe + unsubscribe → is_anyone_subscribed = False."""
        dr = _make_router()
        dr.subscribe_preview("node_preview.abc123", lambda frame: None)
        dr.unsubscribe_preview("node_preview.abc123")
        assert dr.is_anyone_subscribed("node_preview.abc123") is False

    def test_multiple_channels_independent(self):
        """Подписки на разные каналы — независимы."""
        dr = _make_router()
        dr.subscribe_preview("node_preview.aaa", lambda f: None)
        dr.subscribe_preview("node_preview.bbb", lambda f: None)

        assert dr.is_anyone_subscribed("node_preview.aaa") is True
        assert dr.is_anyone_subscribed("node_preview.bbb") is True
        assert dr.is_anyone_subscribed("node_preview.ccc") is False

    def test_display_window_subscriber_via_frame_callback(self):
        """Display-окно через add_frame_callback → is_anyone_subscribed(display_win_0) = True."""
        dr = _make_router()
        dr.add_frame_callback("win_0", lambda frame: None)
        assert dr.is_anyone_subscribed("display_win_0") is True

    def test_display_window_removed_returns_false(self):
        """Удаление frame_callback → is_anyone_subscribed = False."""
        dr = _make_router()
        dr.add_frame_callback("win_0", lambda frame: None)
        dr.remove_frame_callback("win_0")
        assert dr.is_anyone_subscribed("display_win_0") is False

    def test_unknown_channel_returns_false(self):
        """Неизвестный формат канала → False."""
        dr = _make_router()
        assert dr.is_anyone_subscribed("random_channel_42") is False


class TestSubscribePreview:
    """Тесты subscribe_preview / unsubscribe_preview."""

    def test_subscribe_preview_idempotent(self):
        """Повторная подписка — перезаписывает callback (идемпотентно)."""
        dr = _make_router()
        cb1 = MagicMock()
        cb2 = MagicMock()

        dr.subscribe_preview("node_preview.x", cb1)
        dr.subscribe_preview("node_preview.x", cb2)

        # Dispatch должен вызвать cb2 (последний)
        dr.dispatch_preview_frame("node_preview.x", "frame_data")
        cb2.assert_called_once_with("frame_data")
        cb1.assert_not_called()

    def test_unsubscribe_preview_idempotent(self):
        """Отписка несуществующего канала — no-op (без ошибок)."""
        dr = _make_router()
        # Не должно бросить исключение
        dr.unsubscribe_preview("node_preview.nonexistent")


class TestDispatchPreviewFrame:
    """Тесты dispatch_preview_frame."""

    def test_dispatch_calls_callback(self):
        """dispatch_preview_frame вызывает зарегистрированный callback."""
        dr = _make_router()
        cb = MagicMock()
        dr.subscribe_preview("node_preview.test", cb)

        dr.dispatch_preview_frame("node_preview.test", "frame_42")
        cb.assert_called_once_with("frame_42")

    def test_dispatch_no_subscriber_does_nothing(self):
        """dispatch без подписчика → ничего не происходит (без ошибок)."""
        dr = _make_router()
        # Не должно бросить исключение
        dr.dispatch_preview_frame("node_preview.ghost", "frame")


class TestThreadSafety:
    """Тесты потокобезопасности (базовые)."""

    def test_concurrent_subscribe_unsubscribe(self):
        """Параллельные subscribe/unsubscribe не вызывают race condition."""
        dr = _make_router()
        errors: list[Exception] = []

        def subscribe_loop():
            try:
                for i in range(100):
                    dr.subscribe_preview(f"ch.{i}", lambda f: None)
            except Exception as e:
                errors.append(e)

        def unsubscribe_loop():
            try:
                for i in range(100):
                    dr.unsubscribe_preview(f"ch.{i}")
            except Exception as e:
                errors.append(e)

        def check_loop():
            try:
                for i in range(100):
                    dr.is_anyone_subscribed(f"ch.{i}")
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=subscribe_loop),
            threading.Thread(target=unsubscribe_loop),
            threading.Thread(target=check_loop),
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)

        assert errors == [], f"Race condition ошибки: {errors}"
