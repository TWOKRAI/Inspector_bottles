# -*- coding: utf-8 -*-
"""Hazard-тесты автора для очереди управления `scene_source` (Task 6.1, контракт лида
`plans/line-sim/phase-6-contract-6.1.md`) — что может сломаться ИМЕННО в этом механизме:

- разбор очереди управления (`self._control`) не в порядке поступления — «в силе
  последняя» для pause/flow перестаёт быть гарантией FIFO;
- переполнение `maxlen` очереди управления — растёт без предела, если `produce()`
  никогда не зовут (движок собран, но продюсер не запущен);
- `scene.defect_now` — булев ОДНОРАЗОВЫЙ флаг `ObjectFactory.force_defect_next()`, не
  счётчик: два нажатия подряд без спавна между ними обязаны СХЛОПНУТЬСЯ бы в один
  дефект без явной отсрочки второй заявки в `_drain_control()` — тест фиксирует именно
  отсрочку, не только конечный результат (уже покрытый приёмкой);
- гонка `scene.defect_rate` <-> `preset.commit` за один `_pending_factory` (maxlen=1) —
  контракт называет это явно (edge case §3): в силе последняя ПОСТАВЛЕННАЯ, порядок
  вызовов команд, не порядок объявления в контракте.

Своя копия харнесса (тот же приём, что `test_scene_controls_acceptance.py` — файл
самодостаточен, ничего оттуда не импортирует, RED-файл тестера не трогается).
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Callable
from unittest.mock import MagicMock

import cv2
import numpy as np
import pytest
import yaml

from multiprocess_framework.modules.state_store_module.core.delta import Delta
from Services.dataset_gen.core.catalog import imwrite_unicode
from Services.line_sim.core.belt import FACTOR_MM
from Plugins.sim.scene_source.plugin import SceneSourcePlugin

pytestmark = pytest.mark.timeout(30)


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


def _make_fixture_catalog(tmp_path: Path) -> Path:
    classes_dir = tmp_path / f"classes_{uuid.uuid4().hex}"
    class_dir = classes_dir / "square"
    class_dir.mkdir(parents=True)
    sprite = np.zeros((16, 16, 4), dtype=np.uint8)
    sprite[:, :, :3] = 128
    sprite[:, :, 3] = 255
    imwrite_unicode(class_dir / "sprite.png", cv2.cvtColor(sprite, cv2.COLOR_RGBA2BGRA))
    return classes_dir


def _make_plugin(cfg_overrides: dict) -> tuple[SceneSourcePlugin, _FakeStateProxy]:
    state_proxy = _FakeStateProxy()
    ctx = MagicMock()
    ctx.state_proxy = state_proxy
    ctx.config = {
        "resolution_width": 64,
        "resolution_height": 64,
        "spawn_encoder": 0,
        "px_per_mm": 1.0,
        **cfg_overrides,
    }
    plugin = SceneSourcePlugin()
    plugin.configure(ctx)
    plugin.start(ctx)
    return plugin, state_proxy


def _make_plugin_with_engine(tmp_path: Path, cfg_overrides: dict) -> tuple[SceneSourcePlugin, _FakeStateProxy]:
    catalog_dir = _make_fixture_catalog(tmp_path)
    plugin, sp = _make_plugin({"preset_path": str(catalog_dir), **cfg_overrides})
    assert plugin._spawner is not None, "фикстура должна собрать движок"
    return plugin, sp


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
    return getattr(plugin, plugin.commands[name])(data)


# --------------------------------------------------------------------------- #
# Разбор очереди управления строго в порядке поступления (FIFO)               #
# --------------------------------------------------------------------------- #


def test_control_queue_applies_pause_toggles_in_fifo_order(tmp_path):
    """Четыре команды `scene.pause` подряд (False/True/False/True) ДО produce() -- в силе
    обязана остаться ПОСЛЕДНЯЯ ПОСТАВЛЕННАЯ (True). Разбор `deque` через `pop()` вместо
    `popleft()` (LIFO вместо FIFO) применил бы их в обратном порядке и оставил бы False --
    инъекция такой перестановки обязана убить этот тест."""
    plugin, sp = _make_plugin_with_engine(tmp_path, {"spawn_spacing_mm": [10.0, 10.0], "scene_length_mm": 1e9})
    _push_encoder(sp, 0)
    plugin.produce()

    for paused in (False, True, False, True):
        assert _call(plugin, "scene.pause", {"paused": paused}) == {"status": "ok"}
    assert plugin._spawner._paused is False, "до produce() спавнер не должен меняться"

    plugin.produce()
    assert plugin._spawner._paused is True, "в силе последняя ПОСТАВЛЕННАЯ команда (FIFO), не первая"


# --------------------------------------------------------------------------- #
# maxlen очереди управления -- явный потолок, не безграничный рост            #
# --------------------------------------------------------------------------- #


def test_control_queue_ceiling_literal_is_64(tmp_path):
    """Потолок очереди -- ЛИТЕРАЛ, а не то, что написано в коде под тестом (ревью
    итерация 2: все тесты потолка читали `plugin._control.maxlen`, поэтому смена 64 на 1
    никого бы не уронила, а README называет 64 контрактом)."""
    plugin, _sp = _make_plugin_with_engine(tmp_path, {"spawn_spacing_mm": [1e9, 1e9], "scene_length_mm": 1e9})
    assert plugin._control.maxlen == 64


def test_control_queue_maxlen_bounds_growth_when_produce_never_called(tmp_path):
    """Контракт лида, edge case §3: очередь управления не должна расти без предела, если
    produce() не зовут. Находка Ф3(б), ревью итерация 2: `deque(maxlen=...)` больше НЕ
    роняет старые заявки молча -- переполнение отвечает `overloaded` и не кладёт заявку
    вовсе (см. `_push_control`, `test_control_queue_full_rejects_instead_of_dropping_oldest`
    -- полная проверка находки там); здесь -- только сам факт потолка (очередь не растёт
    сверх maxlen, а выжившие -- это ПЕРВЫЕ поставленные, не какие попало)."""
    plugin, _sp = _make_plugin_with_engine(tmp_path, {"spawn_spacing_mm": [10.0, 10.0], "scene_length_mm": 1e9})

    maxlen = plugin._control.maxlen
    assert maxlen is not None and maxlen > 0, "потолок очереди управления должен быть задан явно"

    n_pushed = maxlen + 20
    ok_count = 0
    overloaded_count = 0
    for i in range(n_pushed):
        res = _call(plugin, "scene.pause", {"paused": bool(i % 2)})
        if res == {"status": "ok"}:
            ok_count += 1
        else:
            assert res["status"] == "error" and res["code"] == "overloaded", res
            overloaded_count += 1

    assert ok_count == maxlen, "ровно maxlen заявок обязаны быть приняты"
    assert overloaded_count == n_pushed - maxlen, "остальные обязаны быть отклонены, не приняты молча"
    assert len(plugin._control) == maxlen, "очередь не должна расти сверх заявленного потолка"
    # Выжившие -- это ПЕРВЫЕ поставленные (paused = bool(i % 2) для i=0..maxlen-1) --
    # переполнение отклоняет НОВЫЕ заявки, не роняет старые.
    assert plugin._control[-1]["paused"] == bool((maxlen - 1) % 2)


# --------------------------------------------------------------------------- #
# scene.defect_now -- булев одноразовый флаг, второе нажатие ждёт своей очереди #
# --------------------------------------------------------------------------- #


def test_defect_now_second_press_stays_queued_until_first_is_consumed(tmp_path):
    """`ObjectFactory.force_defect_next()` -- булев флаг, не счётчик (Task 3.2). Два
    нажатия `scene.defect_now` ДО того, как первое досталось спавну, не имеют права
    схлопнуться в один дефектный объект: второе ждёт своей очереди, пока флаг не погашен.

    Проверяется НАБЛЮДАЕМЫЙ итог (два дефектных объекта), а не место хранения заявки:
    первая редакция держала её в голове `_control` и блокировала этим всю очередь
    (дефект, найденный инъекцией лида 2026-09-28 -- см. `test_lead_6_1.py`), сейчас это
    счётчик кредитов. Тест не должен падать от такой замены -- он про свойство."""
    plugin, sp = _make_plugin_with_engine(tmp_path, {"spawn_spacing_mm": [10.0, 10.0], "scene_length_mm": 1e9})
    _push_encoder(sp, 0)
    plugin.produce()  # obj1 -- первый спавн spacing-режима, он НЕ дефектный
    assert len(plugin._spawner.active_objects()) == 1
    assert plugin._spawner.active_objects()[0].passport.defect is None

    assert _call(plugin, "scene.defect_now", {}) == {"status": "ok"}
    assert _call(plugin, "scene.defect_now", {}) == {"status": "ok"}

    plugin.produce()  # энкодер не двигаем -- порог не пройден, спавна нет
    assert len(plugin._spawner.active_objects()) == 1, "фикстура: спавна в этом produce() быть не должно"
    assert plugin._live_factory.force_defect_pending is True, "первое нажатие уже отдано фабрике"

    # лента едет: оба нажатия обязаны стать ДВУМЯ дефектными объектами, не одним
    for i in range(1, 4):
        _push_encoder(sp, i * 10.0 / FACTOR_MM)
        plugin.produce()
    defects = [obj for obj in plugin._spawner.active_objects() if obj.passport.defect is not None]
    assert len(defects) == 2, "второе нажатие потеряно -- два нажатия схлопнулись в один брак"


# --------------------------------------------------------------------------- #
# scene.defect_rate <-> preset.commit -- гонка за _pending_factory (maxlen=1) #
# --------------------------------------------------------------------------- #


def _make_yaml_preset_plugin(tmp_path: Path) -> tuple[SceneSourcePlugin, _FakeStateProxy, Path]:
    class_dir = tmp_path / "cat" / "square"
    class_dir.mkdir(parents=True)
    sprite = np.zeros((16, 16, 4), dtype=np.uint8)
    sprite[:, :, :3] = 128
    sprite[:, :, 3] = 255
    imwrite_unicode(class_dir / "sprite.png", cv2.cvtColor(sprite, cv2.COLOR_RGBA2BGRA))

    preset_path = tmp_path / "preset.yaml"
    preset_path.write_text(
        yaml.safe_dump({"catalog_dir": "cat", "defect_probability": 0.0, "layers": []}, sort_keys=False),
        encoding="utf-8",
    )
    plugin, sp = _make_plugin(
        {
            "preset_path": str(preset_path),
            "spawn_spacing_mm": [50.0, 50.0],
            "scene_length_mm": 1e9,
        }
    )
    assert plugin._spawner is not None, "фикстура должна собрать движок из .yaml-пресета"
    return plugin, sp, preset_path


def test_defect_rate_override_persists_across_later_preset_commit(tmp_path):
    """Контракт лида шаг 6, буквально: "`self._defect_override` обновляется, чтобы
    последующий `preset.commit` не вернул старую долю брака" -- `cmd_preset_commit`
    ВСЕГДА пересобирает фабрику через `apply_defect_override(preset, self._defect_override)`
    (существующий механизм, не новый), поэтому `scene.defect_rate`, поставленный РАНЬШЕ
    `preset.commit` в том же кадре, обязан ПЕРЕЖИТЬ commit -- даже если клиент commit'а
    прислал СВОЙ, другой `defect_probability` в payload. Файл при этом пишется буквально
    тем, что прислал клиент (`preset.commit` не переписывает payload override'ом) --
    расхождение файл/применённое поведение -- то же самое, что уже существует для
    config-уровневого override (`load_scene_preset`), не новая дыра этой задачи."""
    plugin, sp, preset_path = _make_yaml_preset_plugin(tmp_path)
    _push_encoder(sp, 0)
    plugin.produce()  # baseline spawn, обычный defect_probability=0.0

    assert _call(plugin, "scene.defect_rate", {"probability": 0.3}) == {"status": "ok"}

    got = _call(plugin, "preset.get", {})
    preset_dict = dict(got["preset"])
    preset_dict["defect_probability"] = 1.0
    commit_res = _call(plugin, "preset.commit", {"preset": preset_dict, "base_rev": got["rev"]})
    assert commit_res["status"] == "ok" and commit_res["changed"] is True, commit_res

    assert len(plugin._pending_factory) == 1, "maxlen=1 -- в очереди подмены ровно одна фабрика"

    plugin.produce()  # применяет фабрику commit'а -- но пересобранную с override'ом defect_rate
    assert plugin._live_factory._preset.defect_probability == pytest.approx(0.3), (
        "override defect_rate обязан пережить последующий preset.commit (контракт лида шаг 6)"
    )
    on_disk = yaml.safe_load(preset_path.read_text(encoding="utf-8"))
    assert on_disk["defect_probability"] == 1.0, "файл пишется буквально payload'ом клиента, override его не трогает"

    # Обратный порядок: scene.defect_rate вызван ПОСЛЕДНИМ в кадре -> его фабрика (не
    # commit'а) обязана быть последней поставленной в _pending_factory (maxlen=1).
    got2 = _call(plugin, "preset.get", {})
    preset_dict2 = dict(got2["preset"])
    preset_dict2["defect_probability"] = 0.2
    commit_res2 = _call(plugin, "preset.commit", {"preset": preset_dict2, "base_rev": got2["rev"]})
    assert commit_res2["status"] == "ok" and commit_res2["changed"] is True, commit_res2
    assert _call(plugin, "scene.defect_rate", {"probability": 0.9}) == {"status": "ok"}  # вызван ПОСЛЕДНИМ теперь

    plugin.produce()
    assert plugin._defect_override == pytest.approx(0.9)
    assert plugin._live_factory._preset.defect_probability == pytest.approx(0.9), (
        "второй раунд: последний вызванный -- scene.defect_rate, его фабрика и должна победить"
    )


# --------------------------------------------------------------------------- #
# Ревью итерация 2 (5 находок, plans/line-sim/phase-6-contract-6.1.md)        #
# --------------------------------------------------------------------------- #


def test_defect_rate_after_preset_commit_keeps_committed_layers(tmp_path):
    """Находка Ф1: `self._preset` пишется только в `configure()`, поэтому после ЛЮБОГО
    `preset.commit` оно протухает -- `cmd_defect_rate` пересобирает фабрику из
    УСТАРЕВШЕГО пресета и откатывает содержательную правку commit'а. Проверяем полем,
    не связанным с `defect_probability` (`angle_range_deg`), чтобы не спутать с Ф2/
    override-полем: commit меняет угол с [0,0] на [10,10], затем `scene.defect_rate` --
    применённая (последняя в `_pending_factory`, maxlen=1) фабрика обязана нести
    committed [10,10], а не сконфигурированные [0,0]."""
    class_dir = tmp_path / "cat" / "square"
    class_dir.mkdir(parents=True)
    sprite = np.zeros((16, 16, 4), dtype=np.uint8)
    sprite[:, :, :3] = 128
    sprite[:, :, 3] = 255
    imwrite_unicode(class_dir / "sprite.png", cv2.cvtColor(sprite, cv2.COLOR_RGBA2BGRA))

    preset_path = tmp_path / "preset.yaml"
    preset_path.write_text(
        yaml.safe_dump(
            {"catalog_dir": "cat", "defect_probability": 0.0, "angle_range_deg": [0.0, 0.0], "layers": []},
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    plugin, sp = _make_plugin(
        {"preset_path": str(preset_path), "spawn_spacing_mm": [10.0, 10.0], "scene_length_mm": 1e9}
    )
    assert plugin._spawner is not None, "фикстура должна собрать движок из .yaml-пресета"

    got = _call(plugin, "preset.get", {})
    preset_dict = dict(got["preset"])
    preset_dict["angle_range_deg"] = [10.0, 10.0]
    commit_res = _call(plugin, "preset.commit", {"preset": preset_dict, "base_rev": got["rev"]})
    assert commit_res["status"] == "ok" and commit_res["changed"] is True, commit_res

    assert _call(plugin, "scene.defect_rate", {"probability": 0.0}) == {"status": "ok"}

    _push_encoder(sp, 0)
    plugin.produce()  # применяет ПОСЛЕДНЮЮ фабрику в _pending_factory -- фабрику defect_rate
    active = plugin._spawner.active_objects()
    assert len(active) == 1
    assert active[0].passport.angle_deg == pytest.approx(10.0), (
        "фабрика defect_rate обязана нести правку preset.commit, а не устаревший self._preset из configure()"
    )


def test_status_defect_probability_is_applied_not_requested(tmp_path):
    """Находка Ф2: `scene.status["defect_probability"]` обязан отдавать ПРИМЕНЁННОЕ
    значение (у `self._live_factory`), а не заявку `scene.defect_rate`, которая ещё
    сидит в `_pending_factory` и применится только на следующем `produce()`."""
    plugin, sp = _make_plugin_with_engine(tmp_path, {"spawn_spacing_mm": [10.0, 10.0], "scene_length_mm": 1e9})
    _push_encoder(sp, 0)
    plugin.produce()  # фабрика configure(), defect_probability дефолтный 0.0
    assert _call(plugin, "scene.status")["defect_probability"] == pytest.approx(0.0)

    assert _call(plugin, "scene.defect_rate", {"probability": 0.9}) == {"status": "ok"}
    status_pending = _call(plugin, "scene.status")
    assert status_pending["defect_probability"] == pytest.approx(0.0), (
        "заявка ещё не применена produce() -- scene.status обязан отдавать ПРИМЕНЁННОЕ, не заявленное"
    )

    plugin.produce()  # применяет фабрику defect_rate
    assert _call(plugin, "scene.status")["defect_probability"] == pytest.approx(0.9)


def test_controls_report_not_applied_without_engine(tmp_path):
    """Находка Ф3(а): без собранного движка (`self._spawner is None`) три ручки обязаны
    отдавать `applied: False` и НИЧЕГО не класть в очередь управления -- как уже делает
    `scene.defect_rate`. Раньше `scene.pause`/`scene.flow`/`scene.defect_now` отвечали
    голым `{"status": "ok"}` и клали заявку, которую `_drain_control()` потом молча
    выбрасывает (некому применять) -- клиент получал ложный `ok`."""
    plugin, _sp = _make_plugin({"preset_path": str(tmp_path / "does-not-exist")})
    assert plugin._spawner is None, "фикстура: движок не должен был собраться"

    assert _call(plugin, "scene.pause", {"paused": True}) == {"status": "ok", "applied": False}
    assert len(plugin._control) == 0, "заявка не должна была попасть в очередь -- некому её применять"

    assert _call(plugin, "scene.flow", {"spacing_mm": [10.0, 10.0]}) == {"status": "ok", "applied": False}
    assert len(plugin._control) == 0

    assert _call(plugin, "scene.defect_now", {}) == {"status": "ok", "applied": False}
    assert len(plugin._control) == 0


def test_control_queue_full_rejects_instead_of_dropping_oldest(tmp_path):
    """Находка Ф3(б): `deque(maxlen=64)` молча роняет САМЫЕ СТАРЫЕ заявки при
    переполнении -- теряется самая ранняя (например снятие паузы). Вместо этого --
    явная проверка перед `append`: переполнение отвечает `{"status": "error", "code":
    "overloaded", ...}` и не кладёт заявку, а первая поставленная остаётся на месте."""
    plugin, _sp = _make_plugin_with_engine(tmp_path, {"spawn_spacing_mm": [10.0, 10.0], "scene_length_mm": 1e9})
    maxlen = plugin._control.maxlen
    assert maxlen is not None and maxlen > 0

    assert _call(plugin, "scene.pause", {"paused": True}) == {"status": "ok"}
    for i in range(1, maxlen):
        assert _call(plugin, "scene.pause", {"paused": bool(i % 2)}) == {"status": "ok"}
    assert len(plugin._control) == maxlen

    overflow = _call(plugin, "scene.pause", {"paused": False})
    assert overflow["status"] == "error" and overflow["code"] == "overloaded", overflow
    assert overflow.get("message"), "текст ошибки должен быть непустым"
    assert len(plugin._control) == maxlen, "переполнение не должно менять размер очереди"
    assert plugin._control[0] == {"op": "pause", "paused": True}, (
        "самая первая заявка обязана остаться на месте -- не потеряна переполнением"
    )


def test_defect_now_rejects_garbage_payload(tmp_path):
    """Находка Ф4 (часть 1): `scene.defect_now` не валидировал ничего -- любой мусор в
    payload давал `ok`. Принимать только `None`/`{}`, иначе `invalid`, очередь не
    трогается."""
    plugin, _sp = _make_plugin_with_engine(tmp_path, {"spawn_spacing_mm": [10.0, 10.0], "scene_length_mm": 1e9})

    res = _call(plugin, "scene.defect_now", "мусор")
    assert res["status"] == "error" and res["code"] == "invalid", res
    assert len(plugin._control) == 0

    res2 = _call(plugin, "scene.defect_now", {"unexpected": 1})
    assert res2["status"] == "error" and res2["code"] == "invalid", res2
    assert len(plugin._control) == 0

    assert _call(plugin, "scene.defect_now", {}) == {"status": "ok"}
    assert _call(plugin, "scene.defect_now", None) == {"status": "ok"}


def test_flow_rejects_explicit_null_second_key(tmp_path):
    """Находка Ф4 (часть 2): присутствие ключа в `cmd_flow` обязано определяться через
    `in data`, а не `is not None` -- второй ключ, явно выставленный в `None`, всё равно
    СЧИТАЕТСЯ присутствующим, и тогда в payload'е присутствуют ОБА ключа -- `invalid`,
    как и при двух непустых значениях."""
    plugin, _sp = _make_plugin_with_engine(tmp_path, {"spawn_spacing_mm": [10.0, 10.0], "scene_length_mm": 1e9})

    res = _call(plugin, "scene.flow", {"interval_s": [1.0, 2.0], "spacing_mm": None})
    assert res["status"] == "error" and res["code"] == "invalid", res
    assert len(plugin._control) == 0
