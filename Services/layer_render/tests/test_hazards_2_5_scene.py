# -*- coding: utf-8 -*-
"""Task 2.5 (hazard-тесты автора): что может сломаться в ЭТОМ механизме, раз он устроен так.

Механизм: `render_scene` — одна проходная функция (проверки -> `np.empty` -> `render_background` -> цепочка `composite`
-> `apply_effects` только при непустом списке); `SceneCompositor.render` — геометрия + отсечение, затем делегирование.
Слепые тесты тестера (`test_acceptance_2_5_render_scene.py`) держат контракт по критериям; здесь — места, которые видны
только автору:

H1  Последовательность, из которой `placed`/`effects` читаются ДВАЖДЫ (проверка, потом рисование): генератор после
    проверки был бы пуст, кадр вышел бы без объектов и без эффектов — молча. Функция обязана прочитать вход один раз.
H2  Пустой `effects`: `rng` не трогается вовсе (не «состояние то же» — ни одного обращения). Оракул — rng-ловушка,
    любое обращение к которой роняет тест; состояние `bit_generator` такое нарушение не поймало бы, если бы вызов
    был без розыгрыша.
H3  Порядок проверок: плохой элемент `effects` при живом `rng` не оставляет частично потраченного потока (проверки
    до рисования), плохой `placed` не доходит до проверки `effects`.
H4  `PlacedObject` не копирует `rgba` (тот же объект) и принимает read-only НЕСПЛОШНОЙ срез: кадр равен кадру от
    сплошной копии. Прямой оракул «аллокаций нет» не берём: вся цена копий — внутри `composite` (копия кадра на объект),
    а `rgba` туда читается; доказать отсутствие копии спрайта можно только по идентичности объекта в `PlacedObject`
    плюс неизменности байтов (A5 тестера).
H5  `SceneCompositor`, ветка без стека: `now_encoder=NaN` не бросает на пути с ОБЪЕКТАМИ (сдвиг тайла считать нельзя);
    со стеком NaN бросает ДО обращения к спавнеру (не после частично собранных паспортов).
H6  BGR -> RGB на цветном входе с тремя разными каналами: `(1, 2, 3)` даёт пиксель `(3, 2, 1)`. Серый такой порядок
    не ловит.
H7  Сужение `background_bgr`: текст ошибки не повторяет значение; причина (`__cause__`) — исходная ошибка `SolidFill`;
    при заданном `background_layers` невалидный `background_bgr` по-прежнему игнорируется (как до задачи).
H8  `obj.render()` зовётся для КАЖДОГО активного объекта, в том числе отсечённого (размер спрайта нужен для отсечения),
    а в `render_scene` уходит только видимый.
H9  `background_layers=[]` (пустой стек): чёрный кадр, без исключения — `fold_background([])` даёт `[SolidFill(0,0,0)]`;
    целый `belt_y_px` со стеком принимается.
H10 Неизменяемость: поля `SceneBackground`/`PlacedObject` не присваиваются; `np.bool_` как размер отвергается так же,
    как `bool`.
"""

from __future__ import annotations

import dataclasses
from types import SimpleNamespace

import numpy as np
import pytest

from Services.layer_render.effects import EffectSpec
from Services.layer_render.interfaces import ScrollingTile, SolidFill
from Services.layer_render.scene import PlacedObject, SceneBackground, render_scene

_RECT = (0.0, 0.0, 40.0, 30.0)


def _sprite(h: int, w: int, rgb: tuple[int, int, int], alpha: int = 255) -> np.ndarray:
    sprite = np.zeros((h, w, 4), dtype=np.uint8)
    sprite[:, :, :3] = rgb
    sprite[:, :, 3] = alpha
    return sprite


def _bg(layers=None, size_wh=(20, 12)) -> SceneBackground:
    return SceneBackground([SolidFill((10, 20, 30))] if layers is None else layers, size_wh, center_y=6.0)


class _PoisonRng:
    """rng-ловушка: любое обращение (в том числе `bit_generator`, `random`) — провал теста."""

    def __getattr__(self, name: str):
        raise AssertionError(f"rng тронут: .{name}")


# --- H1 -------------------------------------------------------------------------------------------------------


