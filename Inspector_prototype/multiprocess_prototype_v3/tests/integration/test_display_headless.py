"""Интеграционный тест: headless-режим (N=0 display windows)."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

# Добавляем корень multiprocess_prototype_v3 в sys.path для плоских импортов
_V3_ROOT = Path(__file__).resolve().parents[2]
if str(_V3_ROOT) not in sys.path:
    sys.path.insert(0, str(_V3_ROOT))

from multiprocess_prototype_v3.config.app import AppConfig
from multiprocess_prototype_v3.backend.processes.renderer.config import RendererConfig
from registers.display.schemas import DisplaySubscription
from frontend.managers.display_router import DisplayRouter

_SUBSCRIBE_PATH = "frontend.managers.display_router.subscribe_to_camera"
_UNSUBSCRIBE_PATH = "frontend.managers.display_router.unsubscribe_from_camera"


class TestHeadlessMode:
    def test_headless_app_config_excludes_renderer(self):
        """AppConfig(display_enabled=False).all_process_configs() не содержит RendererConfig."""
        cfg = AppConfig(display_enabled=False)
        configs = cfg.all_process_configs()
        renderer_configs = [c for c in configs if isinstance(c, RendererConfig)]
        assert len(renderer_configs) == 0, (
            "В headless-режиме RendererConfig не должен присутствовать в all_process_configs()"
        )

    def test_headless_display_router_subscribe_noop(self):
        """DisplayRouter с headless=True: subscribe → False, subscribe_to_camera не вызывается."""
        with patch(_SUBSCRIBE_PATH, return_value=True) as mock_sub, \
             patch(_UNSUBSCRIBE_PATH, return_value=True):
            dr = DisplayRouter(MagicMock(), MagicMock(), MagicMock(), headless=True)
            sub = DisplaySubscription(source_ref="camera_0", window_id="win_0")
            result = dr.subscribe(sub)
            assert result is False
            mock_sub.assert_not_called()
