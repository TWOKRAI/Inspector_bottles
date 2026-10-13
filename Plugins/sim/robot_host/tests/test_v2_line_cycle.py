# -*- coding: utf-8 -*-
"""Слепая приёмка T2.4 (RED до кода): цикл «кадр -> задание -> DONE» на v2-хосте и ``SceneSourcePlugin``.

Образец сборки сцены — ``Plugins/sim/scene_source/tests/test_acceptance_5_1b.py``
(фейковый ``StateProxy``, один объект на первом ``produce()``).

Связка плагинов в одном окружении (DESIGN п.5): настоящий ``SimRobotHostPlugin`` (v2) и
настоящий ``SceneSourcePlugin`` живут в одном тесте; шина между процессами подменена на уровне
КЛАССА ``DeviceHubClient.send_fire_and_forget`` — событие хоста ``scene.job_done`` доставляется в
``scene.cmd_job_done`` (подмена не зависит от того, из какого модуля хост v2 импортирует клиент).
Хост НЕ подменяется. Энкодер в сцену НЕ идёт через общий мир (хост и сцена не делят ``state_proxy``):
стенд читает ``TLM_ENC`` хоста по проводу и кормит им сцену — это допущение стенда.

Положение объекта берётся у сцены (``scene._spawner.active_objects()`` — паспорт, как в тестах 5.1b;
``scene.status`` положения не отдаёт, только счётчик ``active`` и ``recent``) и переводится в
координаты робота продуктовой функцией ``object_robot_xy`` — pick НЕ литерал теста.
"""

from __future__ import annotations

import random
import time
import uuid
from pathlib import Path
from typing import Callable
from unittest.mock import MagicMock

import numpy as np
import pytest

from multiprocess_framework.modules.state_store_module.core.delta import Delta
from Plugins.hub.device_hub.client import DeviceHubClient
from Plugins.sim.robot_host.tests.host_harness import (
    close_client,
    encoder,
    free_port,
    make_host,
    open_client,
    read_reg,
    run_with_deadline,
    wait_done_hb,
)
from Plugins.sim.scene_source.plugin import SceneSourcePlugin
from Services.dataset_gen.core.catalog import imwrite_unicode
from Services.line_sim.core.matching import BeltGeometry, object_robot_xy
from Services.robot_comm import ROBOT_AVAILABLE

pytestmark = [
    pytest.mark.skipif(not ROBOT_AVAILABLE, reason="pymodbus не установлен"),
]

# Точка укладки: радиус ~412 мм, при P_HAND = 1 суставы J1 55.8 град (|J1| <= 100) — литерал из тестов ядра
# (Services/robot_comm/tests/test_sim_v2_cvt_wdg_vfd.py, ревью лида 2026-10-12), не выведен из кода под тестом.
_PLACE_X_MM, _PLACE_Y_MM, _PLACE_RZ_DEG = 400.0, 100.0, 45.0
# Точка «путь 0» сцены в координатах робота: объект при ecap == spawn_encoder лежит ровно здесь
# (300, -200) — pick, который ядро v2 принимает (те же тесты ядра).
_GEOMETRY_CFG = {"origin_x_mm": 300.0, "origin_y_mm": -200.0}
_JOB_INDEX = 1  # счёт принятых CVT_JOB с 1, а не seq команды (seq клиента случайный, seed 1013 — предусловие ниже)


class _FakeStateProxy:
    def __init__(self) -> None:
        self._callbacks: list[Callable[[list[Delta]], None]] = []

    def subscribe(self, pattern, callback, exclude_self=True, sync=True):
        self._callbacks.append(callback)
        return str(uuid.uuid4())

    def emit(self, deltas: list[Delta]) -> None:
        for cb in self._callbacks:
            cb(deltas)

    def set(self, path: str, value: object) -> None:
        pass


def _make_scene(tmp_path: Path) -> tuple[SceneSourcePlugin, _FakeStateProxy]:
    """Сцена с одним объектом на первом тике (огромный шаг спавна), геометрия — ``_GEOMETRY_CFG``."""
    class_dir = tmp_path / "classes" / "square"
    class_dir.mkdir(parents=True)
    sprite = np.zeros((16, 16, 4), dtype=np.uint8)
    sprite[:, :, :3] = 128
    sprite[:, :, 3] = 255
    imwrite_unicode(class_dir / "sprite.png", sprite)

    state_proxy = _FakeStateProxy()
    ctx = MagicMock()
    ctx.state_proxy = state_proxy
    ctx.config = {
        "resolution_width": 640,
        "resolution_height": 480,
        "spawn_encoder": 0,
        "px_per_mm": 1.0,
        "stale_ms": 60000,
        "preset_path": str(tmp_path / "classes"),
        "spawn_spacing_mm": [1e9, 1e9],
        "scene_length_mm": 1e9,
        "geometry": dict(_GEOMETRY_CFG),
    }
    plugin = SceneSourcePlugin()
    plugin.configure(ctx)
    plugin.start(ctx)
    return plugin, state_proxy


