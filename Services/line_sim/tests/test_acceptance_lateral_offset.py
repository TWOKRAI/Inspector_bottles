# -*- coding: utf-8 -*-
"""Независимая приёмка `sim-lateral-offset` Task 1.1 — ядро line_sim (слепой тестер, ДО реализации).

Контракт — таблица и Acceptance criteria `plans/sim-lateral-offset.md`, НЕ код реализации.
Ожидаемые числа — литералы из плана (±16.33 пикс, 8.163265 пикс/мм, frame_down=(-1, 0), диапазон
[10, 20]); ничто не выводится из тестируемого кода.

ДОГАДКА ТЕСТЕРА (единственная, изолирована в `_make_spawner`): ядро-спавнер принимает диапазон
смещения kwarg'ом `lateral_offset_px=(lo, hi)` — по имени ключа конфига `scene_source`; контракт
сигнатуру спавнера не фиксирует. Другое имя — правка ОДНОЙ функции `_make_spawner`. Тесты
спавнера, которые её зовут, помечены в докстринге «(ДОГАДКА kwarg)»; всё остальное идёт через
паспорт, компоновщик (фейк-спавнер) и публичные dataclass'ы, а `object_robot_xy` — через плагин
(`Plugins/sim/scene_source/tests/test_acceptance_lateral_offset_plugin.py`).

Ожидаемая форма RED сегодня: AttributeError (`lateral_px`, `frame_down_ux`), TypeError
(`lateral_px=` / `lateral_offset_px=` в конструкторе) — символов ещё нет. GREEN-контроли (должны
быть зелёными и до, и после) помечены `[GREEN-контроль]`.
"""

from __future__ import annotations

import threading
from pathlib import Path

import cv2
import numpy as np
import pytest
import yaml

from Services.dataset_gen.core.catalog import imwrite_unicode
from Services.line_sim import ObjectFactory, ObjectSpawner, ScenePreset
from Services.line_sim.core.belt import FACTOR_MM
from Services.line_sim.core.matching import BeltGeometry
from Services.line_sim.core.scene_compositor import SceneCompositor
from Services.line_sim.interfaces import ObjectPassport

_DEADLINE_S = 60.0


def _run_with_deadline(fn, deadline_s: float = _DEADLINE_S):
    """Выполнить `fn` в daemon-потоке с join-дедлайном: зависание = падение теста, не подвисание сьюта."""
    box: dict = {}

    def target() -> None:
        try:
            box["value"] = fn()
        except BaseException as exc:  # noqa: BLE001 — пробросить в основной поток как есть
            box["exc"] = exc

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    thread.join(deadline_s)
    assert not thread.is_alive(), f"вызов завис дольше {deadline_s} с"
    if "exc" in box:
        raise box["exc"]
    return box["value"]


# --------------------------------------------------------------------------- #
# Паспорт                                                                     #
# --------------------------------------------------------------------------- #


def _passport(**extra) -> ObjectPassport:
    return ObjectPassport(
        object_id="obj-1", class_name="disk", angle_deg=0.0, defect=None, spawn_encoder=100.0, **extra
    )


def test_passport_lateral_px_defaults_to_zero() -> None:
    """Паспорт без явного смещения: `lateral_px == 0.0` (float)."""
    p = _passport()
    assert p.lateral_px == 0.0
    assert isinstance(p.lateral_px, float)


def test_passport_to_dict_carries_signed_lateral_px() -> None:
    """`to_dict()` несёт знаковое `lateral_px` как есть (−12.5 остаётся −12.5, не модуль)."""
    d = _passport(lateral_px=-12.5).to_dict()
    assert d["lateral_px"] == -12.5
    assert isinstance(d["lateral_px"], float)


def test_passport_dict_roundtrip_keeps_lateral_px() -> None:
    """`from_dict(to_dict())` возвращает тот же паспорт, включая смещение +17.25."""
    p = _passport(lateral_px=17.25)
    back = ObjectPassport.from_dict(p.to_dict())
    assert back.lateral_px == 17.25
    assert back == p


