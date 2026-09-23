# -*- coding: utf-8 -*-
"""Тесты автора (hazard) — Task 5.2, `TruthLedger` в `SceneSourcePlugin`.

Независимый тестер (`test_acceptance_5_2.py`) закрепил форму команд, путь `_drain_jobs` ->
`ledger.on_match`, `missed` при уходе со сцены, «задание + уход в одном кадре» -> `caught`,
прореживание публикации по ИМЕНАМ и запрет `truth`-путей в `state_proxy.set()`. Здесь — то,
что видно только автору механизма (контракт §"Кто что пишет" -> Автор):

1. `truth.reset` из командного потока ОДНОВРЕМЕННО с `produce()` (два разных лока:
   `self._lock` мира и `self._truth_lock` — гонка между ними, не проверенная тестером).
2. Потолок `max_active` спавнера: объект, никогда не созданный из-за потолка, не должен
   быть ни `caught`, ни `missed` (diff spawn/despawn просто не видит несуществующий id).
3. Значения опубликованных уровней РАВНЫ `truth.status["counters"]` (тестер проверил только
   ИМЕНА уровней в `test_levels_published_throttled`, не числа).

Харнесс — своя копия (тот же приём, что `test_acceptance_5_2.py` и
`test_scene_source_task_3_5.py`; файл самодостаточен, не импортирует чужие тесты).
"""

from __future__ import annotations

import threading
import uuid
from pathlib import Path
from typing import Callable
from unittest.mock import MagicMock

import numpy as np
import pytest

from multiprocess_framework.modules.state_store_module.core.delta import Delta
from Services.dataset_gen.core.catalog import imwrite_unicode
from Services.robot_comm.core.registers import FACTOR_MM
from Plugins.sim.scene_source.plugin import SceneSourcePlugin

pytestmark = pytest.mark.timeout(60)


class _FakeStateProxy:
    def __init__(self) -> None:
        self._callbacks: list[Callable[[list[Delta]], None]] = []
        self.set_calls: list[tuple[str, object]] = []

    def subscribe(self, pattern, callback, exclude_self=True, sync=True):
        self._callbacks.append(callback)
        return str(uuid.uuid4())

    def emit(self, deltas: list[Delta]) -> None:
        for cb in self._callbacks:
            cb(deltas)

    def set(self, path: str, value: object) -> None:
        self.set_calls.append((path, value))


def _make_plugin(cfg_overrides: dict | None = None):
    state_proxy = _FakeStateProxy()
    ctx = MagicMock()
    ctx.state_proxy = state_proxy
    ctx.config = {
        "resolution_width": 640,
        "resolution_height": 480,
        "spawn_encoder": 0,
        "px_per_mm": 1.0,
        "stale_ms": 200,
        **(cfg_overrides or {}),
    }
    plugin = SceneSourcePlugin()
    plugin.configure(ctx)
    plugin.start(ctx)
    return plugin, ctx, state_proxy


def _make_fixture_catalog(tmp_path: Path) -> Path:
    classes_dir = tmp_path / f"classes_{uuid.uuid4().hex}"
    class_dir = classes_dir / "square"
    class_dir.mkdir(parents=True)
    sprite_bgra = np.zeros((16, 16, 4), dtype=np.uint8)
    sprite_bgra[:, :, :3] = 128
    sprite_bgra[:, :, 3] = 255
    imwrite_unicode(class_dir / "sprite.png", sprite_bgra)
    return classes_dir


def _make_plugin_with_engine(tmp_path: Path, cfg_overrides: dict | None = None):
    catalog_dir = _make_fixture_catalog(tmp_path)
    return _make_plugin(
        {
            "preset_path": str(catalog_dir),
            "spawn_spacing_mm": [1e9, 1e9],
            "scene_length_mm": 1e9,
            **(cfg_overrides or {}),
        }
    )


def _push_encoder(sp: _FakeStateProxy, value: float, t: float = 0.0) -> None:
    sp.emit(
        [
            Delta(
                path="sim.belt.encoder",
                old_value=object(),
                new_value={"value": value, "mm_s": 0.0, "t": t},
                source="robot",
            )
        ]
    )


def _call(plugin: SceneSourcePlugin, name: str, data: dict | None = None) -> dict:
    method_name = plugin.commands[name]
    method = getattr(plugin, method_name)
    return method(data)


def _job_for_object(index: int, spawn_encoder: float, ecap: float, t: float = 0.0) -> dict:
    offset_mm = (ecap - spawn_encoder) * FACTOR_MM
    return {"index": index, "x_mm": 0.0, "y_mm": offset_mm, "ecap": ecap, "t": t}


# --------------------------------------------------------------------------- #
# (1) truth.reset из командного потока ОДНОВРЕМЕННО с produce()               #
# --------------------------------------------------------------------------- #