def test_h1_generators_for_placed_and_effects_are_read_once_and_not_lost():
    """Генератор на входе: если бы функция читала его дважды (проверка, затем рисование), объекты и эффекты пропали бы
    молча. Кадр от генераторов == кадру от списков, и он не равен кадру без объектов и эффектов."""
    objects = [
        PlacedObject(_sprite(4, 4, (200, 0, 0)), (8.0, 6.0)),
        PlacedObject(_sprite(3, 3, (0, 200, 0)), (9.0, 6.0)),
    ]
    effects = [EffectSpec("brightness_contrast", 1.0, {"brightness": (30.0, 30.0), "contrast": (1.0, 1.0)})]
    bg = _bg()
    from_lists = render_scene(bg, objects, effects, np.random.default_rng(3))
    from_generators = render_scene(bg, (o for o in objects), (e for e in effects), np.random.default_rng(3))
    bare = render_scene(bg, [], [], None)
    assert not np.array_equal(from_lists, bare), "объекты и эффекты ничего не изменили — тест вакуумный"
    assert np.array_equal(from_generators, from_lists)


# --- H2 -------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("empty", [[], ()], ids=["list", "tuple"])
def test_h2_empty_effects_never_touch_rng(empty):
    """Пустой `effects`: rng-ловушка с любым пустым контейнером не задета; объекты при этом нарисованы (якорь)."""
    objects = [PlacedObject(_sprite(4, 4, (200, 0, 0)), (8.0, 6.0))]
    frame = render_scene(_bg(), objects, empty, _PoisonRng())
    assert tuple(int(v) for v in frame[6, 8]) == (200, 0, 0)


# --- H3 -------------------------------------------------------------------------------------------------------


def test_h3_bad_effect_element_leaves_a_live_rng_untouched():
    """Плохой элемент `effects` с живым `rng`: `ValueError` ДО рисования и ДО розыгрышей — состояние потока то же."""
    rng = np.random.default_rng(11)
    before = np.random.default_rng(11).bit_generator.state
    effects = [EffectSpec("noise", 1.0), object()]
    with pytest.raises(ValueError, match=r"effects\[1\]"):
        render_scene(_bg(), [PlacedObject(_sprite(2, 2, (1, 2, 3)), (5.0, 5.0))], effects, rng)
    assert rng.bit_generator.state == before


def test_h3_bad_placed_element_is_reported_before_bad_effect_and_missing_rng():
    """Плохой `placed` вместе с плохим `effects` и `rng=None`: сообщение называет `placed[1]`, не `effects`/`rng`."""
    ok = PlacedObject(_sprite(1, 1, (1, 2, 3)), (1.0, 1.0))
    with pytest.raises(ValueError) as info:
        render_scene(_bg(), [ok, "not-an-object"], [object()], None)
    text = str(info.value)
    assert "placed[1]" in text
    assert "effects" not in text and "rng" not in text


# --- H4 -------------------------------------------------------------------------------------------------------


def test_h4_placed_object_keeps_the_same_array_and_accepts_noncontiguous_readonly_view():
    """`PlacedObject.rgba is` исходный массив (копии нет). Read-only несплошной срез (шаг 2 по строкам) рисуется так же,
    как его сплошная копия: `composite` читает через срез, а не через предположение о раскладке."""
    base = np.random.default_rng(5).integers(0, 256, size=(12, 6, 4), dtype=np.uint8)
    view = base[::2]
    view.flags.writeable = False
    assert not view.flags.c_contiguous
    placed = PlacedObject(view, (8.0, 6.0))
    assert placed.rgba is view
    snapshot = view.tobytes()
    drawn = render_scene(_bg(), [placed], [], None)
    contiguous = render_scene(_bg(), [PlacedObject(np.ascontiguousarray(view), (8.0, 6.0))], [], None)
    assert np.array_equal(drawn, contiguous)
    assert not np.array_equal(drawn, render_scene(_bg(), [], [], None)), "спрайт не нарисован — тест вакуумный"
    assert view.tobytes() == snapshot


# --- H5, H6, H7, H9: SceneCompositor ---------------------------------------------------------------------------


class _FakeObject:
    """Объект спавнера: `render()` считает вызовы; паспорт — только поля, которые читает `SceneCompositor`."""

    def __init__(self, sprite: np.ndarray, spawn_encoder: float) -> None:
        self._sprite = sprite
        self.render_calls = 0
        self.passport = SimpleNamespace(spawn_encoder=spawn_encoder, lateral_px=0.0)

    def render(self) -> np.ndarray:
        self.render_calls += 1
        return self._sprite


class _FakeSpawner:
    def __init__(self, objects) -> None:
        self._objects = list(objects)
        self.calls = 0

    def active_objects(self):
        self.calls += 1
        return list(self._objects)


def _compositor(spawner, **kwargs):
    from Services.line_sim import SceneCompositor

    return SceneCompositor(spawner, px_per_mm=3.0, belt_y_px=15.0, **kwargs)


