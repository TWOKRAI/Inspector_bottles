"""Слепая приёмка задачи 2.6: зеркало прогресса из стора в UDP (``splash.mirror``).

Написано до реализации по ``tasks/2.6.md`` (DESIGN п.4, REDS). Свои сокеты — ``127.0.0.1:0``.
"""

from __future__ import annotations

import socket

from multiprocess_framework.modules.state_store_module.core.delta import MISSING, Delta
from multiprocess_framework.modules.state_store_module.manager.state_store_manager import StateStoreManager


def _delta(path: str, value: object) -> Delta:
    return Delta(path=path, old_value=MISSING, new_value=value, source="test")


class _RecordingManager:
    """Дублёр стора для отказных веток: помнит, что отдали в ``use``."""

    def __init__(self, error: Exception | None = None) -> None:
        self.used: list = []
        self._error = error

    def use(self, middleware) -> None:
        if self._error is not None:
            raise self._error
        self.used.append(middleware)


def test_forwards_only_whole_leaf_and_never_raises():
    from multiprocess_prototype.splash.mirror import ProgressMirror, install_if_enabled

    calls: list = []
    mirror = ProgressMirror(lambda progress_id, leaf: calls.append((progress_id, leaf)))
    leaf = {"percent": 5, "label": "", "done": False, "updated_at": 1.0}

    mirror.after_set(_delta("system.progress.boot", leaf), {})
    assert calls == [("boot", {"percent": 5, "label": "", "done": False, "updated_at": 1.0})]

    calls.clear()
    mirror.after_set(_delta("system.progress.boot.percent", 7), {})
    mirror.after_set(_delta("system.progress.boot.percent", {"percent": 7}), {})
    mirror.after_set(_delta("system.run.state", {"percent": 7}), {})
    mirror.after_set(_delta("system.progress", {"boot": {"percent": 7}}), {})
    mirror.after_set(_delta("system.progress.boot", 7), {})
    mirror.after_set(_delta("system.progress.boot", "done"), {})
    assert calls == []

    attempts: list = []

    def _broken_send(progress_id, leaf):
        attempts.append(progress_id)
        raise RuntimeError("send сломан")

    ProgressMirror(_broken_send).after_set(_delta("system.progress.boot", leaf), {})  # исключения нет
    assert attempts == ["boot"]

    port_env = {"INSPECTOR_SPLASH_PORT": "50000"}
    assert install_if_enabled(None, dict(port_env)) is False

    without_port = _RecordingManager()
    assert install_if_enabled(without_port, {}) is False
    assert without_port.used == []

    bad_port = _RecordingManager()
    assert install_if_enabled(bad_port, {"INSPECTOR_SPLASH_PORT": "abc"}) is False
    assert bad_port.used == []

    assert install_if_enabled(_RecordingManager(RuntimeError("use сломан")), dict(port_env)) is False

    # Якорь: с исправным ``use`` тот же env даёт True и зеркало — отказы выше не вакуумны.
    healthy = _RecordingManager()
    assert install_if_enabled(healthy, dict(port_env)) is True
    assert [middleware.name for middleware in healthy.used] == ["progress_mirror"]


def test_real_store_set_reaches_udp_socket():
    from multiprocess_prototype.splash.mirror import install_if_enabled
    from multiprocess_prototype.splash.protocol import decode

    receiver = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        receiver.bind(("127.0.0.1", 0))
        receiver.settimeout(5.0)
        port = str(receiver.getsockname()[1])

        manager = StateStoreManager(router=None, auto_register_ipc=False)
        assert install_if_enabled(manager, {"INSPECTOR_SPLASH_PORT": port}) is True
        assert manager.get_middleware("progress_mirror") is not None

        result = manager.handle_state_set(
            {
                "data": {
                    "path": "system.progress.boot",
                    "value": {"percent": 5, "label": "", "done": False, "updated_at": 1.0},
                    "source": "ProcessManager",
                }
            }
        )
        assert result["status"] == "ok"

        message = decode(receiver.recv(65535))
        assert message is not None
        assert message["id"] == "boot"
        assert message["percent"] == 5
    finally:
        receiver.close()

    bare = StateStoreManager(router=None, auto_register_ipc=False)
    assert install_if_enabled(bare, {}) is False
    assert bare.get_middleware("progress_mirror") is None