def test_reset_concurrent_with_produce_stays_consistent(tmp_path):
    """`truth.reset` (командный поток) во время непрерывного `produce()` (поток-продюсер) --
    оба лока (`_truth_lock`, отдельный от `_lock` мира) должны держать счётчики
    консистентными и НЕ бросать. Поток не может повиснуть -- daemon-потоки + join с
    дедлайном (STRICT-канон: hang хуже отсутствующего теста)."""
    plugin, _ctx, sp = _make_plugin_with_engine(tmp_path, {"spawn_spacing_mm": [1.0, 5.0], "scene_length_mm": 50.0})
    errors: list[BaseException] = []
    stop = threading.Event()

    def produce_loop() -> None:
        try:
            encoder = 0.0
            for i in range(300):
                encoder += 20.0
                _push_encoder(sp, encoder)
                plugin.produce()
                active = plugin._spawner.active_objects()
                if active:
                    obj = active[0]
                    job = _job_for_object(index=i, spawn_encoder=obj.passport.spawn_encoder, ecap=encoder)
                    _call(plugin, "scene.job_done", job)
        except BaseException as exc:  # noqa: BLE001 -- пробросить в главный поток для assert
            errors.append(exc)
        finally:
            stop.set()

    def reset_loop() -> None:
        try:
            while not stop.is_set():
                _call(plugin, "truth.reset")
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    t_produce = threading.Thread(target=produce_loop, daemon=True)
    t_reset = threading.Thread(target=reset_loop, daemon=True)
    t_produce.start()
    t_reset.start()
    t_produce.join(timeout=30.0)
    t_reset.join(timeout=30.0)

    assert not t_produce.is_alive(), "produce_loop не завершился за 30с -- подозрение на deadlock"
    assert not t_reset.is_alive(), "reset_loop не завершился за 30с -- подозрение на deadlock"
    assert not errors, f"исключения в потоках: {errors!r}"

    counters = _call(plugin, "truth.status")["counters"]
    assert counters["caught"] == counters["caught_ok"] + counters["caught_defect"]
    assert counters["missed"] == counters["missed_ok"] + counters["missed_defect"]


# --------------------------------------------------------------------------- #
# (2) max_active -- никогда не созданный объект не caught и не missed         #
# --------------------------------------------------------------------------- #


def test_max_active_ceiling_object_never_created_not_caught_not_missed(tmp_path):
    """Потолок `max_active` спавнера мешает второму объекту появиться -- diff
    spawn/despawn `produce()` просто не видит его id (он никогда не входил в
    `active_objects()`), поэтому он не должен попасть ни в `caught`, ни в `missed`,
    ни даже в `on_belt` -- контракт §"Кто что пишет": потолок -- забота автора, тестер
    его не проверял.

    `plugin._spawner._max_active` — приватный атрибут `ObjectSpawner`; плагин не
    прокидывает `max_active` из конфига (см. `configure()`), поэтому единственный
    способ проверить потолок в тесте на уровне плагина — снизить его напрямую после
    сборки движка."""
    plugin, _ctx, sp = _make_plugin_with_engine(tmp_path, {"spawn_spacing_mm": [1.0, 1.0], "scene_length_mm": 1e9})
    plugin._spawner._max_active = 1  # ponytail: приватный атрибут -- hazard-тест, не публичный контракт

    _push_encoder(sp, 0)
    plugin.produce()
    assert len(plugin._spawner.active_objects()) == 1, "setup sanity: первый объект должен заспавниться"

    _push_encoder(sp, 100)  # далеко за порог шага (1мм) -- второй спавн заблокирован потолком=1
    plugin.produce()
    assert len(plugin._spawner.active_objects()) == 1, "потолок max_active=1 должен помешать второму спавну"

    counters = _call(plugin, "truth.status")["counters"]
    assert counters["on_belt"] == 1, "под учётом только реально созданный первый объект"
    assert counters["caught"] == 0
    assert counters["missed"] == 0


# --------------------------------------------------------------------------- #
# (3) значения опубликованных уровней = truth.status counters                 #
# --------------------------------------------------------------------------- #


def test_published_level_values_equal_status_counters(monkeypatch, tmp_path):
    """`test_levels_published_throttled` (тестер) проверяет только ИМЕНА уровней;
    здесь -- что ЧИСЛА в `ctx.publish_metric` совпадают с `truth.status["counters"]`
    после реального `caught` (не все нули)."""
    fake_now = [1000.0]
    monkeypatch.setattr("time.monotonic", lambda: fake_now[0])

    plugin, ctx, sp = _make_plugin_with_engine(tmp_path)
    _push_encoder(sp, 1000)
    plugin.produce()  # первый produce публикует (все нули) -- не интересует этот тест
    active = plugin._spawner.active_objects()
    assert len(active) == 1
    spawn_encoder = active[0].passport.spawn_encoder

    job = _job_for_object(index=1, spawn_encoder=spawn_encoder, ecap=2000)
    assert _call(plugin, "scene.job_done", job) == {"status": "ok"}

    ctx.publish_metric.reset_mock()
    fake_now[0] += 2.0  # за порог truth_publish_s -- публикация обязана повториться
    plugin.produce()  # _drain_jobs -> matched -> caught=1

    published = {call.args[0]: call.args[1] for call in ctx.publish_metric.call_args_list}
    status_counters = _call(plugin, "truth.status")["counters"]

    assert published, "публикация должна была произойти после истечения truth_publish_s"
    assert published["truth_caught"] == status_counters["caught"] == 1
    assert published["truth_dup_jobs"] == status_counters["dup_jobs"] == 0
    assert published["truth_missed"] == status_counters["missed"] == 0
    assert published["truth_false_alarm"] == status_counters["false_alarm"] == 0
    assert published["truth_on_belt"] == status_counters["on_belt"] == 0
