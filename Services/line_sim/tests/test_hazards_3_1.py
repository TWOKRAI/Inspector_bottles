"""Авторские hazard-тесты Task 3.1/3.1a — внутренние опасности механизма LayeredObject.

Не дублируют acceptance (`test_acceptance_3_1.py`). Что здесь может сломаться при том,
как объект построен (рендер один раз в __init__, кэш отдаётся по ссылке):
- алиасинг: вызывающий пишет в массив из render() — кэш портится для всех кадров;
- алиасинг источника: спрайт-массив вызывающего меняется после создания объекта;
- провайдер, отдающий разный массив на каждый вызов, — второй вызов дал бы дрожание;
- канва при отрицательном смещении слоя — обрезка вместо расширения;
- общий мутабельный дефолт / мутация входного паспорта.
Все ожидания — литералы.
"""

from __future__ import annotations

import numpy as np
import pytest
from pydantic import ValidationError

from Services.line_sim import LayerAugment, LayeredObject, LayerSpec, ObjectPassport


def _passport(object_id: str = "h", angle_deg: float = 0.0) -> ObjectPassport:
    return ObjectPassport(object_id=object_id, class_name="c", angle_deg=angle_deg, defect=None, spawn_encoder=0.0)


def _marker(channel: int) -> np.ndarray:
    """5x5 RGBA, непрозрачный квадрат 3x3 в центре (9 пикселей)."""
    s = np.zeros((5, 5, 4), dtype=np.uint8)
    s[1:4, 1:4, channel] = 220
    s[1:4, 1:4, 3] = 255
    return s


def _centroid(rgba: np.ndarray, channel: int) -> tuple[float, float]:
    ys, xs = np.nonzero((rgba[:, :, channel] > 150) & (rgba[:, :, 3] > 0))
    return float(xs.mean()), float(ys.mean())


def test_render_array_is_read_only_and_cache_survives_write_attempt():
    obj = LayeredObject(
        _passport(), [LayerSpec(name="a", mode="static", sprite_source=_marker(0))], np.random.default_rng(0)
    )
    frame = obj.render()
    before = frame.copy()
    with pytest.raises(ValueError):
        frame[2, 2, 3] = 0
    assert obj.render() is frame
    assert np.array_equal(obj.render(), before)


def test_mutating_caller_sprite_after_construction_does_not_change_render():
    sprite = _marker(0)
    obj = LayeredObject(
        _passport(), [LayerSpec(name="a", mode="static", sprite_source=sprite)], np.random.default_rng(0)
    )
    before = obj.render().copy()
    sprite[:] = 0  # вызывающий переиспользовал буфер
    assert np.array_equal(obj.render(), before)


def test_provider_returning_new_array_each_call_is_called_once_per_object():
    calls = []

    def provider() -> np.ndarray:
        calls.append(1)
        s = _marker(0)
        s[1:4, 1:4, 0] = 100 + len(calls)  # каждый вызов — другой массив
        return s

    obj = LayeredObject(
        _passport(), [LayerSpec(name="a", mode="static", sprite_source=provider)], np.random.default_rng(0)
    )
    first = obj.render().copy()
    for _ in range(3):
        assert np.array_equal(obj.render(), first)
    assert len(calls) == 1
    assert int(first[:, :, 0].max()) == 101  # значение первого (и единственного) вызова


def test_negative_offset_expands_canvas_and_keeps_every_pixel():
    layers = [
        LayerSpec(name="anchor", mode="static", sprite_source=_marker(0)),
        LayerSpec(name="far", mode="static", sprite_source=_marker(2), offset_px=(-30.0, -20.0)),
    ]
    frame = LayeredObject(_passport(), layers, np.random.default_rng(0)).render()
    assert int(np.count_nonzero(frame[:, :, 3])) == 18  # 9 + 9 — ни один пиксель не обрезан
    ax, ay = _centroid(frame, 0)
    bx, by = _centroid(frame, 2)
    assert bx - ax == pytest.approx(-30.0, abs=1.0)
    assert by - ay == pytest.approx(-20.0, abs=1.0)