def test_old_passport_dict_without_lateral_px_reads_as_zero() -> None:
    """Старый словарь (до задачи) без ключа `lateral_px` читается, `lateral_px == 0.0`."""
    old = {
        "object_id": "obj-9",
        "class_name": "disk",
        "angle_deg": 30.0,
        "defect": None,
        "spawn_encoder": 5.0,
        "layer_params": {},
    }
    p = ObjectPassport.from_dict(old)
    assert p.lateral_px == 0.0
    assert p.object_id == "obj-9"


def test_old_passport_dict_without_lateral_px_still_loads_other_fields() -> None:
    """[GREEN-контроль] Старый словарь без нового ключа не ломает `from_dict` — прочие поля на месте."""
    old = {
        "object_id": "obj-9",
        "class_name": "disk",
        "angle_deg": 30.0,
        "defect": "scratch",
        "spawn_encoder": 5.0,
        "layer_params": {"a": {"active": True}},
    }
    p = ObjectPassport.from_dict(old)
    assert (p.class_name, p.angle_deg, p.defect, p.spawn_encoder) == ("disk", 30.0, "scratch", 5.0)
    assert p.layer_params == {"a": {"active": True}}


# --------------------------------------------------------------------------- #
# BeltGeometry.frame_down                                                     #
# --------------------------------------------------------------------------- #


def test_beltgeometry_reads_frame_down_from_dict() -> None:
    """`geometry` с `frame_down_ux/uy` отдаёт их атрибутами (−1.0, 0.0)."""
    g = BeltGeometry.from_dict({"origin_x_mm": 100.0, "origin_y_mm": 200.0, "frame_down_ux": -1, "frame_down_uy": 0})
    assert g.frame_down_ux == -1.0
    assert g.frame_down_uy == 0.0
    assert g.origin_x_mm == 100.0
    assert g.origin_y_mm == 200.0


def test_beltgeometry_frame_down_survives_dict_roundtrip() -> None:
    """`from_dict(to_dict())` сохраняет `frame_down` (иначе поперечное слагаемое теряется на границе процесса)."""
    g = BeltGeometry.from_dict({"origin_x_mm": 1.0, "origin_y_mm": 2.0, "frame_down_ux": 0.0, "frame_down_uy": 1.0})
    back = BeltGeometry.from_dict(g.to_dict())
    assert (back.frame_down_ux, back.frame_down_uy) == (0.0, 1.0)
    assert back == g


def test_beltgeometry_without_frame_down_still_loads() -> None:
    """[GREEN-контроль] Старый `geometry` (только origin) читается без ошибки."""
    g = BeltGeometry.from_dict({"origin_x_mm": 3.0, "origin_y_mm": 4.0})
    assert (g.origin_x_mm, g.origin_y_mm) == (3.0, 4.0)


# --------------------------------------------------------------------------- #
# Компоновщик: cy = belt_y_px + lateral_px - y_px                             #
# --------------------------------------------------------------------------- #

_SPRITE = 25  # нечётный размер: центр масс маски = центр спрайта точно


class _FakeObject:
    """Утиный объект для компоновщика: ему нужны только `.passport` и `.render()`."""

    def __init__(self, passport: ObjectPassport) -> None:
        self.passport = passport
        rgba = np.zeros((_SPRITE, _SPRITE, 4), dtype=np.uint8)
        rgba[:, :, 0] = 255  # R
        rgba[:, :, 3] = 255
        self._rgba = rgba

    def render(self) -> np.ndarray:
        return self._rgba


class _FakeSpawner:
    def __init__(self, objects: list[_FakeObject]) -> None:
        self._objects = objects

    def active_objects(self) -> list[_FakeObject]:
        return list(self._objects)


