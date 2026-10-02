"""Task 2.2 (автор): опасные места МЕХАНИЗМА effects.py — то, что видно только изнутри реализации.

Слепые тесты тестера (test_acceptance_2_2_effects.py) держат контракт по критериям; здесь — дополнительно:
алиасинг параметров (вложенные списки вызывающего), неизменность входного кадра (в т.ч. read-only), U8-круг
JPEG при значениях вне 0..255 перед ним (обёртка uint8 вместо clip), один и тот же spec дважды в списке,
вентиль prob перед каждым эффектом при смеси prob 0.0 и 1.0.
"""

from __future__ import annotations

import cv2
import numpy as np
import pytest

from Services.layer_render.effects import EFFECT_PARAMS, EFFECTS, EffectSpec, apply_effects

_FRAME = np.random.default_rng(77).integers(0, 256, (40, 56, 3), dtype=np.uint8)


def _jpeg(frame_u8: np.ndarray, quality: int) -> np.ndarray:
    bgr = cv2.cvtColor(frame_u8, cv2.COLOR_RGB2BGR)
    ok, buf = cv2.imencode(".jpg", bgr, [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)])
    assert ok
    return cv2.cvtColor(cv2.imdecode(buf, cv2.IMREAD_COLOR), cv2.COLOR_BGR2RGB)


# --- алиасинг параметров -------------------------------------------------------------------------------


def test_nested_list_from_caller_is_deep_copied():
    given = {"std": [1.0, 2.0]}
    spec = EffectSpec("noise", params=given)
    given["std"][0] = 99.0
    given["std"].append(5.0)
    assert list(spec.params["std"]) == [1.0, 2.0]


def test_spec_params_do_not_alias_catalog_defaults(monkeypatch):
    """Правка каталога ПОСЛЕ создания spec не должна менять spec (иначе params — прокси поверх EFFECT_PARAMS)."""
    spec = EffectSpec("noise")
    monkeypatch.setitem(EFFECT_PARAMS["noise"], "std", (99.0, 100.0))
    assert tuple(spec.params["std"]) == (2.0, 10.0)
    assert tuple(EffectSpec("noise").params["std"]) == (99.0, 100.0)  # контроль: каталог правда изменён


def test_params_given_as_mapping_proxy_are_accepted_and_copied():
    from types import MappingProxyType

    source = {"std": (3.0, 4.0)}
    spec = EffectSpec("noise", params=MappingProxyType(source))
    source["std"] = (8.0, 9.0)
    assert tuple(spec.params["std"]) == (3.0, 4.0)


@pytest.mark.parametrize("attr, value", [("name", "gamma"), ("params", {}), ("prob", 0.1)])
def test_every_spec_field_is_frozen(attr, value):
    spec = EffectSpec("noise")
    with pytest.raises(AttributeError):  # FrozenInstanceError — подкласс AttributeError
        setattr(spec, attr, value)


# --- входной кадр --------------------------------------------------------------------------------------


def test_input_frame_untouched_by_the_whole_canonical_chain():
    frame = _FRAME.copy()
    specs = [EffectSpec(n, prob=1.0, params=EFFECT_PARAMS[n]) for n in EFFECTS]
    out = apply_effects(frame, specs, np.random.default_rng(5))
    assert frame.tobytes() == _FRAME.tobytes()
    assert out.dtype == np.uint8 and out.shape == frame.shape
    assert not np.shares_memory(out, frame)


def test_read_only_input_is_accepted_for_in_place_noise():
    """noise правит x на месте; x обязан быть собственной копией, а не входом (иначе — ValueError на read-only)."""
    frame = _FRAME.copy()
    frame.flags.writeable = False
    out = apply_effects(frame, [EffectSpec("noise")], np.random.default_rng(5))
    assert out.shape == frame.shape and frame.tobytes() == _FRAME.tobytes()


def test_empty_specs_tuple_returns_copy_with_zero_draws():
    rng = np.random.default_rng(1)
    before = rng.bit_generator.state
    out = apply_effects(_FRAME, (), rng)
    assert rng.bit_generator.state == before
    assert out.tobytes() == _FRAME.tobytes() and not np.shares_memory(out, _FRAME)


