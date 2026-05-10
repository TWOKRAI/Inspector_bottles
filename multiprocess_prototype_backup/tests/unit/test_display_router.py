"""Unit-тесты для DisplayRouter (Phase 6, Task 6.3)."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Добавляем корень multiprocess_prototype в sys.path для плоских импортов
_V3_ROOT = Path(__file__).resolve().parents[2]
if str(_V3_ROOT) not in sys.path:
    sys.path.insert(0, str(_V3_ROOT))

from frontend.managers.display_router import DisplayRouter
from registers.display.schemas import DisplaySubscription
from registers.display.presets import LayoutPreset

# Пути для патчинга (плоские, без multiprocess_prototype префикса)
_SUBSCRIBE_PATH = "frontend.managers.display_router.subscribe_to_camera"
_UNSUBSCRIBE_PATH = "frontend.managers.display_router.unsubscribe_from_camera"


def _make_router(headless: bool = False) -> DisplayRouter:
    """Создать DisplayRouter с мок-зависимостями."""
    return DisplayRouter(MagicMock(), MagicMock(), MagicMock(), headless=headless)


class TestDisplayRouter:
    def test_subscribe_camera_source(self):
        """subscribe с camera_0 → вызывает subscribe_to_camera."""
        with patch(_SUBSCRIBE_PATH, return_value=True) as mock_sub, \
             patch(_UNSUBSCRIBE_PATH, return_value=True):
            dr = _make_router()
            sub = DisplaySubscription(source_ref="camera_0", window_id="win_0")
            result = dr.subscribe(sub)
            assert result is True
            mock_sub.assert_called_once()

    def test_unsubscribe(self):
        """subscribe + unsubscribe → вызывает unsubscribe_from_camera."""
        with patch(_SUBSCRIBE_PATH, return_value=True), \
             patch(_UNSUBSCRIBE_PATH, return_value=True) as mock_unsub:
            dr = _make_router()
            sub = DisplaySubscription(source_ref="camera_0", window_id="win_0")
            dr.subscribe(sub)
            result = dr.unsubscribe(sub.subscription_id)
            assert result is True
            mock_unsub.assert_called_once()

    def test_subscribe_idempotent(self):
        """Дважды subscribe с тем же subscription_id → ok, subscribe_to_camera вызван один раз."""
        with patch(_SUBSCRIBE_PATH, return_value=True) as mock_sub, \
             patch(_UNSUBSCRIBE_PATH, return_value=True):
            dr = _make_router()
            sub = DisplaySubscription(source_ref="camera_0", window_id="win_0")
            dr.subscribe(sub)
            result = dr.subscribe(sub)
            assert result is True
            # subscribe_to_camera вызван ровно один раз (идемпотентность)
            assert mock_sub.call_count == 1

    def test_unsubscribe_unknown_id(self):
        """unsubscribe несуществующего subscription_id → True (идемпотентно)."""
        with patch(_SUBSCRIBE_PATH, return_value=True), \
             patch(_UNSUBSCRIBE_PATH, return_value=True):
            dr = _make_router()
            result = dr.unsubscribe("nonexistent-id-12345")
            assert result is True

    def test_apply_preset_quad(self):
        """apply_preset(QUAD, [0,1,2,3]) → 4 активных подписки."""
        with patch(_SUBSCRIBE_PATH, return_value=True), \
             patch(_UNSUBSCRIBE_PATH, return_value=True):
            dr = _make_router()
            dr.apply_preset(LayoutPreset.QUAD, [0, 1, 2, 3])
            active = dr.get_active_subscriptions()
            assert len(active) == 4

    def test_dispatch_frame(self):
        """add_frame_callback + dispatch_frame → callback вызван с кадром."""
        with patch(_SUBSCRIBE_PATH, return_value=True), \
             patch(_UNSUBSCRIBE_PATH, return_value=True):
            dr = _make_router()
            received_frames = []
            dr.add_frame_callback("win_0", lambda frame: received_frames.append(frame))
            dr.dispatch_frame("display_win_0", "test_frame_data")
            assert received_frames == ["test_frame_data"]

    def test_headless_subscribe_noop(self):
        """headless=True → subscribe возвращает False, subscribe_to_camera не вызывается."""
        with patch(_SUBSCRIBE_PATH, return_value=True) as mock_sub, \
             patch(_UNSUBSCRIBE_PATH, return_value=True):
            dr = _make_router(headless=True)
            sub = DisplaySubscription(source_ref="camera_0", window_id="win_0")
            result = dr.subscribe(sub)
            assert result is False
            mock_sub.assert_not_called()

    def test_parse_camera_id(self):
        """_parse_camera_id корректно разбирает camera_N и processor_N форматы."""
        assert DisplayRouter._parse_camera_id("camera_0") == 0
        assert DisplayRouter._parse_camera_id("camera_5") == 5
        assert DisplayRouter._parse_camera_id("processor_1.region_0.final") == 1
        assert DisplayRouter._parse_camera_id("unknown_format") is None
