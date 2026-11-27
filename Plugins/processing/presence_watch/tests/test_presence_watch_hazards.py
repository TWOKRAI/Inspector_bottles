"""Task 2.2d: авторские тесты опасностей ``presence_watch``.

1. REDS 9: ``process`` пересёк ``pause``/``resume`` — запись прошлой работы не попадает в новую
   (два окна: на часах и посреди разбора item).
2. Исключение внутри разбора item: поток не рвётся, одна строка ERROR на (место, тип), значений item нет.
3. Живая правка регистра действует на следующем вызове.
"""

from __future__ import annotations

import threading
from typing import Any

import pytest

import Plugins.processing.presence_watch.plugin as pw
from multiprocess_framework.modules.process_module.plugins.base import PluginContext
from multiprocess_framework.modules.process_module.plugins.testing import MockProcessServices
from Plugins.processing.presence_watch.plugin import PresenceWatchPlugin

ABSENT = [{"severity": "out_of_spec", "reason": "нет изделия"}]
WEAK = [{"severity": "out_of_spec", "reason": "слабое распознавание"}]


def _weak_flag() -> dict:
    return {"predictions": [{"label": "А", "confidence": 0.9, "below_threshold": True}], "sidecar": {"track_id": 1}}


def _make() -> tuple[PresenceWatchPlugin, MockProcessServices]:
    services = MockProcessServices(name="recog", config={})
    plugin = PresenceWatchPlugin()
    plugin.configure(PluginContext(services=services, config={}))
    return plugin, services


def _fake_clock(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    t = [1000.0]
    monkeypatch.setattr(pw, "_clock", lambda: t[0])
    return t


def test_process_straddling_pause_resume_does_not_leak(monkeypatch: pytest.MonkeyPatch) -> None:
    t = [1000.0]
    started = threading.Event()
    release = threading.Event()
    released_in_time: list[bool] = []

    def _clock() -> float:
        if threading.current_thread().name != "conveyor":
            return t[0]
        # Конвейер взял момент 1025.0 и застрял до записи _last_seen.
        started.set()
        released_in_time.append(release.wait(2.0))
        return 1025.0

    monkeypatch.setattr(pw, "_clock", _clock)
    plugin, _ = _make()
    plugin.start(None)

    conveyor = threading.Thread(target=plugin.process, args=([_weak_flag()],), name="conveyor", daemon=True)
    conveyor.start()
    assert started.wait(2.0), "process() не дошёл до часов"
    plugin.pause(None)
    t[0] = 1030.0
    plugin.resume(None)
    release.set()
    conveyor.join(5.0)

    assert not conveyor.is_alive()
    assert released_in_time == [True]
    assert plugin._last_seen == (1025.0, True)  # запись прошлой работы действительно легла после resume
    t[0] = 1031.0
    assert plugin.readiness(None) == []


def test_pause_resume_during_item_parsing_does_not_leak(monkeypatch: pytest.MonkeyPatch) -> None:
    """Пауза и возобновление проходят, пока item РАЗБИРАЕТСЯ: часы уже должны быть прочитаны."""
    started = threading.Event()
    release = threading.Event()
    released_in_time: list[bool] = []

    class _SlowTop(dict):
        """Топ, чей ``get`` в первый раз стоит: конвейер застревает посреди разбора."""

        def get(self, key: Any, default: Any = None) -> Any:
            if not started.is_set():
                started.set()
                released_in_time.append(release.wait(2.0))
            return super().get(key, default)

    t = _fake_clock(monkeypatch)
    plugin, _ = _make()
    plugin.start(None)
    item = {"predictions": [_SlowTop(label="А", below_threshold=True)], "sidecar": {"track_id": 1}}

    t[0] = 1025.0
    conveyor = threading.Thread(target=plugin.process, args=([item],), daemon=True)
    conveyor.start()
    assert started.wait(2.0), "process() не дошёл до разбора топа"
    plugin.pause(None)
    t[0] = 1030.0
    plugin.resume(None)
    t[0] = 1030.5  # любые часы, прочитанные после разбора, были бы уже из новой работы
    release.set()
    conveyor.join(5.0)

    assert not conveyor.is_alive()
    assert released_in_time == [True]
    t[0] = 1031.0
    assert plugin.readiness(None) == []


class _Broken(dict):
    """dict, у которого ``get`` бросает: ломает разбор пути."""

    def get(self, key: Any, default: Any = None) -> Any:
        raise KeyError("секрет-из-item")


def test_broken_item_keeps_stream_and_logs_once_per_place_without_values(monkeypatch: pytest.MonkeyPatch) -> None:
    t = _fake_clock(monkeypatch)
    plugin, services = _make()
    plugin.start(None)
    seen = len(services.logs)
    t[0] = 1001.0

    # место «ключи изделия»: сам item не разбирается — не изделие
    broken_item = _Broken()
    # место «распознавание»: изделие есть (sidecar), топ не разбирается — слабое
    broken_top = {"predictions": [_Broken()], "sidecar": {"track_id": 7}}
    for _ in range(3):
        batch = [broken_item]
        assert plugin.process(batch) is batch
    assert plugin.readiness(None) == []
    for _ in range(3):
        batch = [broken_top]
        assert plugin.process(batch) is batch
    assert plugin.readiness(None) == WEAK

    errors = [r["msg"] for r in services.logs[seen:] if r["level"] == "ERROR"]
    assert errors == [
        "presence_watch: ключи изделия: KeyError",
        "presence_watch: распознавание: KeyError",
    ]


def test_live_register_edit_applies_on_next_call(monkeypatch: pytest.MonkeyPatch) -> None:
    t = _fake_clock(monkeypatch)
    plugin, _ = _make()
    plugin.start(None)
    t[0] = 1005.0
    assert plugin.readiness(None) == []

    plugin._reg.absent_after_s = 5.0
    assert plugin.readiness(None) == ABSENT
    plugin._reg.text_absent = ""
    assert plugin.readiness(None) == []