def test_all_gates_closed_returns_copy_not_input():
    frame = _FRAME.copy()
    out = apply_effects(frame, [EffectSpec("noise", prob=0.0), EffectSpec("jpeg", prob=0.0)], np.random.default_rng(2))
    assert out.tobytes() == frame.tobytes()
    assert out is not frame and not np.shares_memory(out, frame)


# --- U8-круг JPEG --------------------------------------------------------------------------------------


@pytest.mark.parametrize("brightness", [200.0, -200.0])
def test_jpeg_receives_clipped_uint8_not_wrapped(brightness):
    """brightness_contrast выводит float далеко за 0..255; JPEG обязан получить clip, а не обёртку по модулю 256."""
    rng = np.random.default_rng(31)
    out = apply_effects(
        _FRAME,
        [
            EffectSpec("brightness_contrast", params={"brightness": (brightness, brightness), "contrast": (1.0, 1.0)}),
            EffectSpec("jpeg"),
        ],
        rng,
    )

    ref = np.random.default_rng(31)
    ref.random()
    ref.uniform(brightness, brightness)  # диапазон вырожден, но uniform всё равно тянет значение из потока
    ref.uniform(1.0, 1.0)
    x = (_FRAME.astype(np.float32) - 127.5) * 1.0 + 127.5 + brightness
    ref.random()
    quality = int(ref.integers(50, 90 + 1))
    expected = _jpeg(np.clip(x, 0, 255).astype(np.uint8), quality)
    assert out.tobytes() == expected.tobytes()
    assert rng.bit_generator.state == ref.bit_generator.state


def test_float_precision_kept_between_two_float_effects_around_a_u8_effect():
    """noise -> jpeg -> noise: после JPEG кадр снова float32, второй шум добавляется к нему и в конце один clip."""
    names = ["noise", "jpeg", "noise"]
    out = apply_effects(_FRAME, [EffectSpec(n) for n in names], np.random.default_rng(8))

    rng = np.random.default_rng(8)
    x = _FRAME.astype(np.float32)
    for n in names:
        rng.random()
        if n == "jpeg":
            x = _jpeg(np.clip(x, 0, 255).astype(np.uint8), int(rng.integers(50, 91))).astype(np.float32)
        else:
            std = float(rng.uniform(2.0, 10.0))  # сначала std, потом нормальный шум
            x += rng.standard_normal(x.shape, dtype=np.float32) * std
    assert out.tobytes() == np.clip(x, 0, 255).astype(np.uint8).tobytes()


# --- вентиль и повторное использование spec ------------------------------------------------------------


def test_closed_gate_before_open_gate_consumes_exactly_one_extra_draw():
    out = apply_effects(
        _FRAME, [EffectSpec("noise", prob=0.0), EffectSpec("noise", prob=1.0)], np.random.default_rng(13)
    )
    # после двух гейтов random() идут uniform(std), затем standard_normal
    ref2 = np.random.default_rng(13)
    ref2.random()  # закрытый вентиль
    ref2.random()  # открытый вентиль
    std = float(ref2.uniform(2.0, 10.0))
    y = _FRAME.astype(np.float32)
    y += ref2.standard_normal(y.shape, dtype=np.float32) * std
    assert out.tobytes() == np.clip(y, 0, 255).astype(np.uint8).tobytes()


def test_same_spec_object_twice_draws_independently():
    spec = EffectSpec("noise")
    once = apply_effects(_FRAME, [spec], np.random.default_rng(4))
    twice = apply_effects(_FRAME, [spec, spec], np.random.default_rng(4))
    two_fresh = apply_effects(_FRAME, [EffectSpec("noise"), EffectSpec("noise")], np.random.default_rng(4))
    assert twice.tobytes() == two_fresh.tobytes()
    assert twice.tobytes() != once.tobytes()


def test_effects_registry_entries_use_only_their_own_param_keys():
    """Каждая запись реестра отрабатывает на ровно своих EFFECT_PARAMS (нет KeyError на недостающем ключе)."""
    base = np.full((24, 32, 3), 100.0, dtype=np.float32)
    for name, fn in EFFECTS.items():
        arg = np.clip(base, 0, 255).astype(np.uint8) if name == "jpeg" else base.copy()
        out = fn(arg, EFFECT_PARAMS[name], np.random.default_rng(0))
        assert out.shape == base.shape, name
