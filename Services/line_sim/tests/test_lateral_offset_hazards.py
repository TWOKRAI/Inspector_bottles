# -*- coding: utf-8 -*-
"""Hazard-тесты автора `sim-lateral-offset` Task 1.1 — внутренние места механизма, видимые только автору.

Независимая приёмка (`test_acceptance_lateral_offset.py`) проверяет контракт снаружи; здесь —
что может сломаться именно в ЭТОМ механизме, как он устроен: розыгрыш в `ObjectSpawner._make`
ПОСЛЕ `factory.make()`, ветка «диапазон (0, 0) rng не трогает», две точки вызова `_make`
(режимы `interval_s` и `spacing_mm`), `replace()` паспорта на объекте, который уже собрала фабрика.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import pytest

from Services.dataset_gen.core.catalog import imwrite_unicode
from Services.line_sim import ObjectFactory, ObjectSpawner, ScenePreset
from Services.line_sim.core.matching import BeltGeometry, object_robot_xy
from Services.line_sim.core.spawner import validate_lateral_offset_px
from Services.line_sim.interfaces import ObjectPassport


def _factory(tmp_path: Path) -> ObjectFactory:
    """Два класса и случайный угол: каждая сборка тянет из rng (класс, угол), лишний розыгрыш виден."""
    for name in ("a", "b"):
        d = tmp_path / "catalog" / name
        d.mkdir(parents=True)
        sprite = np.zeros((16, 16, 4), dtype=np.uint8)
        sprite[:, :, :3] = 128
        sprite[:, :, 3] = 255
        imwrite_unicode(d / "sprite.png", sprite)
    preset = tmp_path / "preset.yaml"
    preset.write_text(
        "catalog_dir: catalog\nangle_range_deg: [0.0, 360.0]\nlayers: []\ndefect_probability: 0.0\n",
        encoding="utf-8",
    )
    return ObjectFactory(ScenePreset.from_yaml(preset))


def _spawner(tmp_path: Path, **kwargs) -> ObjectSpawner:
    return ObjectSpawner(_factory(tmp_path), spacing_mm=(1.0, 1.0), scene_length_mm=1e9, **kwargs)


def _spawn(spawner: ObjectSpawner, rng: np.random.Generator, n: int) -> list:
    enc = 0.0
    for _ in range(n):
        enc += 100.0
        spawner.tick(now_encoder=enc, now_wall_s=0.0, rng=rng)
    return spawner.active_objects()


def test_factory_draws_unchanged_by_nonzero_range(tmp_path: Path) -> None:
    """Что ломается: розыгрыш смещения встал бы ДО `factory.make()` (или между его розыгрышами) —
    класс/угол первого объекта поплыли бы относительно прогона без ключа при том же seed.
    Здесь сверяется ПЕРВЫЙ объект: после него rng уже разошёлся (смещение тянет свои числа), а
    первая сборка обязана видеть тот же поток, что и без ключа."""
    plain = _spawn(_spawner(tmp_path / "p"), np.random.default_rng(21), 1)[0].passport
    shifted_sp = _spawner(tmp_path / "s", lateral_offset_px=(10.0, 20.0))
    shifted = _spawn(shifted_sp, np.random.default_rng(21), 1)[0].passport
    assert (shifted.class_name, shifted.angle_deg) == (plain.class_name, plain.angle_deg)
    assert plain.lateral_px == 0.0
    assert 10.0 <= abs(shifted.lateral_px) <= 20.0


def test_zero_range_keeps_the_whole_rng_stream_in_interval_mode_too(tmp_path: Path) -> None:
    """Что ломается: ветка «(0, 0) -> rng не трогать» покрыта приёмкой только в режиме `spacing_mm`;
    у режима `interval_s` своя точка вызова `_make`. Забытая ветка там тянула бы число на каждый
    спавн и сдвигала поток. Ожидание считается НЕ из кода спавнера: фабрика-заглушка не берёт rng,
    значит единственные розыгрыши — срок (`uniform(1, 1)`) на первом тике и после каждого спавна;
    поток обязан совпасть с ручным повтором ровно этого числа розыгрышей. (Сравнение двух прогонов
    спавнера между собой не годится — сломанная ветка ломала бы оба одинаково.)"""
    passport = ObjectPassport(object_id="o", class_name="c", angle_deg=0.0, defect=None, spawn_encoder=0.0)
    factory = SimpleNamespace(
        force_defect_pending=False,
        make=lambda object_id, spawn_encoder, rng: SimpleNamespace(passport=passport),
    )
    rng = np.random.default_rng(5)
    sp = ObjectSpawner(factory, interval_s=(1.0, 1.0), scene_length_mm=1e9, lateral_offset_px=(0.0, 0.0))  # type: ignore[arg-type]
    wall = 0.0
    for _ in range(8):
        wall += 1.5
        sp.tick(now_encoder=0.0, now_wall_s=wall, rng=rng)
    spawned = len(sp.active_objects())
    assert spawned >= 5
    replay = np.random.default_rng(5)
    for _ in range(1 + spawned):  # срок на первом тике + по одному после каждого спавна
        replay.uniform(1.0, 1.0)
    assert rng.bit_generator.state == replay.bit_generator.state


def test_interval_mode_also_samples_lateral(tmp_path: Path) -> None:
    """Что ломается: смещение проставлено только в одной из двух точек спавна — в режиме
    `interval_s` объекты остались бы по центру при заданном диапазоне."""
    rng = np.random.default_rng(6)
    sp = ObjectSpawner(_factory(tmp_path), interval_s=(1.0, 1.0), scene_length_mm=1e9, lateral_offset_px=(10.0, 20.0))
    wall = 0.0
    for _ in range(10):
        wall += 1.5
        sp.tick(now_encoder=0.0, now_wall_s=wall, rng=rng)
    objs = sp.active_objects()
    assert len(objs) >= 5
    assert all(10.0 <= abs(o.passport.lateral_px) <= 20.0 for o in objs)


def test_set_factory_keeps_lateral_sampling(tmp_path: Path) -> None:
    """Что ломается: смещение жило бы в фабрике (или сбрасывалось в `set_factory`) — после
    `preset.commit` новые диски вернулись бы на центр ленты, а объекты ДО подмены остались бы
    смещёнными: на стенде это выглядело бы как «смещение пропало после правки пресета»."""
    sp = _spawner(tmp_path / "one", lateral_offset_px=(10.0, 20.0))
    rng = np.random.default_rng(9)
    before = _spawn(sp, rng, 5)
    sp.set_factory(_factory(tmp_path / "two"))
    enc = 100.0 * 5
    for _ in range(10):
        enc += 100.0
        sp.tick(now_encoder=enc, now_wall_s=0.0, rng=rng)
    after = sp.active_objects()[len(before) :]
    assert len(after) == 10
    assert all(10.0 <= abs(o.passport.lateral_px) <= 20.0 for o in after)
    assert all(10.0 <= abs(o.passport.lateral_px) <= 20.0 for o in before)


class _ZeroMagnitudeNegativeSign:
    """rng-обёртка: смещение даёт магнитуду 0.0 и знак «минус»; всё прочее — настоящий генератор."""

    def __init__(self) -> None:
        self._real = np.random.default_rng(0)

    def uniform(self, lo, hi, *a, **k):
        return 0.0 if (lo, hi) == (0.0, 5.0) else self._real.uniform(lo, hi, *a, **k)

    def random(self, *a, **k):
        return 0.9  # >= 0.5 -> знак минус

    def __getattr__(self, name):
        return getattr(self._real, name)


def test_negative_sign_with_zero_magnitude_is_not_negative_zero() -> None:
    """Что ломается: `sign * 0.0` при знаке «минус» даёт `-0.0` — `==` его не отличает от `0.0`
    (тесты с `==` зелёные), но `copysign`/`signbit` и JSON (`-0.0`) видят разницу, а паспорт
    `sim.objects` уходит в замер именно как JSON. Реальный `rng.uniform` вернёт ровно 0.0 почти
    никогда, поэтому магнитуда подставлена обёрткой."""
    passport = ObjectPassport(object_id="o", class_name="c", angle_deg=0.0, defect=None, spawn_encoder=0.0)
    factory = SimpleNamespace(
        force_defect_pending=False,
        make=lambda object_id, spawn_encoder, rng: SimpleNamespace(passport=passport),
    )
    sp = ObjectSpawner(factory, spacing_mm=(1.0, 1.0), scene_length_mm=1e9, lateral_offset_px=(0.0, 5.0))  # type: ignore[arg-type]
    sp.tick(now_encoder=100.0, now_wall_s=0.0, rng=_ZeroMagnitudeNegativeSign())  # type: ignore[arg-type]
    value = sp.active_objects()[0].passport.lateral_px
    assert value == 0.0
    assert not np.signbit(value), "найден -0.0"


@pytest.mark.parametrize("kwargs", [{"frame_down_ux": -1.0}, {"frame_down_uy": 0.0}])
def test_partial_frame_down_is_value_error(kwargs) -> None:
    """Что ломается: одна компонента вектора `frame_down` без второй молча считалась бы нулём
    (или None -> TypeError только при первом задании с поперечным слагаемым, в рабочем потоке
    сцены). Обязана падать сразу при построении, и в конструкторе, и на dict-границе."""
    with pytest.raises(ValueError, match="frame_down"):
        BeltGeometry(origin_x_mm=0.0, origin_y_mm=0.0, **kwargs)
    with pytest.raises(ValueError, match="frame_down"):
        BeltGeometry.from_dict({"origin_x_mm": 0.0, "origin_y_mm": 0.0, **kwargs})


def test_frame_down_absent_roundtrips_without_new_keys() -> None:
    """Что ломается: `to_dict` писал бы `frame_down_*: None` — старый потребитель словаря
    (и `from_dict` со строгим `float()`) получил бы `None` там, где раньше ключа не было."""
    g = BeltGeometry(origin_x_mm=1.0, origin_y_mm=2.0)
    assert g.to_dict() == {"origin_x_mm": 1.0, "origin_y_mm": 2.0}
    assert BeltGeometry.from_dict(g.to_dict()) == g


def test_lateral_without_frame_down_or_px_per_mm_is_value_error() -> None:
    """Что ломается: `object_robot_xy` молча игнорировал бы смещение (истина врёт про позицию на
    `lateral_px / px_per_mm` мм) — прямой вызов в обход проверки плагина обязан падать."""
    bare = BeltGeometry()
    down = BeltGeometry(frame_down_ux=-1.0, frame_down_uy=0.0)
    with pytest.raises(ValueError, match="lateral_px"):
        object_robot_xy(0.0, 0.0, bare, lateral_px=5.0, px_per_mm=8.0)
    with pytest.raises(ValueError, match="lateral_px"):
        object_robot_xy(0.0, 0.0, down, lateral_px=5.0)
    # нулевое смещение — прежний результат без frame_down/px_per_mm
    assert object_robot_xy(0.0, 0.0, bare) == (0.0, 0.0)


def test_validator_rejects_bool_and_accepts_tuple_and_list() -> None:
    """Что ломается: `bool` — подкласс `int`, `[True, 5]` прошло бы как `[1, 5]`; а тип контейнера
    (YAML даёт list, код — tuple) не должен влиять на результат."""
    with pytest.raises(ValueError, match="lateral_offset_px"):
        validate_lateral_offset_px([True, 5])
    assert validate_lateral_offset_px([10, 20]) == validate_lateral_offset_px((10.0, 20.0)) == (10.0, 20.0)


_NAN = float("nan")
_INF = float("inf")
_BAD_FRAME_DOWN = [
    pytest.param((0.0, 0.0), id="zero-vector"),
    pytest.param((-78.4, 0.0), id="not-unit-mm-length"),
    pytest.param((_NAN, 0.0), id="nan"),
    pytest.param((_INF, 0.0), id="inf"),
]


@pytest.mark.parametrize("ux_uy", _BAD_FRAME_DOWN)
def test_non_unit_frame_down_is_value_error(ux_uy) -> None:
    """Что ломается: проверка «парой» пропускала любой вектор. Измерено на 97dcfed0 при
    `object_robot_xy(0, 0, g, lateral_px=20, px_per_mm=8.163265)`, origin_x 458.2: (0, 0) -> X=458.2
    (поперечное слагаемое молча ноль), (-78.4, 0) -> X=266.12 вместо 455.75 (промах 190 мм),
    (nan, 0) -> (nan, 0.0). Обязана падать сразу и в конструкторе, и на dict-границе; текст
    называет `frame_down_ux`/`frame_down_uy`."""
    ux, uy = ux_uy
    with pytest.raises(ValueError, match="frame_down_ux.*frame_down_uy"):
        BeltGeometry(origin_x_mm=458.2, origin_y_mm=0.0, frame_down_ux=ux, frame_down_uy=uy)
    with pytest.raises(ValueError, match="frame_down_ux.*frame_down_uy"):
        BeltGeometry.from_dict({"origin_x_mm": 458.2, "origin_y_mm": 0.0, "frame_down_ux": ux, "frame_down_uy": uy})


@pytest.mark.parametrize("ux_uy", [(-1.0, 0.0), (0.6, 0.8)])
def test_unit_frame_down_is_accepted_and_applied(ux_uy) -> None:
    """Что ломается: проверка длины отвергла бы рабочий вектор стенда (-1, 0) или косой единичный
    (0.6, 0.8). Литерал: 20 px / 8.0 px/мм = 2.5 мм вдоль вектора."""
    ux, uy = ux_uy
    g = BeltGeometry(origin_x_mm=100.0, origin_y_mm=200.0, frame_down_ux=ux, frame_down_uy=uy)
    assert BeltGeometry.from_dict(g.to_dict()) == g
    x, y = object_robot_xy(0.0, 0.0, g, lateral_px=20.0, px_per_mm=8.0)
    assert (x, y) == pytest.approx((100.0 + 2.5 * ux, 200.0 + 2.5 * uy))


@pytest.mark.parametrize("ux_uy", _BAD_FRAME_DOWN)
def test_plugin_configure_rejects_bad_frame_down(ux_uy) -> None:
    """Что ломается: плагин собирал `BeltGeometry.from_dict` без проверки — кривой вектор при
    `lateral_offset_px > 0` стартовал бы, а истина робота молча врала. ValueError обязан вылететь
    из `configure`, не из `produce()`. Конфиг минимален: проверка геометрии идёт раньше сборки движка."""
    from Plugins.sim.scene_source.plugin import SceneSourcePlugin

    ux, uy = ux_uy
    ctx = MagicMock()
    ctx.config = {
        "resolution_width": 320,
        "resolution_height": 240,
        "px_per_mm": 8.163265,
        "belt_y_px": 120,
        "lateral_offset_px": [10.0, 20.0],
        "geometry": {"origin_x_mm": 458.2, "origin_y_mm": 0.0, "frame_down_ux": ux, "frame_down_uy": uy},
    }
    with pytest.raises(ValueError, match="frame_down_ux.*frame_down_uy"):
        SceneSourcePlugin().configure(ctx)  # type: ignore[arg-type]