def test_object_center_is_canvas_center():
    """Контракт для SceneCompositor: центр объекта = центр массива render()."""
    layer = LayerSpec(name="m", mode="static", sprite_source=_marker(2), offset_px=(10.0, 0.0))
    frame = LayeredObject(_passport(), [layer], np.random.default_rng(0)).render()
    h, w = frame.shape[:2]
    x, y = _centroid(frame, 2)
    assert x - w / 2.0 == pytest.approx(10.0, abs=1.0)
    assert y - h / 2.0 == pytest.approx(0.0, abs=1.0)


def test_input_passport_not_mutated_and_defaults_not_shared():
    passport = _passport("p")
    layer = LayerSpec(name="d", mode="defect", sprite_source=_marker(2), defect_probability=1.0)
    base = LayerSpec(name="b", mode="static", sprite_source=_marker(0))
    obj = LayeredObject(passport, [base, layer], np.random.default_rng(0))
    assert passport.layer_params == {}
    assert passport.defect is None
    assert obj.passport.defect == "d"
    assert obj.passport.layer_params == {"d": {"active": True}}
    other = _passport("q")
    assert other.layer_params is not passport.layer_params


def test_layer_spec_is_frozen():
    spec = LayerSpec(name="a", mode="static", sprite_source=_marker(0))
    with pytest.raises(ValidationError):
        spec.offset_px = (5.0, 5.0)  # type: ignore[misc]


def test_string_sprite_source_rejected_until_catalog():
    with pytest.raises(TypeError, match="3.2"):
        LayeredObject(
            _passport(), [LayerSpec(name="s", mode="static", sprite_source="fixture://x")], np.random.default_rng(0)
        )


def test_fully_transparent_object_rejected():
    empty = np.zeros((5, 5, 4), dtype=np.uint8)
    with pytest.raises(ValueError, match="прозрачен"):
        LayeredObject(_passport(), [LayerSpec(name="e", mode="static", sprite_source=empty)], np.random.default_rng(0))


# --- ревью, итерация 1 --------------------------------------------------------


def _solid(h: int, w: int) -> np.ndarray:
    s = np.zeros((h, w, 4), dtype=np.uint8)
    s[:, :, 0] = 200
    s[:, :, 3] = 255
    return s


def test_forced_defect_from_passport_draws_without_roll():
    passport = ObjectPassport(object_id="f", class_name="c", angle_deg=0.0, defect="dmg", spawn_encoder=0.0)
    layers = [
        LayerSpec(name="b", mode="static", sprite_source=_marker(0)),
        LayerSpec(name="dmg", mode="defect", sprite_source=_marker(2), offset_px=(8.0, 0.0), defect_probability=0.0),
    ]
    obj = LayeredObject(passport, layers, np.random.default_rng(0))
    assert obj.passport.defect == "dmg"
    assert obj.passport.layer_params["dmg"] == {"active": True}
    assert int(np.count_nonzero(obj.render()[:, :, 2] > 150)) == 9


def test_forced_defect_unknown_name_raises():
    passport = ObjectPassport(object_id="u", class_name="c", angle_deg=0.0, defect="nope", spawn_encoder=0.0)
    layers = [LayerSpec(name="dmg", mode="defect", sprite_source=_marker(2), defect_probability=1.0)]
    with pytest.raises(ValueError, match="nope"):
        LayeredObject(passport, layers, np.random.default_rng(0))


@pytest.mark.parametrize(("h", "w", "area"), [(5, 5, 25), (20, 50, 1000)])
@pytest.mark.parametrize("angle", [0.0, 90.0, 180.0, 270.0, -90.0])
def test_quarter_rotation_keeps_every_pixel_opaque(h, w, area, angle):
    """Кратные 90° — без среза края и без размытия: вся площадь остаётся alpha=255."""
    sprite = _solid(h, w)
    rng = np.random.default_rng
    obj_rot = LayeredObject(
        _passport(angle_deg=angle), [LayerSpec(name="a", mode="static", sprite_source=sprite)], rng(0)
    )
    layer_rot = LayeredObject(
        _passport(), [LayerSpec(name="a", mode="static", sprite_source=sprite, angle_deg=angle)], rng(0)
    )
    for frame in (obj_rot.render(), layer_rot.render()):
        assert int(np.count_nonzero(frame[:, :, 3] == 255)) == area
        assert int(np.count_nonzero(frame[:, :, 3])) == area


