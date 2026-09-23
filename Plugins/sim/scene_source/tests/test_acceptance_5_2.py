# -*- coding: utf-8 -*-
"""Task 5.2 — независимый RED (тестер, worktree на коммите контракта 99022975, ДО реализации).

Контракт — ТОЛЬКО ``plans/line-sim/phase-5-contract-5.2.md`` §2 (``TruthLedger`` в
``SceneSourcePlugin``), не код: команды ``truth.status``/``truth.reset`` сегодня НЕ
существуют (``plugin.commands`` их не содержит) -- ожидаемый провал диспетча ``KeyError``
на ``plugin.commands["truth.status"]``; уровни ``truth_*`` через ``ctx.publish_metric``
сегодня не публикуются вовсе -- ожидаемый провал ``AssertionError`` (пустой список вызовов).

Харнесс -- своя копия ``_FakeStateProxy``/``_make_plugin``/``_make_plugin_with_engine`` (тот
же паттерн, что ``Plugins/sim/scene_source/tests/test_scene_source_task_3_5.py`` -- файл
самодостаточен, не импортирует его). ``ctx`` -- ``MagicMock()``: ``declare_metric``/
``publish_metric`` авто-мокаются, вызовы читаются через ``call_args_list``.

Догадка тестера (не факт, помечено по месту): имя конфиг-ключа периода прореживания --
``truth_publish_s`` буквально из §2 контракта («конфиг, дефолт 1.0 с»), не из кода -- кода
нет. Названия пяти уровней (``truth_caught``/``truth_dup_jobs``/``truth_missed``/
``truth_false_alarm``/``truth_on_belt``) -- тоже дословно §2.
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

_TRUTH_LEVELS = {"truth_caught", "truth_dup_jobs", "truth_missed", "truth_false_alarm", "truth_on_belt"}


class _FakeStateProxy:
    """Минимальная замена ``StateProxy`` -- своя копия (см. докстринг файла)."""

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
    """Движок с ОГРОМНЫМ шагом спавна по дистанции -- ровно один объект на первом
    ``tick()``, второй не спавнится в пределах теста (тот же приём, что
    ``test_scene_source_task_3_5.py``)."""
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
    """Вызвать команду через публичный контракт ``commands`` -- §2 контракта лида."""
    method_name = plugin.commands[name]
    method = getattr(plugin, method_name)
    return method(data)


def _job_for_object(index: int, spawn_encoder: float, ecap: float, t: float = 0.0) -> dict:
    """Литеральная геометрия задания при дефолтной ``geometry`` (0,0): ``offset_mm =
    (ecap - spawn_encoder) * FACTOR_MM``; belt-вектор дефолтный (0.0, 1.0) -- та же формула,
    что ``test_scene_source_task_3_5.py``."""
    offset_mm = (ecap - spawn_encoder) * FACTOR_MM
    return {"index": index, "x_mm": 0.0, "y_mm": offset_mm, "ecap": ecap, "t": t}


# --------------------------------------------------------------------------- #
# Команды truth.status/truth.reset -- форма ответа                            #
# --------------------------------------------------------------------------- #


def test_truth_commands_shape():
    """``truth.status`` -> ``{"status": "ok", "counters": {...counters()}}``;
    ``truth.reset`` -> ``ledger.reset()``, ``{"status": "ok"}`` -- §2 контракта.

    Полный набор ключей ``counters()`` уже закреплён независимым тестом §1
    (``Services/line_sim/tests/test_acceptance_5_2.py``) -- здесь только форма ответа
    команды и факт, что ``truth.reset`` не бросает."""
    plugin, _ctx, _sp = _make_plugin()  # движок не нужен -- форма команды не зависит от него

    status = _call(plugin, "truth.status")
    assert status["status"] == "ok"
    assert isinstance(status["counters"], dict)
    assert "caught" in status["counters"]

    reset_result = _call(plugin, "truth.reset")
    assert reset_result == {"status": "ok"}


# --------------------------------------------------------------------------- #
# scene.job_done -> ledger: caught / dup / false_alarm через produce()        #
# --------------------------------------------------------------------------- #


def test_caught_dup_false_alarm_via_job_done(tmp_path):
    """Задание на активный объект -> caught; повторное задание на тот же (уже снятый)
    объект -> dup_jobs; задание на пустое место -> false_alarm -- §2 контракта: каждый
    исход ``_drain_jobs`` идёт в ``ledger.on_match(result)``."""
    plugin, _ctx, sp = _make_plugin_with_engine(tmp_path)
    _push_encoder(sp, 1000)
    plugin.produce()
    active = plugin._spawner.active_objects()  # ponytail: тот же приём чтения фикстуры движка,
    # что test_scene_source_task_3_5.py -- иного публичного способа узнать spawn_encoder нет
    assert len(active) == 1, "фикстура должна заспавнить ровно один объект"
    spawn_encoder = active[0].passport.spawn_encoder

    job1 = _job_for_object(index=1, spawn_encoder=spawn_encoder, ecap=2000)
    assert _call(plugin, "scene.job_done", job1) == {"status": "ok"}
    plugin.produce()  # _drain_jobs -> match_job -> matched -> ledger.on_match -> caught

    counters_after_match = _call(plugin, "truth.status")["counters"]
    assert counters_after_match["caught"] == 1
    assert counters_after_match["dup_jobs"] == 0
    assert counters_after_match["false_alarm"] == 0

    job2 = _job_for_object(index=2, spawn_encoder=spawn_encoder, ecap=2000)
    assert _call(plugin, "scene.job_done", job2) == {"status": "ok"}
    plugin.produce()  # тот же объект, уже снят -> outcome=dup -> ledger.on_match -> dup_jobs

    counters_after_dup = _call(plugin, "truth.status")["counters"]
    assert counters_after_dup["caught"] == 1, "повторное задание не должно снова засчитаться как caught"
    assert counters_after_dup["dup_jobs"] == 1

    job3 = {"index": 3, "x_mm": 999_999.0, "y_mm": 999_999.0, "ecap": 2000, "t": 0.0}  # заведомо мимо
    assert _call(plugin, "scene.job_done", job3) == {"status": "ok"}
    plugin.produce()  # нет кандидатов в радиусе -> no_object -> ledger.on_match -> false_alarm

    counters_after_false_alarm = _call(plugin, "truth.status")["counters"]
    assert counters_after_false_alarm["false_alarm"] == 1
    assert counters_after_false_alarm["caught"] == 1, "false_alarm не должен трогать caught"


# --------------------------------------------------------------------------- #
# Объект уезжает со сцены без задания -> missed                               #
# --------------------------------------------------------------------------- #


def test_leave_scene_is_missed(tmp_path):
    """Объект заспавнен, ни одного задания на него не было, затем он уезжает за
    ``scene_length_mm`` -- §2 контракта: исчезнувшие id между снимком после
    ``_drain_jobs`` и после ``spawner.tick()`` -> ``on_despawn(id)`` -> ``missed``."""
    plugin, _ctx, sp = _make_plugin_with_engine(tmp_path, {"scene_length_mm": 10.0})
    _push_encoder(sp, 0)
    plugin.produce()  # спавн: spawn_encoder=0
    active = plugin._spawner.active_objects()
    assert len(active) == 1, "фикстура должна заспавнить ровно один объект"

    before = _call(plugin, "truth.status")["counters"]
    assert before["missed"] == 0
    assert before["on_belt"] == 1

    # offset_mm = encoder * FACTOR_MM (0.144473) -- 1000 даёт ~144мм >> scene_length_mm=10
    _push_encoder(sp, 1000)
    plugin.produce()  # tick() despawn'ит объект -- ledger.on_despawn(id) -> missed

    assert plugin._spawner.active_objects() == [], "объект должен быть снят спавнером (уехал со сцены)"
    after = _call(plugin, "truth.status")["counters"]
    assert after["missed"] == 1
    assert after["caught"] == 0
    assert after["on_belt"] == 0


# --------------------------------------------------------------------------- #
# Задание + уход со сцены в одном produce() -> caught, НЕ missed              #
# --------------------------------------------------------------------------- #


def test_job_and_leave_same_frame_is_caught(tmp_path):
    """Порядок «сначала задания, потом тик» (§2 контракта): задание на объект, который
    в этом же кадре уедет за ``scene_length_mm``, засчитывается как ``caught`` -- матчинг
    видит объект ещё активным, ``spawner.remove()`` снимает его ДО ``tick()``, поэтому
    diff id до/после тика не видит его пропажу как ``missed``."""
    plugin, _ctx, sp = _make_plugin_with_engine(tmp_path, {"scene_length_mm": 10.0})
    _push_encoder(sp, 0)
    plugin.produce()  # спавн: spawn_encoder=0
    active = plugin._spawner.active_objects()
    assert len(active) == 1
    spawn_encoder = active[0].passport.spawn_encoder

    # Задание ставится СЕЙЧАС (мир ещё на encoder=0, объект активен) -- геометрия задания
    # считается от текущего spawn_encoder, ecap тот же, что и матч-момент.
    job = _job_for_object(index=1, spawn_encoder=spawn_encoder, ecap=0)
    assert _call(plugin, "scene.job_done", job) == {"status": "ok"}

    # Мир продвигается ДАЛЕКО за scene_length_mm=10 ДО следующего produce() -- на этом
    # produce() и разбор задания (matched), и tick() (который увидел бы уход со сцены)
    # происходят в ОДНОМ вызове, задания -- первыми.
    _push_encoder(sp, 1000)
    plugin.produce()

    counters = _call(plugin, "truth.status")["counters"]
    assert counters["caught"] == 1, "задание, сведённое до тика, должно засчитаться как caught"
    assert counters["missed"] == 0, "тот же объект не должен ЕЩЁ и засчитаться как missed"
    assert counters["on_belt"] == 0


# --------------------------------------------------------------------------- #
# Уровни truth_* публикуются через ctx.publish_metric, прорежены по времени   #
# --------------------------------------------------------------------------- #


def test_levels_published_throttled(monkeypatch):
    """Пять уровней (``truth_caught``/``truth_dup_jobs``/``truth_missed``/
    ``truth_false_alarm``/``truth_on_belt``) публикуются из ``produce()`` не чаще раза в
    ``truth_publish_s`` (дефолт 1.0с) -- §2 контракта. Время управляется через
    ``time.monotonic`` -- тот же приём, что ``test_scene_source_task_3_5.py`` (B6)."""
    fake_now = [1000.0]
    monkeypatch.setattr("time.monotonic", lambda: fake_now[0])

    plugin, ctx, _sp = _make_plugin()  # движок не нужен -- уровни публикуются независимо от него
    ctx.publish_metric.reset_mock()

    plugin.produce()
    first_names = {call.args[0] for call in ctx.publish_metric.call_args_list}
    assert _TRUTH_LEVELS <= first_names, f"не все уровни опубликованы на первом produce(): {first_names}"

    ctx.publish_metric.reset_mock()
    fake_now[0] += 0.1  # меньше truth_publish_s -- публикации быть не должно
    plugin.produce()
    assert ctx.publish_metric.call_args_list == [], "публикация раньше truth_publish_s -- нарушение прореживания"

    fake_now[0] += 1.1  # порог пройден -- публикация должна повториться
    plugin.produce()
    second_names = {call.args[0] for call in ctx.publish_metric.call_args_list}
    assert _TRUTH_LEVELS <= second_names, "после истечения truth_publish_s публикация не повторилась"


# --------------------------------------------------------------------------- #
# Счётчики правды не пишутся в дерево мира (sim.*)                            #
# --------------------------------------------------------------------------- #


def test_no_truth_in_world(tmp_path):
    """``state_proxy.set()`` не должен получать ничего с ``truth`` в пути ни на одном
    исходе (спавн/матч/деспавн) -- §2 контракта: «в дерево мира счётчики не пишутся»."""
    plugin, _ctx, sp = _make_plugin_with_engine(tmp_path, {"scene_length_mm": 10.0})
    _push_encoder(sp, 0)
    plugin.produce()
    active = plugin._spawner.active_objects()
    assert len(active) == 1
    spawn_encoder = active[0].passport.spawn_encoder

    job = _job_for_object(index=1, spawn_encoder=spawn_encoder, ecap=0)
    assert _call(plugin, "scene.job_done", job) == {"status": "ok"}
    _push_encoder(sp, 1000)
    plugin.produce()
    _call(plugin, "truth.status")
    _call(plugin, "truth.reset")

    assert all("truth" not in str(path) for path, _value in sp.set_calls), (
        f"truth-путь просочился в state_proxy.set(): {sp.set_calls!r}"
    )