def _push_encoder(sp: _FakeStateProxy, value: float) -> None:
    sp.emit(
        [
            Delta(
                path="sim.belt.encoder",
                old_value=object(),
                new_value={"value": value, "mm_s": 0.0, "t": time.monotonic()},
                source="robot",
            )
        ]
    )


def test_frame_to_job_to_done_cycle(tmp_path, monkeypatch) -> None:
    """Кадр сцены -> объект -> ``SERVO 1``/``HB_PC``/``CVT_JOB`` по TCP v2-хосту -> ``DONE_SEQ`` ->
    ``scene.job_done`` с ``index == 1`` (первое принятое задание) -> сцена сопоставила его с объектом (``matched``).

    ``index`` в событии — счёт принятых ``CVT_JOB`` с 1 (как у v1, ``sim_core.py``), а не ``seq`` команды
    (seq клиента случайный, ``rng=random.Random(1013)``; предусловие ``job.seq != _JOB_INDEX``):
    так различимы две трактовки. Допущение A2 тестера («index == seq») — неверная модель, исправлено лидом.
    Pick — из паспорта объекта сцены (не литерал),
    ``ecap`` — энкодер объекта (``spawn_encoder``); place — литерал ядра с ``|J1| <= 100`` при
    ``P_HAND = 1``. Дедлайн всему DONE — 30 с (``job_ms`` не задан: берётся умолчание хоста).

    НЕ доказывает: что кадр (картинка) попал в зрение — объект берётся из паспорта, не из пикселей;
    что энкодер сцены и хоста едут вместе (лента стоит, оба равны ``TLM_ENC``); что событие уходит
    ровно одно (проверяется ``len == 1`` только на момент проверки, не дальше)."""
    sent: list[tuple[str, str, dict | None]] = []
    scene, sp = _make_scene(tmp_path)

    def _fake_send(self, command, args=None):
        sent.append((self._target, command, args))
        scene.cmd_job_done(args)
        return True

    monkeypatch.setattr(DeviceHubClient, "send_fire_and_forget", _fake_send)

    port = free_port()
    plugin, ctx, _services, workers = make_host(port, protocol="v2", scene_process="camera")
    device = None
    try:
        run_with_deadline(lambda: plugin.start(ctx), timeout=10.0, label="start")
        device, client = open_client(port, rng=random.Random(1013))
        assert read_reg(device, "TLM_PROTO_VER")[0] == 0x0200, "хост не v2 — цикл бессмыслен"

        # --- кадр: энкодер хоста -> сцена, объект появился ---
        e_start = encoder(device)
        _push_encoder(sp, e_start)
        assert scene.produce()[0]["frame"] is not None
        objects = scene._spawner.active_objects()
        assert len(objects) == 1, f"сцена должна заспавнить один объект, есть {len(objects)}"
        passport = objects[0].passport

        # --- задание: pick из данных сцены, ecap = энкодер объекта ---
        ecap = int(passport.spawn_encoder)
        pick_x, pick_y = object_robot_xy(
            passport.spawn_encoder,
            ecap,
            BeltGeometry.from_dict(_GEOMETRY_CFG),
            lateral_px=passport.lateral_px,
            px_per_mm=1.0,
        )
        run_with_deadline(lambda: client.servo(True), timeout=5.0, label="servo")
        run_with_deadline(client.kick_heartbeat, timeout=5.0, label="hb")
        job = run_with_deadline(
            lambda: client.cvt_job(
                ecap,
                pick_x,
                pick_y,
                0.0,  # pick_z: при flags=0 игнорируется
                0,  # flags
                _PLACE_X_MM,
                _PLACE_Y_MM,
                0.0,  # place_z: при flags=0 игнорируется
                _PLACE_RZ_DEG,
            ),
            timeout=5.0,
            label="cvt_job",
        )
        assert job.seq != _JOB_INDEX, (
            f"seq CVT_JOB {job.seq} совпал со счётчиком заданий {_JOB_INDEX}: тест не различает трактовки"
        )
        wait_done_hb(client, job.seq)

        # --- DONE -> scene.job_done ---
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and not sent:
            time.sleep(0.02)
        assert len(sent) == 1, f"ожидалось одно scene.job_done, отправлено {sent!r}"
        target, command, args = sent[0]
        assert (target, command) == ("camera", "scene.job_done")
        assert args["index"] == _JOB_INDEX, f"index события {args['index']!r} != счётчик заданий {_JOB_INDEX}"

        scene.produce()  # разбор очереди заданий — в начале produce()
        status = scene.cmd_status()
        assert [(r["index"], r["outcome"]) for r in status["recent"]] == [(_JOB_INDEX, "matched")], status["recent"]
        assert status["active"] == 0, "сопоставленный объект должен сняться со сцены"
    finally:
        if device is not None:
            close_client(device)
        try:
            run_with_deadline(lambda: plugin.shutdown(ctx), timeout=10.0, label="shutdown")
        finally:
            workers.stop_all()
