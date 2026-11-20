# -*- coding: utf-8 -*-
"""Task 4c, hazard-тесты автора (REDS 6): жизненный цикл плагина обходит охрану ``run_locked_commands``.

``start()`` при ``auto_start`` и ``shutdown()`` зовут ``cmd_take_device`` / ``cmd_release_device`` прямым вызовом,
а охрана «в running запрещено» стоит только на обработчике, ушедшем в ``register_command``. Значит при взведённом
флаге ``start`` обязан открыть камеру, а ``shutdown`` — закрыть. Два теста раздельно, чтобы мутанты «только start
через command_manager» и «только shutdown через command_manager» ловились независимо.
Проводка (rig, ``pdef``, daemon-поток с дедлайном) — из слепого ``test_run_locked_commands_camera.py``.
"""

from __future__ import annotations

from Services.camera_device.tests.test_run_locked_commands_camera import _pdef, _Rig, _scenario

import pytest

pytestmark = pytest.mark.timeout(60)


def test_start_opens_camera_when_flag_set() -> None:
    """6a: флаг взведён, камера закрыта; ``start(ctx)`` с ``auto_start`` открывает её (прямой вызов минует охрану)."""

    def body(rig: _Rig) -> None:
        plugin = rig.plugin
        assert rig.call("release_device")["status"] == "ok"  # флаг ещё снят
        assert rig.state() == "closed", "предусловие: камера закрыта"
        rig.flag.set()
        plugin.start(plugin._ctx)
        assert rig.state() == "grabbing"

    _scenario(_pdef(), body)


def test_shutdown_closes_camera_when_flag_set() -> None:
    """6b: флаг взведён, камера открыта после ``boot()``; ``shutdown(ctx)`` закрывает её."""

    def body(rig: _Rig) -> None:
        plugin = rig.plugin
        assert rig.state() == "grabbing", "предусловие: камера открыта"
        rig.flag.set()
        plugin.shutdown(plugin._ctx)
        assert rig.state() == "closed"

    _scenario(_pdef(), body)