def _render_single(lateral_px: float, *, belt_y_px: float = 100.0, belt_direction: int = 1) -> tuple[float, float]:
    """Кадр 200x200, один красный спрайт 25x25; вернуть центр масс красных пикселей (cx, cy).

    Энкодер подобран так, что путь вдоль ленты = 100 мм при px_per_mm=1 -> cx ≈ 100 (вход слева)."""
    now_encoder = 100.0 + 100.0 / FACTOR_MM  # spawn_encoder паспорта = 100.0
    passport = _passport(**({} if lateral_px == 0.0 else {"lateral_px": lateral_px}))
    comp = SceneCompositor(
        _FakeSpawner([_FakeObject(passport)]),
        px_per_mm=1.0,
        belt_y_px=belt_y_px,
        background_bgr=(60, 60, 60),
        belt_direction=belt_direction,
        entry_x_px=0.0 if belt_direction == 1 else 200.0,
    )
    frame, passports = comp.render(now_encoder, (0.0, 0.0, 200.0, 200.0))
    assert len(passports) == 1, "объект целиком в кадре — паспорт должен вернуться"
    mask = (frame[:, :, 0] == 255) & (frame[:, :, 1] == 0) & (frame[:, :, 2] == 0)
    ys, xs = np.nonzero(mask)
    assert ys.size > 0, "красный спрайт не найден в кадре"
    return float(xs.mean()), float(ys.mean())


def test_compositor_without_lateral_centres_on_belt_y() -> None:
    """[GREEN-контроль] Объект без смещения стоит на `belt_y_px = 100` (±1 px), cx ≈ 100."""
    cx, cy = _render_single(0.0)
    assert cy == pytest.approx(100.0, abs=1.0)
    assert cx == pytest.approx(100.0, abs=1.0)


def test_compositor_positive_lateral_moves_sprite_down_the_frame() -> None:
    """`lateral_px=+16` -> центр спрайта по Y = 100 + 16 = 116 (вниз по кадру, ±1 px)."""
    _cx, cy = _render_single(16.0)
    assert cy == pytest.approx(116.0, abs=1.0)


def test_compositor_negative_lateral_moves_sprite_up_the_frame() -> None:
    """`lateral_px=-16` -> центр спрайта по Y = 100 − 16 = 84 (вверх по кадру, ±1 px)."""
    _cx, cy = _render_single(-16.0)
    assert cy == pytest.approx(84.0, abs=1.0)


def test_compositor_lateral_does_not_touch_x() -> None:
    """Поперечное смещение не двигает спрайт по X: cx при `lateral_px=+16` равен cx без смещения (±0.5)."""
    cx0, _ = _render_single(0.0)
    cx16, _ = _render_single(16.0)
    assert cx16 == pytest.approx(cx0, abs=0.5)


def test_compositor_lateral_added_to_belt_y_not_replacing_it() -> None:
    """При `belt_y_px = 60` и `lateral_px=+20` центр = 80 (а не 20 и не 60) — слагаемое, а не замена."""
    _cx, cy = _render_single(20.0, belt_y_px=60.0)
    assert cy == pytest.approx(80.0, abs=1.0)


def test_compositor_lateral_with_reversed_belt_direction_still_vertical() -> None:
    """При `belt_direction=-1` смещение всё равно вертикально: `lateral_px=+16` -> cy = 116 (±1)."""
    _cx, cy = _render_single(16.0, belt_direction=-1)
    assert cy == pytest.approx(116.0, abs=1.0)


# --------------------------------------------------------------------------- #
# Спавнер: розыгрыш модуля и знака                                            #
# --------------------------------------------------------------------------- #


