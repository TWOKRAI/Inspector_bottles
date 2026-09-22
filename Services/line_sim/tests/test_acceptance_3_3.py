"""Независимые acceptance-тесты Task 3.3 — поток спавна объектов на ленте (`ObjectSpawner`).
Написаны ДО реализации (RED-фаза, tester не видел `_impl/`/Steps плана). Источник
истины — Acceptance criteria и блок "Уточнено лидом 2026-09-22 перед тестером" в
`plans/line-sim/phase-3-object-engine.md` (раздел Task 3.3), НЕ код под тестом.

Публичный контракт под тестом (новое в этой задаче):
    from Services.line_sim import ObjectSpawner
    ObjectSpawner(factory: ObjectFactory, interval_s: tuple[float, float], scene_length_mm: float)
    spawner.tick(now_encoder: float, now_wall_s: float, rng: np.random.Generator) -> None
    spawner.active_objects() -> list[LayeredObject]
    spawner.set_paused(bool) -> None

================================================================================
ПРЕДПОЛОЖЕНИЯ О СИГНАТУРАХ (лид дал контракт явно там, где мог; ниже — что ИМЕННО
дано лидом дословно, и что ДОГАДАНО тестером сверх этого):
================================================================================

ДАНО ЛИДОМ ДОСЛОВНО (не догадка):
- `ObjectSpawner(factory, interval_s, scene_length_mm)` — `ValueError` в конструкторе
  при `lo > hi`, `lo <= 0` или `scene_length_mm <= 0`, с именем параметра в тексте.
- `tick(now_encoder, now_wall_s, rng)` — первый `tick()` только взводит срок
  (`now_wall_s + interval`), объекта не создаёт; создаёт РОВНО один объект за `tick()`,
  когда `now_wall_s >= срок` (граница включительна); пропуски не догоняются, новый
  срок = `now_wall_s (текущего тика) + новый interval`; интервал — `rng.uniform(lo, hi)`.
- `spawn_encoder` объекта = `now_encoder` тика, в котором он создан.
- Despawn в ТОМ ЖЕ `tick()`: `encoder_to_offset_mm(now_encoder, spawn_encoder) >
  scene_length_mm` (строго больше) убирает объект; равно — объект ещё на сцене.
- `active_objects()` — копия (мутация результата не трогает спавнер).
- `set_paused(bool)`: на паузе новые объекты не создаются, НО despawn работает как
  обычно (дословно: "на паузе... despawn работает") — это прямо подтверждает, что
  despawn считается на КАЖДОМ `tick()`, а не только вместе со спавном (см. "ДОГАДАНО").
  После снятия паузы, если срок уже прошёл — объект создаётся в ближайшем `tick()`.
- Форс-хук брака — существующий `ObjectFactory.force_defect_next()` (Task 3.2,
  реализован и смержен), выбран ПЕРВЫЙ вариант критерия 4: на паузе объект не
  создаётся вообще, брак помечает следующий РЕАЛЬНЫЙ спавн (после снятия паузы).

ДОГАДАНО ТЕСТЕРОМ (лид явно не писал — если реализация разойдётся, developer
поправит тест, сам факт критерия остаётся acceptance-требованием):
- Despawn вычисляется на КАЖДОМ вызове `tick()` независимо от того, спавнится ли в
  этом тике новый объект (не только "в момент спавна") — обосновано цитатой лида
  про паузу выше, но явной фразы "despawn при КАЖДОМ tick" в контракте нет дословно.
- Форс-хук вызывается на самом `factory` (`factory.force_defect_next()`), а не через
  метод-обёртку на `ObjectSpawner` — Files-раздел 3.3 в плане не перечисляет метод
  `force_defect_next` в публичном API `spawner.py` (только `tick`/`active_objects`/
  `set_paused`), а хук уже существует и протестирован на `ObjectFactory` (Task 3.2);
  тест держит свою собственную ссылку на `factory` и зовёт хук на ней напрямую —
  это не проверяет ЕСТЬ ли у `ObjectSpawner` метод-делегат с тем же именем.
- `now_encoder`/`now_wall_s` переданы именованными аргументами (контракт даёт только
  порядок и имена в сигнатуре — считаем их keyword-совместимыми, как везде в проекте).
- `object_id` — просто уникальная строка/значение в пределах спавнера; формат не
  проверяется (не дано лидом), только уникальность.

Каталог-фикстура — ОДИН класс (`only_class`), сплошной непрозрачный RGBA 16x16 —
класс/вариативность вне зоны действия Task 3.3 (это Task 3.2), спавнеру нужен
рабочий `ObjectFactory`, не разнообразие классов. Построен так же, как в
`test_acceptance_3_2.py` (`imwrite_unicode`, BGRA на диске, YAML с относительным
`catalog_dir`) — переиспользуется тот же паттерн, не мокается.

Граница despawn (692/693 тиков энкодера, `scene_length_mm=100`) подобрана ВРУЧНУЮ по
`FACTOR_MM = 0.144473` (Services.robot_comm.core.registers), а не вызовом
`ObjectSpawner`/поиском границы кодом под тестом:
    692 * 0.144473 = 99.975316  <= 100  -> объект ещё активен
    693 * 0.144473 = 100.119789 >  100  -> объект уехал
Оба числа — точные (0.144473 * N без остатка на 6 знаках), приведены литералами и
дополнительно сверены через уже протестированный `encoder_to_offset_mm` (Task 3.1,
готовый API — не код под тестом в этом файле).
================================================================================
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest
import yaml

from Services.dataset_gen.core.catalog import imwrite_unicode
from Services.line_sim import FACTOR_MM, ObjectFactory, ObjectSpawner, ScenePreset, encoder_to_offset_mm

# --------------------------------------------------------------------------
# Фикстура-помощник: минимальный рабочий ObjectFactory поверх одного класса
# --------------------------------------------------------------------------


def _make_factory(tmp_path: Path, defect_probability: float = 0.0) -> ObjectFactory:
    """Каталог-фикстура из ОДНОГО класса + пресет без доп. слоёв — достаточно для
    ObjectSpawner (класс/вариативность спрайтов — Task 3.2, не Task 3.3)."""
    class_dir = tmp_path / "catalog" / "only_class"
    class_dir.mkdir(parents=True)
    sprite = np.zeros((16, 16, 4), dtype=np.uint8)
    sprite[:, :, :3] = 128
    sprite[:, :, 3] = 255
    imwrite_unicode(class_dir / "sprite.png", cv2.cvtColor(sprite, cv2.COLOR_RGBA2BGRA))

    preset_path = tmp_path / "preset.yaml"
    preset_path.write_text(
        yaml.safe_dump(
            {"catalog_dir": "catalog", "layers": [], "defect_probability": defect_probability},
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    preset = ScenePreset.from_yaml(preset_path)
    return ObjectFactory(preset)


# --------------------------------------------------------------------------
# Фиксированный интервал: ровно 5 объектов за 5 шагов по 0.5с (критерий 1)
# --------------------------------------------------------------------------


def test_fixed_interval_spawns_exactly_five(tmp_path):
    factory = _make_factory(tmp_path)
    spawner = ObjectSpawner(factory, interval_s=(0.5, 0.5), scene_length_mm=1_000_000.0)
    rng = np.random.default_rng(1)

    spawner.tick(now_encoder=0.0, now_wall_s=0.0, rng=rng)  # только взводит срок, без спавна
    assert len(spawner.active_objects()) == 0

    for now_wall_s in (0.5, 1.0, 1.5, 2.0, 2.5):
        spawner.tick(now_encoder=0.0, now_wall_s=now_wall_s, rng=rng)

    assert len(spawner.active_objects()) == 5


def test_no_catch_up_after_long_gap(tmp_path):
    """tick(t=0) затем tick(t=10) -> РОВНО 1 объект, пропуски не догоняются."""
    factory = _make_factory(tmp_path)
    spawner = ObjectSpawner(factory, interval_s=(0.5, 0.5), scene_length_mm=1_000_000.0)
    rng = np.random.default_rng(2)

    spawner.tick(now_encoder=0.0, now_wall_s=0.0, rng=rng)
    spawner.tick(now_encoder=0.0, now_wall_s=10.0, rng=rng)

    assert len(spawner.active_objects()) == 1


# --------------------------------------------------------------------------
# Despawn — строго больше scene_length_mm (критерий 2)
# --------------------------------------------------------------------------


def test_despawn_boundary_strictly_greater(tmp_path):
    assert FACTOR_MM == 0.144473  # пин константы, из которой вручную посчитаны 692/693 ниже
    factory = _make_factory(tmp_path)
    spawner = ObjectSpawner(factory, interval_s=(1000.0, 1000.0), scene_length_mm=100.0)
    rng = np.random.default_rng(3)

    spawner.tick(now_encoder=0.0, now_wall_s=0.0, rng=rng)  # взвод
    spawner.tick(now_encoder=0.0, now_wall_s=1000.0, rng=rng)  # спавн, spawn_encoder=0.0
    assert len(spawner.active_objects()) == 1

    # 692 * FACTOR_MM = 99.975316 <= 100 -> ещё на сцене (см. блок предположений сверху)
    offset_active = encoder_to_offset_mm(692.0, 0.0)
    assert offset_active == pytest.approx(99.975316, abs=1e-6)
    spawner.tick(now_encoder=692.0, now_wall_s=1000.1, rng=rng)
    assert len(spawner.active_objects()) == 1

    # 693 * FACTOR_MM = 100.119789 > 100 -> уехал
    offset_gone = encoder_to_offset_mm(693.0, 0.0)
    assert offset_gone == pytest.approx(100.119789, abs=1e-6)
    spawner.tick(now_encoder=693.0, now_wall_s=1000.2, rng=rng)
    assert len(spawner.active_objects()) == 0


# --------------------------------------------------------------------------
# Пауза: 0 новых, существующие двигаются (критерий 3)
# --------------------------------------------------------------------------


def test_pause_stops_new_keeps_existing_moving(tmp_path):
    factory = _make_factory(tmp_path)
    spawner = ObjectSpawner(factory, interval_s=(0.5, 0.5), scene_length_mm=1_000_000.0)
    rng = np.random.default_rng(4)

    spawner.tick(now_encoder=0.0, now_wall_s=0.0, rng=rng)
    spawner.tick(now_encoder=0.0, now_wall_s=0.5, rng=rng)  # единственный объект
    active = spawner.active_objects()
    assert len(active) == 1
    obj_id = active[0].passport.object_id
    spawn_encoder = active[0].passport.spawn_encoder

    spawner.set_paused(True)

    now_wall = 0.5
    now_encoder = 0.0
    offsets: list[float] = []
    for _ in range(10):  # 5 симулированных секунд по 0.5с, много раз пересекает срок 0.5с
        now_wall += 0.5
        now_encoder += 1000.0
        spawner.tick(now_encoder=now_encoder, now_wall_s=now_wall, rng=rng)
        offsets.append(encoder_to_offset_mm(now_encoder, spawn_encoder))

    active = spawner.active_objects()
    assert len(active) == 1  # ни одного нового за 5 секунд паузы
    assert active[0].passport.object_id == obj_id  # тот же объект, не пересоздан
    assert offsets[-1] > offsets[0]  # позиция растёт вместе с now_encoder на паузе


def test_unpause_after_deadline_spawns_on_next_tick(tmp_path):
    factory = _make_factory(tmp_path)
    spawner = ObjectSpawner(factory, interval_s=(0.5, 0.5), scene_length_mm=1_000_000.0)
    rng = np.random.default_rng(5)

    spawner.tick(now_encoder=0.0, now_wall_s=0.0, rng=rng)  # срок = 0.5
    spawner.set_paused(True)
    spawner.tick(now_encoder=0.0, now_wall_s=5.0, rng=rng)  # срок давно прошёл, но пауза
    assert len(spawner.active_objects()) == 0

    spawner.set_paused(False)
    spawner.tick(now_encoder=0.0, now_wall_s=5.1, rng=rng)  # снятие паузы -> спавн на ближайшем tick
    assert len(spawner.active_objects()) == 1


# --------------------------------------------------------------------------
# Форс-хук брака на паузе (критерий 4, выбранный лидом вариант)
# --------------------------------------------------------------------------


def test_force_defect_on_pause_marks_next_real_spawn(tmp_path):
    factory = _make_factory(tmp_path, defect_probability=0.0)
    spawner = ObjectSpawner(factory, interval_s=(0.5, 0.5), scene_length_mm=1_000_000.0)
    rng = np.random.default_rng(6)

    spawner.tick(now_encoder=0.0, now_wall_s=0.0, rng=rng)  # срок = 0.5
    spawner.set_paused(True)
    factory.force_defect_next()
    spawner.tick(now_encoder=0.0, now_wall_s=5.0, rng=rng)  # срок прошёл, но пауза -> нет спавна
    assert len(spawner.active_objects()) == 0

    spawner.set_paused(False)
    spawner.tick(now_encoder=0.0, now_wall_s=5.1, rng=rng)  # первый реальный спавн после паузы
    first_batch = spawner.active_objects()
    assert len(first_batch) == 1
    assert first_batch[0].passport.defect == "damaged"
    first_id = first_batch[0].passport.object_id

    spawner.tick(now_encoder=0.0, now_wall_s=5.6, rng=rng)  # следующий обычный спавн (prob=0.0)
    second_batch = spawner.active_objects()
    assert len(second_batch) == 2
    newcomer = next(o for o in second_batch if o.passport.object_id != first_id)
    assert newcomer.passport.defect is None


# --------------------------------------------------------------------------
# spawn_encoder, уникальность id, копия active_objects()
# --------------------------------------------------------------------------


def test_spawn_encoder_equals_tick_encoder(tmp_path):
    factory = _make_factory(tmp_path)
    spawner = ObjectSpawner(factory, interval_s=(0.5, 0.5), scene_length_mm=1_000_000.0)
    rng = np.random.default_rng(7)

    spawner.tick(now_encoder=123.0, now_wall_s=0.0, rng=rng)  # взвод, энкодер тика не спавнящего не важен
    spawner.tick(now_encoder=999.0, now_wall_s=0.5, rng=rng)  # спавн ИМЕННО на этом тике

    active = spawner.active_objects()
    assert len(active) == 1
    assert active[0].passport.spawn_encoder == 999.0


def test_object_ids_unique_over_twenty_spawns(tmp_path):
    factory = _make_factory(tmp_path)
    spawner = ObjectSpawner(factory, interval_s=(0.5, 0.5), scene_length_mm=1_000_000.0)
    rng = np.random.default_rng(8)

    now_wall = 0.0
    spawner.tick(now_encoder=0.0, now_wall_s=now_wall, rng=rng)
    for _ in range(20):
        now_wall += 0.5
        spawner.tick(now_encoder=0.0, now_wall_s=now_wall, rng=rng)

    active = spawner.active_objects()
    assert len(active) == 20
    ids = [obj.passport.object_id for obj in active]
    assert len(set(ids)) == 20


def test_active_objects_returns_copy(tmp_path):
    factory = _make_factory(tmp_path)
    spawner = ObjectSpawner(factory, interval_s=(0.5, 0.5), scene_length_mm=1_000_000.0)
    rng = np.random.default_rng(9)

    spawner.tick(now_encoder=0.0, now_wall_s=0.0, rng=rng)
    spawner.tick(now_encoder=0.0, now_wall_s=0.5, rng=rng)

    first = spawner.active_objects()
    assert len(first) == 1
    first.clear()  # мутация результата не должна тронуть внутреннее состояние спавнера

    second = spawner.active_objects()
    assert len(second) == 1


# --------------------------------------------------------------------------
# Валидация конструктора (edge cases)
# --------------------------------------------------------------------------


def test_constructor_rejects_interval_lo_greater_than_hi(tmp_path):
    factory = _make_factory(tmp_path)
    with pytest.raises(ValueError, match="interval_s"):
        ObjectSpawner(factory, interval_s=(1.0, 0.5), scene_length_mm=100.0)


def test_constructor_rejects_nonpositive_interval_lo(tmp_path):
    factory = _make_factory(tmp_path)
    with pytest.raises(ValueError, match="interval_s"):
        ObjectSpawner(factory, interval_s=(0.0, 1.0), scene_length_mm=100.0)


def test_constructor_rejects_nonpositive_scene_length_mm(tmp_path):
    factory = _make_factory(tmp_path)
    with pytest.raises(ValueError, match="scene_length_mm"):
        ObjectSpawner(factory, interval_s=(0.5, 1.0), scene_length_mm=0.0)