def test_h5_without_stack_nan_encoder_with_objects_does_not_raise():
    """Без стека `NaN` не бросает и на пути с объектами (позиция объекта NaN -> отсечён, кадр — чистый фон)."""
    spawner = _FakeSpawner([_FakeObject(_sprite(4, 4, (255, 0, 0)), 0.0)])
    frame, passports = _compositor(spawner, background_bgr=(1, 2, 3)).render(float("nan"), _RECT)
    assert frame.shape == (30, 40, 3)
    assert passports == []
    assert (frame == np.array([3, 2, 1], dtype=np.uint8)).all()


def test_h5_with_stack_nan_encoder_raises_before_touching_the_spawner():
    """Со стеком `NaN` бросает при расчёте сдвига тайла — до чтения спавнера (нет полусобранных паспортов)."""
    spawner = _FakeSpawner([_FakeObject(_sprite(4, 4, (255, 0, 0)), 0.0)])
    comp = _compositor(spawner, background_layers=[SolidFill((1, 2, 3))])
    with pytest.raises((ValueError, OverflowError)):
        comp.render(float("nan"), _RECT)
    assert spawner.calls == 0


def test_h6_bgr_to_rgb_on_three_distinct_channels():
    """`background_bgr=(1, 2, 3)` (B=1, G=2, R=3) -> пиксель RGB `(3, 2, 1)`; серый порядок не различает."""
    frame, _ = _compositor(_FakeSpawner([]), background_bgr=(1, 2, 3)).render(0.0, _RECT)
    assert (frame == np.array([3, 2, 1], dtype=np.uint8)).all()


def test_h7_invalid_background_bgr_message_hides_the_value_and_chains_the_cause():
    """Текст ошибки не повторяет значение (секретность не причина — шум и чужой порядок каналов), причина сохранена."""
    with pytest.raises(ValueError) as info:
        _compositor(_FakeSpawner([]), background_bgr=(777, 0, 0))
    assert "background_bgr" in str(info.value)
    assert "777" not in str(info.value)
    assert isinstance(info.value.__cause__, ValueError)
    assert "SolidFill" in str(info.value.__cause__)


def test_h7_invalid_background_bgr_is_ignored_when_stack_is_given():
    """Прежнее поведение: при заданном `background_layers` значение `background_bgr` не читается и не проверяется."""
    comp = _compositor(_FakeSpawner([]), background_bgr=(300, 0, 0), background_layers=[SolidFill((9, 8, 7))])
    frame, _ = comp.render(0.0, _RECT)
    assert (frame == np.array([9, 8, 7], dtype=np.uint8)).all()


def test_h8_render_is_called_for_every_active_object_but_only_visible_ones_are_drawn():
    """Размер спрайта нужен для отсечения: `render()` зовётся и у невидимого. В паспортах — только видимый."""
    visible = _FakeObject(_sprite(4, 4, (255, 0, 0)), 0.0)
    invisible = _FakeObject(_sprite(4, 4, (0, 255, 0)), -100000.0)
    comp = _compositor(_FakeSpawner([invisible, visible]), background_bgr=(0, 0, 0), entry_x_px=20.0)
    frame, passports = comp.render(0.0, _RECT)
    assert visible.render_calls == 1 and invisible.render_calls == 1
    assert passports == [visible.passport]
    assert tuple(int(v) for v in frame[15, 20]) == (255, 0, 0)
    assert not (frame[:, :, 1] == 255).any()


def test_h9_empty_stack_gives_black_frame_and_integer_belt_y_is_accepted():
    """`background_layers=[]` — чёрный кадр без исключения; целый `belt_y_px=15` со стеком тайла тоже работает."""
    frame, _ = _compositor(_FakeSpawner([]), background_layers=[]).render(0.0, _RECT)
    assert frame.shape == (30, 40, 3) and not frame.any()
    tile = ScrollingTile(np.full((4, 6, 3), 77, dtype=np.uint8))
    frame2, _ = _compositor(_FakeSpawner([]), background_layers=[tile]).render(0.0, _RECT)
    assert (frame2[13:17] == 77).all()  # полоса тайла: top = round(15 - 2) = 13, высота 4


# --- H10 ------------------------------------------------------------------------------------------------------


def test_h10_fields_are_frozen_and_numpy_bool_size_is_rejected():
    bg = _bg()
    with pytest.raises(dataclasses.FrozenInstanceError):
        bg.scroll_px = 5  # type: ignore[misc]
    obj = PlacedObject(_sprite(1, 1, (1, 2, 3)), (0.0, 0.0))
    with pytest.raises(dataclasses.FrozenInstanceError):
        obj.center_xy = (1.0, 1.0)  # type: ignore[misc]
    with pytest.raises(ValueError):
        SceneBackground([SolidFill((1, 2, 3))], (np.bool_(True), 4), center_y=1.0)
