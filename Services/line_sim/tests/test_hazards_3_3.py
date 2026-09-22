"""Hazard-тесты автора для `ObjectSpawner` (Task 3.3) — ловушки самого механизма:
копия `active_objects()`, устойчивость к исключению `factory.make()` внутри `tick()`
(частота интервала, не кадра — review fix F1), деспавн по СОБСТВЕННОМУ `spawn_encoder`
объекта, потолок активного списка вместо энкодерного правила (review fix F2, замена
отвергнутой версии — LS-008), делегат `force_defect_next()` через спавнер (review fix
F3), джиттер интервала в границах.

Не переиспользует и не расширяет `test_acceptance_3_3.py` (независимые acceptance-тесты
тестера) — своя фикстура-фабрика (тот же паттерн из `test_acceptance_3_2.py`).
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest
import yaml

from Services.dataset_gen.core.catalog import imwrite_unicode
from Services.line_sim import ObjectFactory, ObjectSpawner, ScenePreset
from Services.line_sim.core.belt import FACTOR_MM, encoder_to_offset_mm


def _make_factory(tmp_path: Path, defect_probability: float = 0.0) -> ObjectFactory:
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


def test_active_objects_copy_survives_mutation_and_later_despawn(tmp_path):
    """`active_objects()` — копия: `.clear()`/`.pop()` результата не трогают внутренний
    список, и деспавн следующим `tick()` по-прежнему видит объект и снимает его."""
    factory = _make_factory(tmp_path)
    spawner = ObjectSpawner(factory, interval_s=(0.5, 0.5), scene_length_mm=100.0)
    rng = np.random.default_rng(101)

    spawner.tick(now_encoder=0.0, now_wall_s=0.0, rng=rng)
    spawner.tick(now_encoder=0.0, now_wall_s=0.5, rng=rng)
    snapshot = spawner.active_objects()
    assert len(snapshot) == 1
    snapshot.pop()  # мутация копии — не должна тронуть внутренний список спавнера
    snapshot.append("посторонний объект")  # даже подмена элемента копии — изолирована

    assert len(spawner.active_objects()) == 1  # спавнер не заметил мутацию копии

    # despawn всё ещё работает после мутации возвращённой копии (693 * FACTOR_MM > 100)
    spawner.tick(now_encoder=693.0, now_wall_s=0.5, rng=rng)
    assert spawner.active_objects() == []


def test_permanent_factory_failure_raises_at_interval_frequency_not_tick_frequency(tmp_path, monkeypatch):
    """[review fix F1] Постоянный сбой `factory.make()` — исключение прилетает НА ЧАСТОТЕ
    ИНТЕРВАЛА (срок сдвигается независимо от успеха), а не на частоте каждого кадра
    продюсера — репродукция ревью: 286 исключений за 300 тиков на 30 fps до фикса.
    Тики идут вдвое чаще интервала (шаг 0.25с при интервале 0.5с — обе величины кратны
    степени двойки, сумма float точна): 12 тиков после взвода, из них должно упасть
    исключение РОВНО на 6 — каждый второй, не на всех двенадцати."""
    factory = _make_factory(tmp_path)
    calls = {"n": 0}

    def _always_fails(*args, **kwargs):
        calls["n"] += 1
        raise RuntimeError("постоянный сбой каталога")

    spawner = ObjectSpawner(factory, interval_s=(0.5, 0.5), scene_length_mm=1_000_000.0)
    rng = np.random.default_rng(105)
    spawner.tick(now_encoder=0.0, now_wall_s=0.0, rng=rng)  # взвод срока = 0.5

    monkeypatch.setattr(factory, "make", _always_fails)

    exceptions = 0
    for i in range(1, 13):  # 12 тиков по 0.25с = 3.0с, интервал 0.5с -> 6 срабатываний
        now_wall_s = i * 0.25
        try:
            spawner.tick(now_encoder=0.0, now_wall_s=now_wall_s, rng=rng)
        except RuntimeError:
            exceptions += 1

    assert exceptions == 6  # НЕ 12 (частота кадра) -- частота интервала
    assert calls["n"] == 6
    assert spawner.active_objects() == []  # make() всегда падает -- ни один объект не выжил


def test_transient_factory_failure_loses_at_most_one_object_and_keeps_forced_defect(tmp_path, monkeypatch):
    """[review fix F1] Один транзитный сбой `factory.make()` — окно теряется НАВСЕГДА
    (срок уже сдвинут авансом, повторной попытки в ТОМ ЖЕ окне нет), но следующее окно
    спавнит нормально; форс-брак, взведённый ДО сбоя, не теряется — достаётся следующему
    УСПЕШНОМУ объекту (LS-007: фабрика гасит флаг только после успешной сборки)."""
    factory = _make_factory(tmp_path)
    spawner = ObjectSpawner(factory, interval_s=(0.5, 0.5), scene_length_mm=1_000_000.0)
    rng = np.random.default_rng(106)

    spawner.tick(now_encoder=0.0, now_wall_s=0.0, rng=rng)  # взвод срока = 0.5
    factory.force_defect_next()

    real_make = factory.make
    calls = {"n": 0}

    def _fail_once(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("транзитный сбой каталога")
        return real_make(*args, **kwargs)

    monkeypatch.setattr(factory, "make", _fail_once)

    with pytest.raises(RuntimeError, match="транзитный сбой"):
        spawner.tick(now_encoder=0.0, now_wall_s=0.5, rng=rng)  # окно #1 -- теряется
    assert spawner.active_objects() == []

    spawner.tick(now_encoder=0.0, now_wall_s=1.0, rng=rng)  # окно #2 -- успех
    active = spawner.active_objects()
    assert len(active) == 1
    assert active[0].passport.defect == "damaged"  # форс не потерян -- достался этому объекту
    assert calls["n"] == 2  # окно #1 не ретраилось внутри себя


def test_active_list_ceiling_blocks_new_spawns_then_resumes_after_despawn(tmp_path):
    """[review fix F2, замена отвергнутой энкодерной версии — LS-008] Потолок
    `max_active` не завязан на энкодер: держать энкодер константой между тиками —
    законный способ изолировать таймер (так делают test_acceptance_3_3.py и лидовский
    N4-тест), и версия «блокировать повтор энкодера навсегда» их ломала. `max_active=3`,
    энкодер заморожен на 0.0 — 50 тиков по 0.5с (25с симулированного времени) держат
    РОВНО 3 активных объекта, без исключений; как только деспавн освобождает место (лента
    уехала мимо `scene_length_mm`), спавн на уже просроченном сроке продолжается —
    потолок не «залипает»."""
    factory = _make_factory(tmp_path)
    spawner = ObjectSpawner(factory, interval_s=(0.5, 0.5), scene_length_mm=100.0, max_active=3)
    rng = np.random.default_rng(107)

    spawner.tick(now_encoder=0.0, now_wall_s=0.0, rng=rng)  # взвод срока = 0.5

    now_wall = 0.0
    for _ in range(50):  # 50 тиков по 0.5с = 25с; энкодер заморожен на 0.0
        now_wall += 0.5
        spawner.tick(now_encoder=0.0, now_wall_s=now_wall, rng=rng)
    active = spawner.active_objects()
    assert len(active) == 3  # потолок держит РОВНО 3, не 50, без единого исключения
    first_ids = {o.passport.object_id for o in active}

    # лента проезжает мимо длины сцены -- деспавн освобождает все 3 места, и на том же
    # просроченном сроке (не сдвигался все 25с простоя) спавн происходит сразу же
    now_wall += 0.5
    spawner.tick(now_encoder=700.0, now_wall_s=now_wall, rng=rng)
    active = spawner.active_objects()
    assert len(active) == 1  # все три старых уехали, один новый занял освободившееся место
    assert active[0].passport.object_id not in first_ids

    # и дальше спавнер снова работает штатно на следующем окне -- потолок не «залипает»
    now_wall += 0.5
    spawner.tick(now_encoder=701.0, now_wall_s=now_wall, rng=rng)
    assert len(spawner.active_objects()) == 2


def test_spawner_force_defect_next_delegate_marks_next_object_while_paused(tmp_path):
    """[review fix F3] Вызов ЧЕРЕЗ СПАВНЕР (`spawner.force_defect_next()`, не
    `factory.force_defect_next()` напрямую) — делегат реально подключён: удаление метода
    у `ObjectSpawner` не должно оставлять сьют зелёным (ревью нашло именно это — этот
    хазард закрывает дыру, которую acceptance-тесты тестера не закрывали, так как они
    зовут `factory.force_defect_next()` напрямую)."""
    factory = _make_factory(tmp_path, defect_probability=0.0)
    spawner = ObjectSpawner(factory, interval_s=(0.5, 0.5), scene_length_mm=1_000_000.0)
    rng = np.random.default_rng(108)

    spawner.tick(now_encoder=0.0, now_wall_s=0.0, rng=rng)  # взвод срока = 0.5
    spawner.set_paused(True)
    spawner.force_defect_next()  # ЧЕРЕЗ СПАВНЕР, не через factory
    spawner.tick(now_encoder=0.0, now_wall_s=5.0, rng=rng)  # пауза -- спавна нет
    assert spawner.active_objects() == []

    spawner.set_paused(False)
    spawner.tick(now_encoder=1.0, now_wall_s=5.5, rng=rng)  # первый реальный спавн
    first = spawner.active_objects()
    assert len(first) == 1
    assert first[0].passport.defect == "damaged"

    spawner.tick(now_encoder=2.0, now_wall_s=6.0, rng=rng)  # следующий обычный спавн
    second = spawner.active_objects()
    assert len(second) == 2
    newcomer = next(o for o in second if o.passport.object_id != first[0].passport.object_id)
    assert newcomer.passport.defect is None


def test_interval_jitter_stays_within_bounds_over_200_spawns(tmp_path):
    """Джиттер `rng.uniform(lo, hi)` с lo != hi — каждый интервал между последовательными
    спавнами лежит строго в [lo, hi] (реальный `np.random.default_rng`, не мок). Энкодер
    двигается вместе с временем (fix F2 блокирует повторный спавн на замороженном
    энкодере) — джиттер здесь единственный предмет теста, движение ленты не мешает ему."""
    lo, hi = 0.2, 0.8
    factory = _make_factory(tmp_path)
    spawner = ObjectSpawner(factory, interval_s=(lo, hi), scene_length_mm=1_000_000_000.0)
    rng = np.random.default_rng(103)

    now_wall = 0.0
    now_encoder = 0.0
    spawner.tick(now_encoder=now_encoder, now_wall_s=now_wall, rng=rng)  # взвод

    spawn_times: list[float] = []
    step = 0.01  # мельче нижней границы интервала — не пропустим момент спавна
    prev_count = 0
    while len(spawn_times) < 200:
        now_wall += step
        now_encoder += 1.0  # лента едет -- каждый тик энкодер строго больше предыдущего
        spawner.tick(now_encoder=now_encoder, now_wall_s=now_wall, rng=rng)
        count = len(spawner.active_objects())
        if count > prev_count:
            spawn_times.append(now_wall)
            prev_count = count

    gaps = [b - a for a, b in zip(spawn_times, spawn_times[1:])]
    assert len(gaps) == 199
    # допуск на дискретность шага сканирования (step) сверх точной границы rng.uniform
    for gap in gaps:
        assert lo - step <= gap <= hi + step, gap


def test_despawn_uses_each_objects_own_spawn_encoder(tmp_path):
    """Два объекта, заспавненные на РАЗНЫХ энкодерах, уезжают со сцены в РАЗНОЕ время —
    деспавн считает смещение от `passport.spawn_encoder` каждого объекта, не от общего
    начала отсчёта спавнера."""
    factory = _make_factory(tmp_path)
    spawner = ObjectSpawner(factory, interval_s=(1.0, 1.0), scene_length_mm=100.0)
    rng = np.random.default_rng(104)

    spawner.tick(now_encoder=0.0, now_wall_s=0.0, rng=rng)  # взвод
    spawner.tick(now_encoder=0.0, now_wall_s=1.0, rng=rng)  # spawn A: spawn_encoder=0.0
    spawner.tick(now_encoder=500.0, now_wall_s=2.0, rng=rng)  # spawn B: spawn_encoder=500.0
    assert len(spawner.active_objects()) == 2

    # 693 * FACTOR_MM (0.144473) = 100.119789 > 100 -> A (spawn_encoder=0) уехал,
    # B (spawn_encoder=500) на энкодере 693 прошёл только 193 тика от своего спавна
    # (193 * 0.144473 = 27.883 мм) — всё ещё на сцене.
    spawner.tick(now_encoder=693.0, now_wall_s=2.1, rng=rng)
    remaining = spawner.active_objects()
    assert len(remaining) == 1
    assert remaining[0].passport.spawn_encoder == 500.0


def test_object_exactly_at_scene_end_is_still_active(tmp_path):
    """[lead 3.3, break-injection N1] граница «строго больше» не была закреплена: тест
    приёмки брал значения около границы, и замена `<=` на `<` выживала. Здесь смещение
    РОВНО равно длине сцены — объект обязан остаться на сцене."""
    factory = _make_factory(tmp_path)
    ticks = 700
    scene_len = ticks * FACTOR_MM  # точное равенство достижимо: спавн на энкодере 0
    spawner = ObjectSpawner(factory=factory, interval_s=(0.5, 0.5), scene_length_mm=scene_len)
    rng = np.random.default_rng(0)
    spawner.tick(now_encoder=0.0, now_wall_s=0.0, rng=rng)
    spawner.tick(now_encoder=0.0, now_wall_s=0.5, rng=rng)
    assert len(spawner.active_objects()) == 1
    assert spawner.active_objects()[0].passport.spawn_encoder == 0.0

    spawner.set_paused(True)
    spawner.tick(now_encoder=float(ticks), now_wall_s=1.0, rng=rng)
    assert encoder_to_offset_mm(float(ticks), 0.0) == scene_len
    assert len(spawner.active_objects()) == 1, "смещение РОВНО в край сцены — объект ещё на сцене"

    spawner.tick(now_encoder=float(ticks + 1), now_wall_s=1.5, rng=rng)
    assert spawner.active_objects() == []


def test_long_gap_does_not_leave_a_backlog_of_deadlines(tmp_path):
    """[lead 3.3, break-injection N4] «не догоняем пропущенные интервалы» проверялось только
    по числу объектов в тике после паузы: `deadline += interval` выживало. Здесь важно, что
    ПОСЛЕ спавна на просроченном сроке следующий объект ждёт полный интервал от текущего
    времени, а не выпадает пачкой на ближайших тиках."""
    factory = _make_factory(tmp_path)
    spawner = ObjectSpawner(factory=factory, interval_s=(0.5, 0.5), scene_length_mm=10_000.0)
    rng = np.random.default_rng(0)
    spawner.tick(now_encoder=0.0, now_wall_s=0.0, rng=rng)
    spawner.tick(now_encoder=0.0, now_wall_s=10.0, rng=rng)
    assert len(spawner.active_objects()) == 1

    for step in (10.05, 10.1, 10.2, 10.3, 10.4):
        spawner.tick(now_encoder=0.0, now_wall_s=step, rng=rng)
    assert len(spawner.active_objects()) == 1, "долг по пропущенным интервалам не копится"

    spawner.tick(now_encoder=0.0, now_wall_s=10.5, rng=rng)
    assert len(spawner.active_objects()) == 2


def test_ceiling_does_not_move_the_deadline(tmp_path):
    """[lead 3.3, break-injection O4] «упёрлись в потолок — срок не трогаем» выживало: тест
    потолка проверял только число активных. Здесь важно, что после освобождения места объект
    появляется на БЛИЖАЙШЕМ тике (срок давно просрочен), а не через полный интервал."""
    factory = _make_factory(tmp_path)
    spawner = ObjectSpawner(factory=factory, interval_s=(0.5, 0.5), scene_length_mm=100.0, max_active=1)
    rng = np.random.default_rng(0)
    spawner.tick(now_encoder=0.0, now_wall_s=0.0, rng=rng)
    spawner.tick(now_encoder=0.0, now_wall_s=0.5, rng=rng)
    assert len(spawner.active_objects()) == 1

    # Потолок упёрт: пять тиков подряд, все просрочены — ни одного нового объекта.
    for step in (1.0, 1.5, 2.0, 2.5, 3.0):
        spawner.tick(now_encoder=0.0, now_wall_s=step, rng=rng)
    assert len(spawner.active_objects()) == 1

    # Освобождаем место (объект уехал за сцену) и тикаем РОВНО один раз, не дожидаясь
    # нового интервала: срок просрочен с 1.0, значит объект обязан появиться сразу.
    far = 1000.0
    spawner.tick(now_encoder=far, now_wall_s=3.01, rng=rng)
    active = spawner.active_objects()
    assert len(active) == 1, "срок остался просроченным — спавн сразу после освобождения места"
    assert active[0].passport.spawn_encoder == far


def test_constructor_rejects_nonpositive_max_active(tmp_path):
    """[lead 3.3, break-injection O5] проверка потолка не была закреплена ничем."""
    factory = _make_factory(tmp_path)
    for bad in (0, -1):
        with pytest.raises(ValueError, match="max_active"):
            ObjectSpawner(factory=factory, interval_s=(0.5, 0.5), scene_length_mm=100.0, max_active=bad)
