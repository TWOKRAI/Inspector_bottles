# -*- coding: utf-8 -*-
"""H4: возврат из `lost` берёт новые опорные номера кадра и триггера — обрыв не считается потерей кадров.

Переподключение сеанса входит в `grabbing` из `lost`, минуя `opening`. Плагин, сеанс и `WorkerManager` настоящие,
порт — фейк ядра. Фейк на `start_grabbing` начинает номера заново, поэтому номера "после возврата" подменяются
в `port._frame_meta` во время обрыва. Ожидаемые значения — литералы.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any

import pytest

from multiprocess_framework.modules.process_module.plugins.base import PluginContext
from multiprocess_framework.modules.process_module.plugins.testing import MockProcessServices
from multiprocess_framework.modules.worker_module import WorkerManager
from Services.camera_device import plugin_base
from Services.camera_device.plugin_base import CameraDevicePlugin
from Services.camera_device.testing import fake_port

_CFG = {
    "auto_start": False,
    "camera_id": 4,
    "device_select": "serial",
    "device_serial": "FAKE-0001",
    "timeout_ms": 50,
    "reconnect": True,
    "link_silence_s": 0.0,  # потерю даёт только событие прибора: тест не зависит от сроков тишины
    "reconnect_interval_s": 0.5,
}
_DEADLINE_S = 8.0


def _call(fn: Callable[[], Any]) -> Any:
    box: dict[str, Any] = {}
    worker = threading.Thread(target=lambda: box.update(result=fn()), daemon=True)
    worker.start()
    worker.join(_DEADLINE_S)
    assert not worker.is_alive(), f"вызов не вернулся за {_DEADLINE_S} с"
    return box.get("result")


def _numbers(*frame_nums: int) -> tuple[tuple[int, int, int | None], ...]:
    """`frame_meta` без триггера: `(frame_num, lost_packets, trigger_index)`."""
    return tuple((n, 0, None) for n in frame_nums)


class _Rig:
    """Плагин над фейком, отдающим ровно кадры `port._frame_meta` и дальше молчащим; `produce()` ведёт тест."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, frame_meta: tuple, **cfg: Any) -> None:
        monkeypatch.setattr(plugin_base, "_TICK_S", 0.05)
        port = fake_port.make_link_event_port(frame_period_s=0.01, frame_meta=frame_meta)
        scripted_get_frame = port.get_frame

        def get_frame(timeout_ms: int):
            if port._delivered >= len(port._frame_meta):
                time.sleep(timeout_ms / 1000.0)  # кадры сценария кончились: таймаут, как у настоящего SDK
                return None
            return scripted_get_frame(timeout_ms)

        port.get_frame = get_frame
        self.port = port
        monkeypatch.setattr(plugin_base, "create_port", lambda driver: port)
        config = {**_CFG, **cfg}
        self.services = MockProcessServices(name="cam_h4", config=config)
        self.wm = WorkerManager("test_lost_frames_after_reconnect")
        self.services.worker_manager = self.wm
        self.ctx = PluginContext(services=self.services, config=config, plugin_name="camera_device")
        self.levels: dict[str, object] = {}  # последнее опубликованное значение каждого уровня
        self.published: list[str] = []
        publish = self.ctx.publish_metric

        def spy(name: str, value: object):
            self.levels[name] = value
            self.published.append(name)
            return publish(name, value)

        self.ctx.publish_metric = spy
        self.plugin = CameraDevicePlugin()
        self.plugin.configure(self.ctx)
        assert _call(lambda: self.plugin.cmd_take_device({}))["status"] == "ok"
        self.session = self.plugin._session

    def drive_until(self, pred: Callable[[], bool], message: str) -> None:
        end = time.monotonic() + _DEADLINE_S
        while not pred():
            if time.monotonic() >= end:
                pytest.fail(f"не дождались за {_DEADLINE_S} с: {message}; levels={self.levels}")
            self.plugin.produce()
            time.sleep(0.005)

    def await_frames(self, total: int) -> None:
        """Плагин принял `total` кадров с начала теста (`_seq` растёт на каждый кадр колбэка)."""
        self.drive_until(lambda: self.plugin._seq >= total, f"принято кадров {total}")
        assert self.plugin._seq == total

    def outage(self, frame_meta_after: tuple) -> None:
        """Обрыв и возврат; после возврата порт отдаёт `frame_meta_after`.

        Новый сценарий не длиннее старого: иначе порт отдал бы его хвост ещё до обрыва.
        """
        assert len(frame_meta_after) <= len(self.port._frame_meta)
        total = self.plugin._seq + len(frame_meta_after)
        self.port._frame_meta = frame_meta_after
        self.port.emit_link_event("disconnected")
        self.await_frames(total)
        assert self.session.state == "grabbing"
        assert self.session.link()["outages"] == 1

    def window(self) -> dict[str, object]:
        """Уровни из окна тика, опубликованного ПОСЛЕ вызова."""
        mark = len(self.published)
        self.drive_until(lambda: "trigger_lost" in self.published[mark:], "свежее окно уровней")
        return dict(self.levels)

    def close(self) -> None:
        try:
            if getattr(self.plugin, "_session", None) is not None:
                _call(lambda: self.plugin.shutdown(self.ctx))
        finally:
            self.wm.stop_all_workers(2.0)


@pytest.fixture
def make(monkeypatch):
    rigs: list[_Rig] = []

    def factory(frame_meta: tuple, **cfg: Any) -> _Rig:
        rigs.append(_Rig(monkeypatch, frame_meta, **cfg))
        return rigs[-1]

    yield factory
    for built in rigs:
        built.close()


# Два пути возврата из `lost` в сеансе: без режима триггера в плане `grabbing` ставится сразу после переоткрытия,
# свободный поток (`trigger_mode Off`) — только с первым кадром.
@pytest.mark.parametrize(
    "cfg",
    [{}, {"trigger_managed": True, "trigger_mode": "Off"}],
    ids=["no_trigger_mode", "free_run"],
)
def test_reconnect_with_higher_numbers_not_counted(make, cfg):
    rig = make(_numbers(1, 2, 3, 4, 5, 6, 7, 8, 9, 10), **cfg)
    rig.await_frames(10)

    rig.outage(_numbers(500, 501, 502))

    assert rig.window()["lost_frames"] == 0
    assert rig.session.link()["outages"] == 1


def test_trigger_lost_reference_reset_after_reconnect(make):
    rig = make(tuple((n, 0, n) for n in range(1, 11)))
    rig.await_frames(10)

    # номера кадров после возврата идут с 1 (не потеря и без правки): красным может стать только `trigger_lost`
    rig.outage(((1, 0, 300), (2, 0, 301), (3, 0, 302)))

    window = rig.window()
    assert window["trigger_lost"] == 0
    assert window["lost_frames"] == 0


def test_gap_inside_session_still_counted(make):
    rig = make(_numbers(1, 2, 3, 4, 5, 7))
    rig.await_frames(6)

    assert rig.window()["lost_frames"] == 1
    assert rig.session.link()["outages"] == 0


def test_counted_losses_survive_reconnect_and_new_reference_counts_gaps(make):
    """Возврат из `lost` меняет только опору: накопленный счётчик цел, пропуск после возврата считается."""
    rig = make(((1, 0, 1), (2, 0, 2), (3, 0, 3), (5, 0, 5)))
    rig.await_frames(4)

    rig.outage(((500, 0, 300), (501, 0, 301), (503, 0, 303)))

    window = rig.window()
    assert window["lost_frames"] == 2  # 4 до обрыва и 502 после
    assert window["trigger_lost"] == 2  # 4 до обрыва и 302 после