@pytest.mark.parametrize(("angle", "expected"), [(90.0, (0.0, -10.0)), (180.0, (-10.0, 0.0)), (270.0, (0.0, 10.0))])
def test_quarter_rotation_centre_residual_is_half_pixel(angle, expected):
    """Остаток 0.5 px — целочисленная постановка нечётного спрайта на чётную канву (см. LS-005)."""
    layer = LayerSpec(name="m", mode="static", sprite_source=_marker(2), offset_px=(10.0, 0.0))
    frame = LayeredObject(_passport(angle_deg=angle), [layer], np.random.default_rng(0)).render()
    h, w = frame.shape[:2]
    ys, xs = np.nonzero(frame[:, :, 3])
    assert xs.mean() + 0.5 - w / 2.0 == pytest.approx(expected[0], abs=0.6)
    assert ys.mean() + 0.5 - h / 2.0 == pytest.approx(expected[1], abs=0.6)


def test_bad_sprite_in_inactive_defect_layer_raises_deterministically():
    rgb = np.zeros((5, 5, 3), dtype=np.uint8)
    layers = [
        LayerSpec(name="b", mode="static", sprite_source=_marker(0)),
        LayerSpec(name="bad", mode="defect", sprite_source=rgb, defect_probability=0.0),
    ]
    for seed in range(5):
        with pytest.raises(ValueError, match="bad"):
            LayeredObject(_passport(), layers, np.random.default_rng(seed))


def test_provider_of_inactive_defect_layer_called_once():
    calls = []

    def provider() -> np.ndarray:
        calls.append(1)
        return _marker(2)

    layers = [
        LayerSpec(name="b", mode="static", sprite_source=_marker(0)),
        LayerSpec(name="d", mode="defect", sprite_source=provider, defect_probability=0.0),
    ]
    LayeredObject(_passport(), layers, np.random.default_rng(0))
    assert len(calls) == 1


def test_trailing_defect_roll_does_not_shift_earlier_layer_sampling():
    """Своя подпоследовательность rng на слой: defect-слой в конце не меняет выборку этикетки."""
    base = LayerSpec(name="b", mode="static", sprite_source=_marker(0))
    label = LayerSpec(
        name="l",
        mode="augmented",
        sprite_source=_marker(2),
        offset_px=(6.0, 0.0),
        augment=LayerAugment(angle_deg=(-30.0, 30.0)),
    )
    dmg = LayerSpec(name="d", mode="defect", sprite_source=_marker(1), defect_probability=0.0)
    for seed in range(5):
        a = LayeredObject(_passport(), [base, label, dmg], np.random.default_rng(seed))
        b = LayeredObject(_passport(), [base, label], np.random.default_rng(seed))
        assert a.passport.layer_params["l"] == b.passport.layer_params["l"]
        assert np.array_equal(a.render(), b.render())


def test_forcing_a_defect_does_not_shift_following_layer_sampling():
    """Принудительный дефект пропускает розыгрыш; на общем rng это сдвинуло бы выборку этикетки."""
    dmg = LayerSpec(name="d", mode="defect", sprite_source=_marker(1), defect_probability=1.0)
    label = LayerSpec(
        name="l", mode="augmented", sprite_source=_marker(2), augment=LayerAugment(angle_deg=(-30.0, 30.0))
    )
    forced = ObjectPassport(object_id="f", class_name="c", angle_deg=0.0, defect="d", spawn_encoder=0.0)
    for seed in range(5):
        a = LayeredObject(forced, [dmg, label], np.random.default_rng(seed))
        b = LayeredObject(_passport(), [dmg, label], np.random.default_rng(seed))
        assert a.passport.layer_params["l"] == b.passport.layer_params["l"]


def test_duplicate_layer_names_rejected():
    """[lead 3.1, ревью 2] layer_params и принудительный defect адресуют слой по имени — дубль неоднозначен."""
    a = LayerSpec(name="x", mode="static", sprite_source=_marker(0))
    b = LayerSpec(name="x", mode="static", sprite_source=_marker(1))
    with pytest.raises(ValueError, match=r"\['x'\]"):
        LayeredObject(_passport(), [a, b], np.random.default_rng(0))
    from Services.line_sim import ScenePreset

    layer = {"name": "x", "mode": "static", "sprite_source": "id"}
    with pytest.raises(ValidationError, match=r"\['x'\]"):
        ScenePreset.from_dict({"layers": [layer, dict(layer)]})
