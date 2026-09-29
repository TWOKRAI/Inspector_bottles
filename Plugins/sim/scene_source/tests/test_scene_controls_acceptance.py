# -*- coding: utf-8 -*-
"""Task 6.1 — независимый RED (тестер, worktree ``ls-61-tester`` на коммите 8441b531,
ДО реализации). Контракт — ТОЛЬКО бриф ведущего (план ``plans/line-sim/plan.md``, фаза 6,
раздел Task 6.1), сам файл ``plans/line-sim/phase-6-contract-6.1.md`` тестеру видеть нельзя.

Четыре команды ``scene.pause``/``scene.flow``/``scene.defect_rate``/``scene.defect_now``
СЕГОДНЯ не существуют — ``plugin.commands`` их не содержит (grep подтверждён ДО написания
теста, см. отчёт тестера). Ожидаемый провал диспетча — ``KeyError`` на
``plugin.commands["scene.pause"]`` и т.д. (тот же паттерн отказа, что
``test_acceptance_5_2.py`` описывает для ``truth.status``/``truth.reset`` на своей задаче).

Харнесс — своя копия ``_FakeStateProxy``/``_make_plugin``/``_make_plugin_with_engine``/``_call``
(тот же паттерн, что ``test_acceptance_5_2.py`` и ``test_scene_source_task_3_3a.py`` — файл
самодостаточен, ничего оттуда не импортирует).

Догадки тестера, помеченные по месту (контракт не описывает буквально):
  - Точная форма ключа ``flow`` в ответе ``scene.status`` НЕ описана в брифе (только то,
    что он должен быть согласован с реальным режимом движка) — тесты проверяют присутствие
    и мягкую форму (``"interval_s"``/``"spacing_mm"`` как имя активного ключа), не жёсткий
    dict целиком.
  - Текст ошибки (``message``) не проверяется дословно — только факт ``status == "error"``
    и непустое сообщение (бриф не даёт литерального текста).
  - ``code`` в ответе об ошибке не проверяется (бриф просит только ``{"status": "error", ...}``).
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Callable
from unittest.mock import MagicMock

import cv2
import numpy as np
import pytest

from multiprocess_framework.modules.state_store_module.core.delta import Delta
from Services.dataset_gen.core.catalog import imwrite_unicode
from Services.line_sim.core.belt import FACTOR_MM
from Plugins.sim.scene_source.plugin import SceneSourcePlugin

pytestmark = pytest.mark.timeout(30)


# --------------------------------------------------------------------------- #
# Харнесс (самодостаточная копия — см. докстринг файла)                      #
# --------------------------------------------------------------------------- #


class _FakeStateProxy:
    """Минимальная замена ``StateProxy`` — своя копия, не импорт из других файлов."""

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
        "resolution_width": 64,
        "resolution_height": 64,
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
    sprite = np.zeros((16, 16, 4), dtype=np.uint8)
    sprite[:, :, :3] = 128
    sprite[:, :, 3] = 255
    imwrite_unicode(class_dir / "sprite.png", cv2.cvtColor(sprite, cv2.COLOR_RGBA2BGRA))
    return classes_dir


def _make_plugin_with_engine(tmp_path: Path, cfg_overrides: dict | None = None):
    """Реальный движок line_sim; вызывающий обязан передать РОВНО один из
    ``spawn_interval_s``/``spawn_spacing_mm`` и, при желании, ``scene_length_mm`` — своих
    дефолтов для режима спавна здесь нет намеренно (каждый тест решает сам, что ему нужно)."""
    catalog_dir = _make_fixture_catalog(tmp_path)
    return _make_plugin({"preset_path": str(catalog_dir), **(cfg_overrides or {})})


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
    """Вызвать команду через публичный контракт ``commands`` — тот же приём, что
    ``test_acceptance_5_2.py``. ``KeyError`` здесь и есть ожидаемый RED (команды нет)."""
    method_name = plugin.commands[name]
    method = getattr(plugin, method_name)
    return method(data)


# --------------------------------------------------------------------------- #
# scene.pause — останов/возобновление СПАВНА, деспавн не трогается           #
# --------------------------------------------------------------------------- #


def test_pause_stops_new_spawn(tmp_path):
    """Критерий 1: пауза -> сколь угодно большое движение энкодера не спавнит новых
    объектов. Число активных объектов проверяется, не факт вызова сеттера."""
    plugin, _ctx, sp = _make_plugin_with_engine(tmp_path, {"spawn_spacing_mm": [10.0, 10.0], "scene_length_mm": 1e9})
    _push_encoder(sp, 0)
    plugin.produce()  # spacing: первый объект — сразу, без ожидания
    assert len(plugin._spawner.active_objects()) == 1

    assert _call(plugin, "scene.pause", {"paused": True}) == {"status": "ok"}

    for step in range(1, 6):
        _push_encoder(sp, step * 1_000_000)  # огромный шаг энкодера -- обычно много спавнов
        plugin.produce()
        assert len(plugin._spawner.active_objects()) == 1, (
            f"пауза не должна давать новый спавн (шаг {step}, encoder={step * 1_000_000})"
        )


def test_unpause_resumes_spawn(tmp_path):
    """Критерий 1: снятие паузы -> спавн возобновляется."""
    plugin, _ctx, sp = _make_plugin_with_engine(tmp_path, {"spawn_spacing_mm": [10.0, 10.0], "scene_length_mm": 1e9})
    _push_encoder(sp, 0)
    plugin.produce()
    assert len(plugin._spawner.active_objects()) == 1

    assert _call(plugin, "scene.pause", {"paused": True}) == {"status": "ok"}
    _push_encoder(sp, 1_000_000)  # путь давно перекрыл spacing_mm=10, но пауза держит
    plugin.produce()
    assert len(plugin._spawner.active_objects()) == 1

    assert _call(plugin, "scene.pause", {"paused": False}) == {"status": "ok"}
    plugin.produce()  # порог уже пройден -- спавн не должен ждать доп. движения
    assert len(plugin._spawner.active_objects()) == 2


def test_pause_does_not_stop_despawn(tmp_path):
    """Критерий 2: пауза не трогает деспавн -- объект, уехавший за scene_length_mm,
    снимается и при paused=True (на том же produce(), где пауза применилась)."""
    plugin, _ctx, sp = _make_plugin_with_engine(tmp_path, {"spawn_spacing_mm": [1e9, 1e9], "scene_length_mm": 5.0})
    _push_encoder(sp, 0)
    plugin.produce()  # спавн: spawn_encoder=0 (второй объект не наступит -- шаг 1e9мм)
    assert len(plugin._spawner.active_objects()) == 1

    assert _call(plugin, "scene.pause", {"paused": True}) == {"status": "ok"}
    _push_encoder(sp, 1000)  # offset ~= 1000*0.144473 = 144.5мм >> scene_length_mm=5
    plugin.produce()  # деспавн идёт на КАЖДОМ tick(), независимо от paused
    assert plugin._spawner.active_objects() == [], "деспавн должен сработать даже при paused=True"


# --------------------------------------------------------------------------- #
# scene.defect_now — ровно ОДИН следующий спавн, два нажатия не схлопываются #
# --------------------------------------------------------------------------- #


def test_defect_now_marks_exactly_one_next_object(tmp_path):
    """Критерий 3: defect_now делает дефектным РОВНО следующий спавн; уже активный
    объект (спавненный ДО нажатия) не меняется."""
    plugin, _ctx, sp = _make_plugin_with_engine(tmp_path, {"spawn_spacing_mm": [50.0, 50.0], "scene_length_mm": 1e9})
    _push_encoder(sp, 0)
    plugin.produce()  # obj1 -- НЕ дефектный (никто ещё не жал defect_now)
    active = plugin._spawner.active_objects()
    assert len(active) == 1
    assert active[0].passport.defect is None

    assert _call(plugin, "scene.defect_now", {}) == {"status": "ok"}

    delta_ticks = 50.0 / FACTOR_MM + 1.0  # +1 тик запаса -- допуск, как в спавнере
    _push_encoder(sp, delta_ticks)
    plugin.produce()  # obj2 -- должен родиться дефектным
    active = plugin._spawner.active_objects()
    assert len(active) == 2
    ids_by_spawn = {obj.passport.spawn_encoder: obj for obj in active}
    obj1 = ids_by_spawn[0.0]
    obj2 = ids_by_spawn[delta_ticks]
    assert obj1.passport.defect is None, "уже заспавненный объект не должен задним числом стать дефектным"
    assert obj2.passport.defect == "damaged"


def test_two_defect_now_presses_give_two_defects(tmp_path):
    """Критерий 3: два нажатия подряд -> ДВА дефектных объекта, не один (не схлопываются)."""
    plugin, _ctx, sp = _make_plugin_with_engine(tmp_path, {"spawn_spacing_mm": [50.0, 50.0], "scene_length_mm": 1e9})
    _push_encoder(sp, 0)
    plugin.produce()  # obj1 -- baseline, не дефектный
    assert plugin._spawner.active_objects()[0].passport.defect is None

    assert _call(plugin, "scene.defect_now", {}) == {"status": "ok"}
    assert _call(plugin, "scene.defect_now", {}) == {"status": "ok"}

    step_ticks = 50.0 / FACTOR_MM + 1.0
    _push_encoder(sp, step_ticks)
    plugin.produce()  # obj2
    _push_encoder(sp, step_ticks * 2)
    plugin.produce()  # obj3

    active = plugin._spawner.active_objects()
    assert len(active) == 3
    by_encoder = {obj.passport.spawn_encoder: obj for obj in active}
    obj2 = by_encoder[step_ticks]
    obj3 = by_encoder[step_ticks * 2]
    assert obj2.passport.defect == "damaged", "первое нажатие должно достаться obj2"
    assert obj3.passport.defect == "damaged", "второе нажатие НЕ должно схлопнуться с первым -- obj3 тоже дефектный"


def test_defect_now_under_pause_survives_until_unpause(tmp_path):
    """Критерий 4: defect_now на paused=True объект не создаёт; после снятия паузы
    первый же созданный объект -- дефектный (нажатие не теряется)."""
    plugin, _ctx, sp = _make_plugin_with_engine(tmp_path, {"spawn_spacing_mm": [50.0, 50.0], "scene_length_mm": 1e9})
    _push_encoder(sp, 0)
    plugin.produce()  # obj1 -- baseline
    assert len(plugin._spawner.active_objects()) == 1

    assert _call(plugin, "scene.pause", {"paused": True}) == {"status": "ok"}
    assert _call(plugin, "scene.defect_now", {}) == {"status": "ok"}

    step_ticks = 50.0 / FACTOR_MM + 1.0
    _push_encoder(sp, step_ticks)  # порог пройден, но пауза держит -- НЕ должно спавнить
    plugin.produce()
    assert len(plugin._spawner.active_objects()) == 1, "defect_now под паузой не создаёт объект"

    assert _call(plugin, "scene.pause", {"paused": False}) == {"status": "ok"}
    plugin.produce()  # снятие паузы -- порог уже пройден, спавн происходит немедленно
    active = plugin._spawner.active_objects()
    assert len(active) == 2
    newcomer = next(obj for obj in active if obj.passport.spawn_encoder != 0.0)
    assert newcomer.passport.defect == "damaged", "нажатие под паузой не должно потеряться"


# --------------------------------------------------------------------------- #
# scene.defect_rate -- вероятность брака СЛЕДУЮЩИХ спавнов                   #
# --------------------------------------------------------------------------- #


def test_defect_rate_one_makes_every_spawn_defective(tmp_path):
    """Критерий 5: probability=1.0 -> каждый следующий спавн дефектный."""
    plugin, _ctx, sp = _make_plugin_with_engine(tmp_path, {"spawn_spacing_mm": [50.0, 50.0], "scene_length_mm": 1e9})
    assert _call(plugin, "scene.defect_rate", {"probability": 1.0}) == {"status": "ok"}

    _push_encoder(sp, 0)
    plugin.produce()  # obj1 -- rate уже применена ДО этого produce()
    step_ticks = 50.0 / FACTOR_MM + 1.0
    _push_encoder(sp, step_ticks)
    plugin.produce()  # obj2

    active = plugin._spawner.active_objects()
    assert len(active) == 2
    assert all(obj.passport.defect == "damaged" for obj in active)


def test_defect_rate_zero_makes_none(tmp_path):
    """Критерий 5: probability=0.0 -> ни одного дефектного (даже если базовый пресет
    был настроен на 100% брака -- команда должна реально его перекрыть, не совпасть
    с уже нулевым дефолтом)."""
    plugin, _ctx, sp = _make_plugin_with_engine(
        tmp_path,
        {"spawn_spacing_mm": [50.0, 50.0], "scene_length_mm": 1e9, "defect_probability": 1.0},
    )
    assert _call(plugin, "scene.defect_rate", {"probability": 0.0}) == {"status": "ok"}

    _push_encoder(sp, 0)
    plugin.produce()  # obj1
    step_ticks = 50.0 / FACTOR_MM + 1.0
    _push_encoder(sp, step_ticks)
    plugin.produce()  # obj2

    active = plugin._spawner.active_objects()
    assert len(active) == 2
    assert all(obj.passport.defect is None for obj in active)


# --------------------------------------------------------------------------- #
# scene.flow -- смена правила шага спавна на живом движке                    #
# --------------------------------------------------------------------------- #


def test_flow_spacing_mm_sets_step(tmp_path, monkeypatch):
    """Критерий 6: spacing_mm=[144,144] на движущемся энкодере -> шаг спавна 144мм
    (допуск один тик) -- переключение с interval_s на живом спавнере."""
    fake_now = [0.0]
    monkeypatch.setattr("time.monotonic", lambda: fake_now[0])

    plugin, _ctx, sp = _make_plugin_with_engine(tmp_path, {"spawn_interval_s": [1e9, 1e9], "scene_length_mm": 1e9})
    _push_encoder(sp, 0)
    plugin.produce()  # interval: первый tick только взводит срок -- спавна ещё нет
    assert plugin._spawner.active_objects() == []

    assert _call(plugin, "scene.flow", {"spacing_mm": [144.0, 144.0]}) == {"status": "ok"}

    tick_step = 1.0
    tick_mm = tick_step * FACTOR_MM
    now_encoder = 0.0
    spawn_points: list[float] = []
    prev_count = 0
    max_ticks = int(144.0 / tick_mm) * 4 + 50
    for _ in range(max_ticks):
        now_encoder += tick_step
        _push_encoder(sp, now_encoder)
        plugin.produce()
        count = len(plugin._spawner.active_objects())
        if count > prev_count:
            spawn_points.append(now_encoder)
            prev_count = count
        if len(spawn_points) >= 3:
            break

    assert len(spawn_points) == 3, "spacing_mm=[144,144] должен был дать хотя бы 3 спавна за отведённые тики"
    for a, b in zip(spawn_points, spawn_points[1:]):
        gap_mm = (b - a) * FACTOR_MM
        assert 144.0 <= gap_mm <= 144.0 + tick_mm + 1e-9, gap_mm


def test_flow_switch_interval_to_spacing(tmp_path, monkeypatch):
    """Критерий 6: движок стартует в spacing_mm, переключается в interval_s -> следующий
    объект появляется по НОВОМУ (временному) правилу, а не по дальнейшему движению ленты."""
    fake_now = [0.0]
    monkeypatch.setattr("time.monotonic", lambda: fake_now[0])

    plugin, _ctx, sp = _make_plugin_with_engine(tmp_path, {"spawn_spacing_mm": [50.0, 50.0], "scene_length_mm": 1e9})
    _push_encoder(sp, 0)
    plugin.produce()  # spacing: первый спавн сразу
    assert len(plugin._spawner.active_objects()) == 1

    assert _call(plugin, "scene.flow", {"interval_s": [2.0, 2.0]}) == {"status": "ok"}

    plugin.produce()  # энкодер не двигаем -- первый tick под interval только взводит срок
    assert len(plugin._spawner.active_objects()) == 1, "смена режима не должна спавнить мгновенно"

    fake_now[0] += 2.1  # порог interval_s пройден, энкодер по-прежнему не двигался
    plugin.produce()
    assert len(plugin._spawner.active_objects()) == 2, (
        "спавн должен был случиться по ВРЕМЕНИ (interval_s), не по пути ленты -- энкодер держался константой"
    )


# --------------------------------------------------------------------------- #
# Кривые аргументы -- error, ничего не меняется, процесс жив                 #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "command,payload",
    [
        ("scene.pause", {"paused": "yes"}),
        ("scene.flow", {"interval_s": [1.0, 2.0], "spacing_mm": [3.0, 4.0]}),
        ("scene.flow", {}),
        ("scene.flow", {"interval_s": [5.0, 1.0]}),
        ("scene.flow", {"spacing_mm": [0.0, 10.0]}),
        ("scene.defect_rate", {"probability": 1.5}),
        ("scene.defect_rate", {"probability": "x"}),
    ],
)
def test_bad_args_return_error_and_change_nothing(tmp_path, command, payload):
    """Критерий 7: кривые аргументы каждой из команд -> {"status": "error", ...} с
    текстом; процесс жив (следующий produce() не бросает), поведение сцены (число
    активных объектов) не изменилось."""
    plugin, _ctx, sp = _make_plugin_with_engine(tmp_path, {"spawn_spacing_mm": [50.0, 50.0], "scene_length_mm": 1e9})
    _push_encoder(sp, 0)
    plugin.produce()
    active_before = len(plugin._spawner.active_objects())

    result = _call(plugin, command, payload)
    assert result["status"] == "error", f"{command}{payload!r} должен вернуть error, получено {result!r}"
    assert result.get("message"), "текст ошибки должен быть непустым"

    plugin.produce()  # процесс жив -- не бросает
    assert len(plugin._spawner.active_objects()) == active_before, "кривая команда не должна менять сцену"


# --------------------------------------------------------------------------- #
# Команды не трогают спавнер ДО produce()                                    #
# --------------------------------------------------------------------------- #


def test_commands_do_not_touch_spawner_before_produce(tmp_path, monkeypatch):
    """Критерий 8: cmd_pause не имеет права менять спавнер немедленно -- проверяется
    через существующий публичный/полу-публичный атрибут `ObjectSpawner._paused`
    (используется тем же приёмом, каким уже приняты остальные тесты этого файла и
    `Services/line_sim/tests/test_spawner.py` -- НЕ новый угаданный хук)."""
    fake_now = [0.0]
    monkeypatch.setattr("time.monotonic", lambda: fake_now[0])

    plugin, _ctx, sp = _make_plugin_with_engine(tmp_path, {"spawn_interval_s": [1e9, 1e9], "scene_length_mm": 1e9})
    _push_encoder(sp, 0)
    plugin.produce()  # взводит interval-дедлайн, спавнер создан и жив
    assert plugin._spawner is not None
    assert plugin._spawner._paused is False

    assert _call(plugin, "scene.pause", {"paused": True}) == {"status": "ok"}
    assert plugin._spawner._paused is False, "команда не должна менять спавнер ДО produce()"

    plugin.produce()
    assert plugin._spawner._paused is True, "produce() должен применить накопленное намерение"


# --------------------------------------------------------------------------- #
# Команда до первой дельты мира -- не теряется, не роняет процесс            #
# --------------------------------------------------------------------------- #


def test_command_before_first_world_delta_is_not_lost(tmp_path):
    """Критерий 10: команда, пришедшая ДО первой дельты мира (спавнер ещё не тикает,
    `_world_ready is False`), не теряется и не роняет процесс -- применяется на первом
    же подходящем produce()."""
    plugin, _ctx, sp = _make_plugin_with_engine(tmp_path, {"spawn_spacing_mm": [50.0, 50.0], "scene_length_mm": 1e9})
    # Мира ещё не было -- ни одной дельты энкодера.
    assert _call(plugin, "scene.pause", {"paused": True}) == {"status": "ok"}
    assert _call(plugin, "scene.defect_now", {}) == {"status": "ok"}
    plugin.produce()  # мир не готов -- спавнер не тикает вовсе, не должно падать
    assert plugin._spawner.active_objects() == []

    _push_encoder(sp, 0)  # первая дельта мира -- спавнер начинает тикать
    plugin.produce()  # paused=True применяется -- спавн НЕ должен произойти
    assert plugin._spawner.active_objects() == [], "пауза, пришедшая до мира, не должна потеряться"

    assert _call(plugin, "scene.pause", {"paused": False}) == {"status": "ok"}
    plugin.produce()  # снятие паузы -- spacing: первый спавн свободный
    active = plugin._spawner.active_objects()
    assert len(active) == 1
    assert active[0].passport.defect == "damaged", "defect_now, пришедший до мира, не должен потеряться"


# --------------------------------------------------------------------------- #
# scene.status -- paused/flow/defect_probability/force_defect_pending        #
# --------------------------------------------------------------------------- #


def test_status_reports_paused_flow_defect_probability(tmp_path):
    """Критерий 9: scene.status отдаёт paused/flow/defect_probability/
    force_defect_pending, согласованные с РЕАЛЬНЫМ состоянием движка (после
    применения на produce(), не сырая заявка клиента).

    Догадка тестера (см. докстринг файла): форма ``flow`` не описана дословно бри
    фом -- проверяется только присутствие активного режима по имени ключа команды
    (``interval_s``/``spacing_mm``), не весь dict целиком."""
    plugin, _ctx, sp = _make_plugin_with_engine(tmp_path, {"spawn_interval_s": [1e9, 1e9], "scene_length_mm": 1e9})
    _push_encoder(sp, 0)
    plugin.produce()  # взводит дедлайн, ничего не спавнит

    status0 = _call(plugin, "scene.status")
    assert status0["paused"] is False
    assert status0["defect_probability"] == 0.0
    assert status0["force_defect_pending"] is False
    assert "interval_s" in status0["flow"], f"ожидался активный режим interval_s, получено {status0['flow']!r}"

    assert _call(plugin, "scene.pause", {"paused": True}) == {"status": "ok"}
    plugin.produce()
    assert _call(plugin, "scene.status")["paused"] is True

    assert _call(plugin, "scene.defect_rate", {"probability": 0.7}) == {"status": "ok"}
    plugin.produce()
    assert _call(plugin, "scene.status")["defect_probability"] == pytest.approx(0.7)

    assert _call(plugin, "scene.defect_now", {}) == {"status": "ok"}
    plugin.produce()  # дедлайн interval ещё далеко (1e9с) -- спавна нет, флаг не гасится
    assert _call(plugin, "scene.status")["force_defect_pending"] is True

    assert _call(plugin, "scene.flow", {"spacing_mm": [33.0, 33.0]}) == {"status": "ok"}
    plugin.produce()
    status4 = _call(plugin, "scene.status")
    assert "spacing_mm" in status4["flow"], f"после переключения ожидался spacing_mm, получено {status4['flow']!r}"
