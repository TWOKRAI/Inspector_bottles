"""Unit-тесты для display-подписок (Phase 6, Task 6.1)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from multiprocess_prototype_v3.registers.display.schemas import DisplaySubscription
from multiprocess_prototype_v3.registers.display.transform import DisplayTransform
from multiprocess_prototype_v3.registers.display.presets import LayoutPreset, preset_subscriptions


class TestDisplayTransform:
    def test_display_transform_defaults(self):
        """DisplayTransform() создаётся с fps_limit=30, overlay_enabled=True, resize=None."""
        t = DisplayTransform()
        assert t.fps_limit == 30
        assert t.overlay_enabled is True
        assert t.resize_width is None
        assert t.resize_height is None

    def test_display_transform_fps_limit_validation_zero(self):
        """fps_limit=0 → ValidationError (ниже min=1)."""
        with pytest.raises((ValidationError, ValueError)):
            DisplayTransform(fps_limit=0)

    def test_display_transform_fps_limit_validation_over_max(self):
        """fps_limit=200 → ValidationError (выше max=120)."""
        with pytest.raises((ValidationError, ValueError)):
            DisplayTransform(fps_limit=200)

    def test_display_transform_fps_limit_boundaries(self):
        """fps_limit=1 и fps_limit=120 — граничные значения — принимаются."""
        t_min = DisplayTransform(fps_limit=1)
        assert t_min.fps_limit == 1

        t_max = DisplayTransform(fps_limit=120)
        assert t_max.fps_limit == 120


class TestDisplaySubscription:
    def test_display_subscription_round_trip(self):
        """model_dump() / model_validate() — полный round-trip без потерь."""
        sub = DisplaySubscription(source_ref="camera_0", window_id="win_0")
        data = sub.model_dump()
        restored = DisplaySubscription.model_validate(data)
        assert restored.subscription_id == sub.subscription_id
        assert restored.source_ref == sub.source_ref
        assert restored.window_id == sub.window_id
        assert restored.transform.fps_limit == sub.transform.fps_limit

    def test_display_subscription_auto_uuid(self):
        """Два экземпляра DisplaySubscription имеют разные subscription_id."""
        sub1 = DisplaySubscription(source_ref="camera_0", window_id="win_0")
        sub2 = DisplaySubscription(source_ref="camera_0", window_id="win_0")
        assert sub1.subscription_id != sub2.subscription_id


class TestPresetSubscriptions:
    def test_preset_none_returns_empty(self):
        """preset_subscriptions(NONE, [0, 1]) → пустой список."""
        result = preset_subscriptions(LayoutPreset.NONE, [0, 1])
        assert result == []

    def test_preset_single(self):
        """preset_subscriptions(SINGLE, [0]) → 1 подписка с source_ref=camera_0."""
        result = preset_subscriptions(LayoutPreset.SINGLE, [0])
        assert len(result) == 1
        assert result[0].source_ref == "camera_0"
        assert result[0].window_id == "win_0"

    def test_preset_quad(self):
        """preset_subscriptions(QUAD, [0,1,2,3]) → 4 подписки с правильными source_ref и window_id."""
        result = preset_subscriptions(LayoutPreset.QUAD, [0, 1, 2, 3])
        assert len(result) == 4
        for i, sub in enumerate(result):
            assert sub.source_ref == f"camera_{i}"
            assert sub.window_id == f"win_{i}"

    def test_preset_quad_insufficient_cameras(self):
        """preset_subscriptions(QUAD, [0,1]) → 2 подписки (нет краша при нехватке камер)."""
        result = preset_subscriptions(LayoutPreset.QUAD, [0, 1])
        assert len(result) == 2

    def test_preset_custom_returns_empty(self):
        """preset_subscriptions(CUSTOM, [0]) → пустой список."""
        result = preset_subscriptions(LayoutPreset.CUSTOM, [0])
        assert result == []