def _make_factory(tmp_path: Path) -> ObjectFactory:
    class_dir = tmp_path / "catalog" / "only_class"
    class_dir.mkdir(parents=True)
    sprite = np.zeros((16, 16, 4), dtype=np.uint8)
    sprite[:, :, :3] = 128
    sprite[:, :, 3] = 255
    imwrite_unicode(class_dir / "sprite.png", cv2.cvtColor(sprite, cv2.COLOR_RGBA2BGRA))
    preset_path = tmp_path / "preset.yaml"
    preset_path.write_text(
        yaml.safe_dump(
            {"catalog_dir": "catalog", "layers": [], "defect_probability": 0.0}, allow_unicode=True, sort_keys=False
        ),
        encoding="utf-8",
    )
    return ObjectFactory(ScenePreset.from_yaml(preset_path))


def _make_spawner(tmp_path: Path, lateral_offset_px: tuple[float, float] | None) -> ObjectSpawner:
    """ЕДИНСТВЕННАЯ ДОГАДКА ТЕСТЕРА: kwarg `lateral_offset_px=(lo, hi)` у `ObjectSpawner`.

    `None` — kwarg не передаётся вовсе (поведение «ключа нет»)."""
    kwargs = {} if lateral_offset_px is None else {"lateral_offset_px": lateral_offset_px}
    return ObjectSpawner(_make_factory(tmp_path), spacing_mm=(1.0, 1.0), scene_length_mm=1e9, max_active=200, **kwargs)


def _spawn_n(spawner: ObjectSpawner, rng: np.random.Generator, n: int) -> list:
    """Тикать лентой (+100 счётов = 14.4 мм > шага 1 мм): один спавн за тик, ровно n объектов."""
    enc = 0.0
    for _ in range(n):
        enc += 100.0
        spawner.tick(now_encoder=enc, now_wall_s=0.0, rng=rng)
    objs = spawner.active_objects()
    assert len(objs) == n
    return objs


def test_spawner_lateral_magnitude_in_range_for_200_objects(tmp_path: Path) -> None:
    """(ДОГАДКА kwarg) С `[10, 20]`: у каждого из 200 объектов `10 <= |lateral_px| <= 20`."""
    spawner = _make_spawner(tmp_path, (10.0, 20.0))
    objs = _run_with_deadline(lambda: _spawn_n(spawner, np.random.default_rng(1), 200))
    mags = [abs(o.passport.lateral_px) for o in objs]
    assert min(mags) >= 10.0, f"минимум модуля {min(mags)} < 10"
    assert max(mags) <= 20.0, f"максимум модуля {max(mags)} > 20"


def test_spawner_lateral_sign_takes_both_values_over_200_objects(tmp_path: Path) -> None:
    """(ДОГАДКА kwarg) На 200 объектах встречаются И плюс, И минус — знак случаен, не залип."""
    spawner = _make_spawner(tmp_path, (10.0, 20.0))
    objs = _run_with_deadline(lambda: _spawn_n(spawner, np.random.default_rng(2), 200))
    signs = {float(np.sign(o.passport.lateral_px)) for o in objs}
    assert signs == {-1.0, 1.0}, f"встретились знаки {signs}"


def test_spawner_lateral_sign_is_roughly_balanced(tmp_path: Path) -> None:
    """(ДОГАДКА kwarg) Знак ±1 равновероятен: плюсов среди 200 от 70 до 130 (вероятность выхода ≈ 1e-5)."""
    spawner = _make_spawner(tmp_path, (10.0, 20.0))
    objs = _run_with_deadline(lambda: _spawn_n(spawner, np.random.default_rng(3), 200))
    positives = sum(1 for o in objs if o.passport.lateral_px > 0)
    assert 70 <= positives <= 130, f"плюсов {positives} из 200"


def test_spawner_lateral_magnitude_is_spread_not_constant(tmp_path: Path) -> None:
    """(ДОГАДКА kwarg) Модуль случаен внутри диапазона: на 200 объектах разброс по модулю больше 5 пикс."""
    spawner = _make_spawner(tmp_path, (10.0, 20.0))
    objs = _run_with_deadline(lambda: _spawn_n(spawner, np.random.default_rng(4), 200))
    mags = [abs(o.passport.lateral_px) for o in objs]
    assert max(mags) - min(mags) > 5.0


