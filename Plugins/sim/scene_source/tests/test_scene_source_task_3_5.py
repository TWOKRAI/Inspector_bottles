# -*- coding: utf-8 -*-
"""RED-приёмка Task 3.5 (часть B, плагины) — «робот забрал — объект исчезает»,
сторона ``Plugins/sim/scene_source``.

Независимый tester, worktree на коммите контракта лида (``ea2761e7``, до реализации).
Контракт — ТОЛЬКО секция «Контракт лида 3.5 (2026-09-23, до тестера)» в
``plans/line-sim/phase-3-object-engine.md``, §§2/4 (форма события ``JobDone``, команды
``scene.job_done``/``scene.status``, порядок разбора очереди в ``produce()``). Реализация
(``Services/line_sim/core/matching.py``, команды в ``plugin.py``) сегодня НЕ существует —
``plugin.commands`` пуст (``{}``), ожидаемый провал диспетча — ``KeyError``.

Координаты задания в системе робота считаются в тесте ЛИТЕРАЛЬНО (``FACTOR_MM=0.144473``,
единичный вектор хода ленты ``(0.0, 1.0)`` — из контракта, не из ``Services.line_sim.core.belt``
и не из нового ``matching.py``), от РЕАЛЬНОГО ``spawn_encoder`` только что заспавненного
объекта (читается из ``plugin._spawner.active_objects()`` после ``produce()``).

Харнесс — своя копия ``_FakeStateProxy``/``_make_plugin``/``_make_plugin_with_engine`` (тот же
паттерн, что ``tests/test_scene_source_hazards.py``/``tests/test_scene_source_task_3_3a.py`` —
файл самодостаточен, не импортирует их). Спавн — режим ``spawn_spacing_mm`` с огромным шагом
(детерминированный: ровно один объект на первом ``tick()``, второй не спавнится НИКОГДА в
пределах теста) — не ``spawn_interval_s`` (реальный wall-clock, не нужен для детерминизма).

Известная догадка тестера: поле ``"active"`` в ``scene.status`` при недоступном движке
(``_spawner is None``) не названо контрактом явно — тест B7 предполагает ``0`` (нет движка -
нет активных объектов), решить/подтвердить на ревью реализации.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Callable
from unittest.mock import MagicMock

import numpy as np
import pytest

from multiprocess_framework.modules.state_store_module.core.delta import Delta
from Services.dataset_gen.core.catalog import imwrite_unicode
from Plugins.sim.scene_source.plugin import SceneSourcePlugin

pytestmark = pytest.mark.timeout(30)

#: Литералы контракта (§4/§2 «Контракт лида 3.5») — НЕ импорт нового matching.py.
_FACTOR_MM = 0.144473
_BELT_UX, _BELT_UY = 0.0, 1.0
_DEFAULT_MATCH_RADIUS_MM = 5.0
_DEFAULT_DUP_WINDOW_S = 10.0


class _FakeStateProxy:
    """Минимальная замена ``StateProxy`` — своя копия (см. докстринг файла)."""

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
    """Движок с ОГРОМНЫМ шагом спавна по дистанции — ровно один объект на первом
    ``tick()``, второй не спавнится (детерминизм без сна/wall-clock)."""
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
    """Вызвать команду через публичный контракт ``commands`` (см. §4 контракта лида)."""
    method_name = plugin.commands[name]
    method = getattr(plugin, method_name)
    return method(data)


def _job_for_object(index: int, spawn_encoder: float, ecap: float, t: float = 0.0) -> dict:
    """Литеральная геометрия задания при дефолтной ``geometry`` (0,0): ``offset_mm =
    (ecap - spawn_encoder) * FACTOR_MM``; ``x = 0.0*offset``, ``y = 1.0*offset``."""
    offset_mm = (ecap - spawn_encoder) * _FACTOR_MM
    return {
        "index": index,
        "x_mm": _BELT_UX * offset_mm,
        "y_mm": _BELT_UY * offset_mm,
        "ecap": ecap,
        "t": t,
    }


def _spawn_one_and_match(tmp_path: Path):
    """Общий сетап B2/B3: заспавнить один объект, свести с ним ОДНО задание
    (``index=1``) до ``matched``, вернуть плагин/state_proxy/id объекта."""
    plugin, ctx, sp = _make_plugin_with_engine(tmp_path)
    _push_encoder(sp, 1000)
    plugin.produce()
    active = plugin._spawner.active_objects()
    assert len(active) == 1, "фикстура должна заспавнить ровно один объект"
    oid = active[0].passport.object_id
    spawn_encoder = active[0].passport.spawn_encoder

    job1 = _job_for_object(index=1, spawn_encoder=spawn_encoder, ecap=2000)
    assert _call(plugin, "scene.job_done", job1) == {"status": "ok"}
    plugin.produce()  # разбор очереди -> match_job -> matched -> spawner.remove()
    return plugin, sp, oid


# --------------------------------------------------------------------------- #
# B1 — scene.job_done: только ставит в очередь, кривые аргументы не роняют    #
# --------------------------------------------------------------------------- #


def test_job_done_enqueues_ok_and_bad_args_error():
    plugin, _ctx, sp = _make_plugin()  # без preset_path -- для этой проверки движок не важен

    valid = {"index": 1, "x_mm": 0.0, "y_mm": 0.0, "ecap": 100, "t": 0.0}
    result_ok = _call(plugin, "scene.job_done", valid)
    assert result_ok == {"status": "ok"}
    assert sp.set_calls == [], "команда только ставит в очередь -- sim.objects не мутируется сразу"

    bad = {"index": "не число"}  # нет x_mm/y_mm/ecap/t
    result_bad = _call(plugin, "scene.job_done", bad)
    assert result_bad["status"] == "error"
    assert isinstance(result_bad.get("message"), str) and result_bad["message"], (
        "кривые аргументы должны вернуть message, не бросить исключение"
    )


# --------------------------------------------------------------------------- #
# B2 — matched: объект пропадает из sim.objects на СЛЕДУЮЩЕМ produce()        #
# --------------------------------------------------------------------------- #


def test_matched_object_gone_from_sim_objects_after_next_produce(tmp_path):
    plugin, sp, oid = _spawn_one_and_match(tmp_path)

    assert plugin._spawner.active_objects() == [], "сведённый объект должен быть снят спавнером"
    assert sp.set_calls[-1] == ("sim.objects", {}), (
        "sim.objects должен переопубликоваться пустым -- множество активных id изменилось"
    )

    status = _call(plugin, "scene.status")
    assert status["status"] == "ok"
    assert status["active"] == 0
    assert len(status["recent"]) == 1
    entry = status["recent"][0]
    assert entry["index"] == 1
    assert entry["outcome"] == "matched"
    assert entry["object_id"] == oid
    assert entry["residual_mm"] is not None and entry["residual_mm"] < _DEFAULT_MATCH_RADIUS_MM


# --------------------------------------------------------------------------- #
# B3 — второе идентичное задание после matched -> dup, состав объектов не    #
#      меняется дальше                                                       #
# --------------------------------------------------------------------------- #


def test_second_identical_job_is_dup_objects_unchanged(tmp_path):
    plugin, sp, oid = _spawn_one_and_match(tmp_path)
    calls_after_match = list(sp.set_calls)

    job2 = _job_for_object(index=2, spawn_encoder=1000.0, ecap=2000)
    assert _call(plugin, "scene.job_done", job2) == {"status": "ok"}
    plugin.produce()

    assert sp.set_calls == calls_after_match, "dup не должен снова публиковать sim.objects"
    status = _call(plugin, "scene.status")
    assert status["active"] == 0
    entry = status["recent"][-1]
    assert entry["index"] == 2
    assert entry["outcome"] == "dup"
    assert entry["object_id"] == oid


# --------------------------------------------------------------------------- #
# B4 — задание на пустой ленте (кандидатов вообще нет) -> no_object,          #
#      ничего не снимается                                                    #
# --------------------------------------------------------------------------- #


def test_job_on_empty_belt_is_no_object_nothing_removed(tmp_path):
    plugin, _ctx, sp = _make_plugin_with_engine(tmp_path)
    # Мир НЕ трогаем -- spawner.tick() ни разу не вызывался, active/removed пусты.
    assert plugin._spawner.active_objects() == []

    job = _job_for_object(index=1, spawn_encoder=0.0, ecap=500)
    assert _call(plugin, "scene.job_done", job) == {"status": "ok"}
    plugin.produce()

    assert sp.set_calls == [], "нет кандидатов -- sim.objects не публикуется вовсе"
    status = _call(plugin, "scene.status")
    assert status["active"] == 0
    entry = status["recent"][-1]
    assert entry["outcome"] == "no_object"
    assert entry["object_id"] is None
    assert entry["residual_mm"] is None


# --------------------------------------------------------------------------- #
# B5 — recent: не больше 32, старые первыми, обязательные поля               #
# --------------------------------------------------------------------------- #


def test_status_recent_bounded_oldest_first_with_fields():
    plugin, _ctx, _sp = _make_plugin()  # движок не нужен -- все 40 заданий дадут no_object

    for i in range(1, 41):
        job = {"index": i, "x_mm": 0.0, "y_mm": 0.0, "ecap": i, "t": 0.0}
        assert _call(plugin, "scene.job_done", job) == {"status": "ok"}

    plugin.produce()  # один кадр -- вся очередь разбирается целиком

    status = _call(plugin, "scene.status")
    recent = status["recent"]
    assert len(recent) == 32, "не больше 32 -- контракт §4"
    assert [entry["index"] for entry in recent] == list(range(9, 41)), "старые первыми, последние 32 из 40"
    for entry in recent:
        assert set(entry.keys()) == {"index", "outcome", "object_id", "residual_mm"}
        assert entry["outcome"] == "no_object"


# --------------------------------------------------------------------------- #
# B6 — снятый объект старше dup_window_s не считается кандидатом -> no_object #
# --------------------------------------------------------------------------- #


def test_removed_older_than_dup_window_gives_no_object(tmp_path, monkeypatch):
    fake_now = [1_000.0]
    monkeypatch.setattr("time.monotonic", lambda: fake_now[0])

    plugin, _ctx, sp = _make_plugin_with_engine(tmp_path)
    _push_encoder(sp, 1000, t=fake_now[0])
    plugin.produce()
    active = plugin._spawner.active_objects()
    assert len(active) == 1
    spawn_encoder = active[0].passport.spawn_encoder

    job1 = _job_for_object(index=1, spawn_encoder=spawn_encoder, ecap=2000, t=fake_now[0])
    assert _call(plugin, "scene.job_done", job1) == {"status": "ok"}
    plugin.produce()
    assert _call(plugin, "scene.status")["recent"][-1]["outcome"] == "matched", "сетап должен дать matched"

    fake_now[0] += _DEFAULT_DUP_WINDOW_S + 1.0  # dup_window_s истёк

    job2 = _job_for_object(index=2, spawn_encoder=spawn_encoder, ecap=2000, t=fake_now[0])
    assert _call(plugin, "scene.job_done", job2) == {"status": "ok"}
    plugin.produce()

    entry = _call(plugin, "scene.status")["recent"][-1]
    assert entry["index"] == 2
    assert entry["outcome"] == "no_object", "снятый объект старше dup_window_s -- не кандидат вовсе"
    assert entry["object_id"] is None


# --------------------------------------------------------------------------- #
# B7 — движок не собран (нет preset_path) -> no_object, без исключения       #
# --------------------------------------------------------------------------- #


def test_engine_not_built_gives_no_object():
    plugin, _ctx, sp = _make_plugin()  # без preset_path -> _spawner is None

    job = {"index": 1, "x_mm": 0.0, "y_mm": 0.0, "ecap": 100, "t": 0.0}
    assert _call(plugin, "scene.job_done", job) == {"status": "ok"}
    plugin.produce()  # не должен упасть -- движок недоступен, разбор очереди всё равно идёт

    assert sp.set_calls == []
    entry = _call(plugin, "scene.status")["recent"][-1]
    assert entry["outcome"] == "no_object"
    assert entry["object_id"] is None
