# -*- coding: utf-8 -*-
"""RED-приёмка Task 5.1b — §3 контракта, сторона сцены: SceneSourcePlugin передаёт
``job`` в ``TruthLedger.on_match`` (в т.ч. в ветке «движок не собран»), и
``truth.status``/уровни несут новый ``false_alarm_frozen_xy``/``truth_false_alarm_frozen_xy``.

Независимый tester, worktree на коммите контракта лида (602be8ec, до реализации).
Контракт — ТОЛЬКО ``plans/line-sim/phase-5-contract-5.1b.md`` §3. Сегодня
``_drain_jobs`` зовёт ``self._truth.on_match(result)`` БЕЗ job (см.
``Plugins/sim/scene_source/plugin.py`` — прочитан для геометрии/харнесса), и уровень
``truth_false_alarm_frozen_xy`` НЕ публикуется вовсе (``_TRUTH_LEVELS``/
``_publish_truth_metrics`` перечисляют только пять старых) — ожидаемый провал:
``KeyError`` на ``counters["false_alarm_frozen_xy"]`` (счётчика ещё нет, т.к.
``on_match`` вызывается без job — TruthLedger никогда не видит недавние задания) и
``AssertionError`` (уровень не найден среди опубликованных имён).

Харнесс скопирован с ``Plugins/sim/scene_source/tests/test_acceptance_5_2.py``
(``_FakeStateProxy``/``_make_plugin_with_engine``/``_call``/``_job_for_object`` —
тот же паттерн, файл самодостаточен, не импортирует его). Геометрия задания —
дефолтная (0,0), belt-вектор (0.0, 1.0): ``y_mm = (ecap - spawn_encoder) *
FACTOR_MM`` — та же формула, что харнесс 5.2.
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
from Services.robot_comm.core.registers import FACTOR_MM
from Plugins.sim.scene_source.plugin import SceneSourcePlugin

pytestmark = pytest.mark.timeout(30)

_TRUTH_LEVEL_FROZEN_XY = "truth_false_alarm_frozen_xy"


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
    """Огромный шаг спавна — ровно один объект на первом ``tick()`` (тот же приём,
    что ``test_acceptance_5_2.py``)."""
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
# matched job, затем no_object на той же X/Y с ecap+362 -> frozen false alarm #
# --------------------------------------------------------------------------- #


def test_truth_status_counts_frozen_false_alarm(tmp_path):
    """§3 контракта: задание попадает в объект (matched), затем второе задание — на
    ТУ ЖЕ (x_mm, y_mm), что первое, но ``ecap`` первого + 362 (~52мм проезда по Y —
    объект уже снят, кандидатов рядом с исходной точкой нет) -> ``no_object``, и т.к.
    matched-задание было передано в ``on_match(..., job=...)`` и осталось в памяти
    ledger — второй исход считается ``false_alarm_frozen_xy``."""
    plugin, _ctx, sp = _make_plugin_with_engine(tmp_path)
    _push_encoder(sp, 1000)
    plugin.produce()
    active = plugin._spawner.active_objects()
    assert len(active) == 1, "фикстура должна заспавнить ровно один объект"
    spawn_encoder = active[0].passport.spawn_encoder

    job1 = _job_for_object(index=1, spawn_encoder=spawn_encoder, ecap=2000, t=10.0)
    assert _call(plugin, "scene.job_done", job1) == {"status": "ok"}
    plugin.produce()  # matched -> caught, и (после 5.1b) job1 остаётся в памяти ledger

    matched_counters = _call(plugin, "truth.status")["counters"]
    assert matched_counters["caught"] == 1

    # Та же (x_mm, y_mm), что job1 буквально — НЕ пересчитанная под новый ecap.
    job2 = {"index": 2, "x_mm": job1["x_mm"], "y_mm": job1["y_mm"], "ecap": job1["ecap"] + 362, "t": 10.5}
    assert _call(plugin, "scene.job_done", job2) == {"status": "ok"}
    plugin.produce()  # объект уже снят -> match_job не находит кандидата рядом -> no_object

    counters = _call(plugin, "truth.status")["counters"]
    assert counters["caught"] == 1, "первое задание не должно быть задето вторым"
    assert counters["false_alarm"] == 1, counters
    assert counters["false_alarm_frozen_xy"] == 1, (
        f"§3 контракта 5.1b: job должен доходить до TruthLedger.on_match, счётчики: {counters!r}"
    )


# --------------------------------------------------------------------------- #
# Уровень truth_false_alarm_frozen_xy публикуется вместе с остальными truth_* #
# --------------------------------------------------------------------------- #


def test_level_published(monkeypatch):
    """§3 контракта: новый уровень входит в тот же набор ``ctx.publish_metric``, что
    остальные ``truth_*`` (движок не нужен — уровни публикуются независимо от него,
    тот же приём, что ``test_acceptance_5_2.py::test_levels_published_throttled``)."""
    fake_now = [1000.0]
    monkeypatch.setattr("time.monotonic", lambda: fake_now[0])

    plugin, ctx, _sp = _make_plugin()
    ctx.publish_metric.reset_mock()

    plugin.produce()
    published_names = {call.args[0] for call in ctx.publish_metric.call_args_list}
    assert _TRUTH_LEVEL_FROZEN_XY in published_names, (
        f"§3 контракта 5.1b: {_TRUTH_LEVEL_FROZEN_XY} должен публиковаться наравне с остальными "
        f"truth_*, опубликовано: {published_names!r}"
    )