def test_spawner_degenerate_range_gives_exact_magnitude(tmp_path: Path) -> None:
    """(ДОГАДКА kwarg) Граница `lo == hi == 15`: модуль ровно 15.0 у всех, знак всё ещё случаен."""
    spawner = _make_spawner(tmp_path, (15.0, 15.0))
    objs = _run_with_deadline(lambda: _spawn_n(spawner, np.random.default_rng(5), 60))
    assert {abs(o.passport.lateral_px) for o in objs} == {15.0}
    assert {float(np.sign(o.passport.lateral_px)) for o in objs} == {-1.0, 1.0}


def test_spawner_range_from_zero_stays_within_bounds(tmp_path: Path) -> None:
    """(ДОГАДКА kwarg) Нижняя граница `lo = 0` допустима: `[0, 5]` даёт `|lateral_px| <= 5`, и не всё нули."""
    spawner = _make_spawner(tmp_path, (0.0, 5.0))
    objs = _run_with_deadline(lambda: _spawn_n(spawner, np.random.default_rng(6), 100))
    mags = [abs(o.passport.lateral_px) for o in objs]
    assert max(mags) <= 5.0
    assert max(mags) > 0.0


def test_spawner_without_key_gives_zero_lateral(tmp_path: Path) -> None:
    """Без ключа (дефолт ядра `[0, 0]`) у каждого объекта `lateral_px == 0.0`."""
    spawner = _make_spawner(tmp_path, None)
    objs = _run_with_deadline(lambda: _spawn_n(spawner, np.random.default_rng(7), 30))
    assert [o.passport.lateral_px for o in objs] == [0.0] * 30


def test_spawner_explicit_zero_range_gives_zero_lateral(tmp_path: Path) -> None:
    """(ДОГАДКА kwarg) Явный `[0, 0]` — смещения нет, `lateral_px == 0.0` у всех (и не `-0.0` от знака)."""
    spawner = _make_spawner(tmp_path, (0.0, 0.0))
    objs = _run_with_deadline(lambda: _spawn_n(spawner, np.random.default_rng(8), 30))
    assert [o.passport.lateral_px for o in objs] == [0.0] * 30
    assert not any(np.signbit(o.passport.lateral_px) for o in objs), "найден -0.0"


def test_spawner_explicit_zero_range_does_not_consume_rng(tmp_path: Path) -> None:
    """(ДОГАДКА kwarg) `[0, 0]` не трогает rng: состояние генератора после 40 спавнов такое же, как без ключа."""
    rng_default = np.random.default_rng(11)
    rng_zero = np.random.default_rng(11)
    _run_with_deadline(lambda: _spawn_n(_make_spawner(tmp_path / "a", None), rng_default, 40))
    _run_with_deadline(lambda: _spawn_n(_make_spawner(tmp_path / "b", (0.0, 0.0)), rng_zero, 40))
    assert rng_default.bit_generator.state == rng_zero.bit_generator.state


# Литерал снят с кода ДО задачи (коммит плана ce29455a): rng.random() после 40 спавнов, seed 11, без ключа.
_GOLDEN_NEXT_RANDOM_SEED11_40_SPAWNS = 0.25814085185458835


def test_spawner_default_rng_sequence_unchanged_golden(tmp_path: Path) -> None:
    """[GREEN-контроль, обязан остаться зелёным] Без ключа rng-последовательность байт в байт как ДО задачи:
    после 40 спавнов (seed 11) следующий `rng.random()` — литерал, снятый с кода до задачи."""
    rng = np.random.default_rng(11)
    _run_with_deadline(lambda: _spawn_n(_make_spawner(tmp_path, None), rng, 40))
    assert rng.random() == _GOLDEN_NEXT_RANDOM_SEED11_40_SPAWNS
