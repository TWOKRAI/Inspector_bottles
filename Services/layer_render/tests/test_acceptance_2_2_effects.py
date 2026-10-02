"""Task 2.2 (слепой тест тестера): `Services/layer_render/effects.py` — реестр эффектов, `EffectSpec`, `apply_effects`.

Пишется по acceptance-критериям A1c, A2, A3, A5, A6, A8 (AST-часть) и DESIGN плана `layer-render/phase-2-core.md`.
Ожидаемые значения — литералы или независимый ручной вывод из numpy/cv2, не из проверяемого кода.
`Services.layer_render.effects` импортируется внутри теста: каждый красный тест красен сам по себе, а не одной
ошибкой сбора.
"""

from __future__ import annotations

import ast
import dataclasses
import types
from pathlib import Path

import cv2
import numpy as np
import pytest

_ROOT = Path(__file__).resolve().parents[3]
_LAYER_RENDER = _ROOT / "Services" / "layer_render"

CANONICAL_ORDER = [
    "glare",
    "shadow",
    "occlusion",
    "gaussian_blur",
    "motion_blur",
    "vignette",
    "brightness_contrast",
    "gamma",
    "color_temperature",
    "channel_shift",
    "noise",
    "jpeg",
]

_FRAME = np.random.default_rng(2024).integers(0, 256, (48, 64, 3), dtype=np.uint8)  # 64 (ширина) x 48 (высота)


# --------------------------------------------------------------------------------------------------
# A3 — канонический порядок.
# --------------------------------------------------------------------------------------------------


def test_a3_effects_insertion_order_is_canonical():
    from Services.layer_render.effects import EFFECTS

    assert list(EFFECTS) == CANONICAL_ORDER


def test_a3_effects_values_are_callables_and_params_cover_same_names():
    from Services.layer_render.effects import EFFECT_PARAMS, EFFECTS

    assert all(callable(fn) for fn in EFFECTS.values())
    assert set(EFFECT_PARAMS) == set(EFFECTS)


# --------------------------------------------------------------------------------------------------
# A2 — пустой список: ни одного розыгрыша, копия, а не тот же объект.
# --------------------------------------------------------------------------------------------------


def test_a2_empty_specs_leaves_rng_state_untouched():
    from Services.layer_render.effects import apply_effects

    rng = np.random.default_rng(11)
    before = rng.bit_generator.state
    apply_effects(_FRAME, [], rng)
    assert rng.bit_generator.state == before


def test_a2_empty_specs_returns_equal_copy_not_the_input():
    from Services.layer_render.effects import apply_effects

    frame = _FRAME.copy()
    out = apply_effects(frame, [], np.random.default_rng(11))
    assert out.dtype == np.uint8 and out.shape == frame.shape
    assert out.tobytes() == frame.tobytes()
    assert out is not frame
    assert not np.shares_memory(out, frame)


# --------------------------------------------------------------------------------------------------
# Розыгрыш prob: ВСЕГДА, и при 0.0, и при 1.0 (DESIGN).
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("n_specs", [1, 2, 3])
def test_prob_zero_draws_once_per_spec_and_applies_nothing(n_specs):
    from Services.layer_render.effects import EffectSpec, apply_effects

    frame = _FRAME.copy()
    rng = np.random.default_rng(3)
    out = apply_effects(frame, [EffectSpec("noise", prob=0.0) for _ in range(n_specs)], rng)

    expected_rng = np.random.default_rng(3)
    for _ in range(n_specs):
        expected_rng.random()
    assert rng.bit_generator.state == expected_rng.bit_generator.state
    assert out.tobytes() == frame.tobytes()
    assert out is not frame


def test_prob_one_draws_the_gate_then_the_effect_values():
    """noise при prob=1.0: random() (вентиль), uniform(std), standard_normal(shape, float32) — ровно в этом порядке."""
    from Services.layer_render.effects import EffectSpec, apply_effects

    rng = np.random.default_rng(3)
    out = apply_effects(_FRAME, [EffectSpec("noise", prob=1.0)], rng)

    ref = np.random.default_rng(3)
    ref.random()
    std = float(ref.uniform(2.0, 10.0))
    x = _FRAME.astype(np.float32)
    x += ref.standard_normal(x.shape, dtype=np.float32) * std
    assert out.tobytes() == np.clip(x, 0, 255).astype(np.uint8).tobytes()
    assert rng.bit_generator.state == ref.bit_generator.state


@pytest.mark.parametrize("name", CANONICAL_ORDER)
def test_each_effect_returns_uint8_same_shape_and_leaves_input_untouched(name):
    from Services.layer_render.effects import EffectSpec, apply_effects

    frame = _FRAME.copy()
    out = apply_effects(frame, [EffectSpec(name, prob=1.0)], np.random.default_rng(9))
    assert out.dtype == np.uint8 and out.shape == frame.shape
    assert frame.tobytes() == _FRAME.tobytes(), "apply_effects изменил входной кадр"


# --------------------------------------------------------------------------------------------------
# A1c — нестандартный порядок и несколько U8-эффектов подряд. Ожидание — ручной вывод по DESIGN:
# U8-эффект получает clip->uint8, после него кадр снова float32, в конце clip->uint8.
# --------------------------------------------------------------------------------------------------


def _jpeg(frame_u8, quality):
    bgr = cv2.cvtColor(frame_u8, cv2.COLOR_RGB2BGR)
    ok, buf = cv2.imencode(".jpg", bgr, [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)])
    assert ok
    return cv2.cvtColor(cv2.imdecode(buf, cv2.IMREAD_COLOR), cv2.COLOR_BGR2RGB)


def _manual(frame_u8, names, seed):
    """Независимое вычисление: `names` из {'jpeg','noise'}, дефолтные параметры (quality 50..90, std 2..10),
    prob 1.0."""
    rng = np.random.default_rng(seed)
    x = frame_u8.astype(np.float32)
    for name in names:
        assert rng.random() < 1.0
        if name == "jpeg":
            quality = int(rng.integers(50, 90 + 1))
            x = _jpeg(np.clip(x, 0, 255).astype(np.uint8), quality).astype(np.float32)
        else:
            std = float(rng.uniform(2.0, 10.0))
            x += rng.standard_normal(x.shape, dtype=np.float32) * std
    return np.clip(x, 0, 255).astype(np.uint8), rng


@pytest.mark.parametrize(
    "names",
    [["jpeg", "noise"], ["jpeg", "jpeg"], ["noise", "jpeg", "noise"]],
    ids=lambda n: "+".join(n),
)
def test_a1c_noncanonical_order_matches_manual_derivation(names):
    from Services.layer_render.effects import EffectSpec, apply_effects

    for seed in range(10):
        rng = np.random.default_rng(seed)
        out = apply_effects(_FRAME, [EffectSpec(n, prob=1.0) for n in names], rng)
        expected, ref_rng = _manual(_FRAME, names, seed)
        assert out.dtype == np.uint8 and out.shape == _FRAME.shape, f"seed={seed}"
        assert out.tobytes() == expected.tobytes(), f"{names} seed={seed}: кадр"
        assert rng.bit_generator.state == ref_rng.bit_generator.state, f"{names} seed={seed}: состояние rng"


# --------------------------------------------------------------------------------------------------
# A5 — EffectSpec: валидация и сообщения.
# --------------------------------------------------------------------------------------------------


def test_a5_unknown_name_raises_value_error_listing_known_names():
    from Services.layer_render.effects import EffectSpec

    with pytest.raises(ValueError) as exc:
        EffectSpec("nope")
    msg = str(exc.value)
    assert "glare" in msg and "jpeg" in msg
    assert all(name in msg for name in CANONICAL_ORDER)  # «список известных» — все 12


def test_a5_unknown_param_key_raises_value_error_with_key_and_allowed_list():
    from Services.layer_render.effects import EffectSpec

    with pytest.raises(ValueError) as exc:
        EffectSpec("noise", params={"sigma": 1})
    msg = str(exc.value)
    assert "sigma" in msg and "std" in msg


def test_a5_unknown_param_key_lists_every_allowed_key_of_a_multi_param_effect():
    from Services.layer_render.effects import EffectSpec

    with pytest.raises(ValueError) as exc:
        EffectSpec("glare", params={"foo": 1})
    msg = str(exc.value)
    assert "foo" in msg and "intensity" in msg and "radius_frac" in msg


def test_a5_one_unknown_key_among_valid_ones_still_raises():
    from Services.layer_render.effects import EffectSpec

    with pytest.raises(ValueError, match="bogus"):
        EffectSpec("glare", params={"intensity": (1.0, 2.0), "bogus": 3})


@pytest.mark.parametrize("prob", [1.5, -0.1, 1.0000001, -1e-9])
def test_a5_prob_outside_unit_interval_raises(prob):
    from Services.layer_render.effects import EffectSpec

    with pytest.raises(ValueError):
        EffectSpec("noise", prob=prob)


@pytest.mark.parametrize("prob", [0.0, 1.0, 0.5])
def test_a5_prob_on_boundaries_is_accepted(prob):
    from Services.layer_render.effects import EffectSpec

    assert EffectSpec("noise", prob=prob).prob == prob


# --------------------------------------------------------------------------------------------------
# EffectSpec — DESIGN: дефолты, слияние, неизменяемость, eq=False.
# --------------------------------------------------------------------------------------------------


def _norm(v):
    if isinstance(v, (list, tuple)):
        return tuple(_norm(i) for i in v)
    return v


def test_effect_spec_defaults_prob_one_and_params_from_catalog():
    from Services.layer_render.effects import EffectSpec

    spec = EffectSpec("noise")
    assert spec.name == "noise"
    assert spec.prob == 1.0
    assert _norm(dict(spec.params)) == {"std": (2.0, 10.0)}  # литерал дефолта NoiseAug.std


def test_effect_spec_missing_keys_filled_with_defaults_given_keys_kept():
    from Services.layer_render.effects import EffectSpec

    spec = EffectSpec("occlusion", params={"count": (3, 3)})
    assert _norm(dict(spec.params)) == {"count": (3, 3), "size_frac": (0.05, 0.18)}


def test_effect_spec_params_is_read_only_mapping_proxy():
    from Services.layer_render.effects import EffectSpec

    spec = EffectSpec("noise")
    assert isinstance(spec.params, types.MappingProxyType)
    with pytest.raises(TypeError):
        spec.params["std"] = (1.0, 2.0)


def test_effect_spec_does_not_alias_the_callers_dict():
    from Services.layer_render.effects import EffectSpec

    given = {"std": (1.0, 2.0)}
    spec = EffectSpec("noise", params=given)
    given["std"] = (5.0, 6.0)
    assert _norm(spec.params["std"]) == (1.0, 2.0)


def test_effect_spec_is_frozen():
    from Services.layer_render.effects import EffectSpec

    spec = EffectSpec("noise")
    with pytest.raises(dataclasses.FrozenInstanceError):
        spec.prob = 0.5


def test_effect_spec_equality_is_by_identity():
    """eq=False (DESIGN): два одинаково собранных spec не равны, сам с собой равен."""
    from Services.layer_render.effects import EffectSpec

    a, b = EffectSpec("noise"), EffectSpec("noise")
    assert a == a
    assert a != b


# --------------------------------------------------------------------------------------------------
# A6 — реэкспорт: те же объекты; line_sim.factory работает без правки.
# --------------------------------------------------------------------------------------------------

_FUNC_NAMES = [
    "apply_glare",
    "make_motion_kernel",
    "apply_motion_blur",
    "apply_brightness_contrast",
    "apply_color_temperature",
    "apply_channel_shift",
    "apply_shadow",
    "apply_occlusion",
    "apply_gamma",
    "apply_vignette",
    "apply_jpeg",
]


@pytest.mark.parametrize("name", _FUNC_NAMES)
def test_a6_dataset_gen_augment_name_is_the_layer_render_object(name):
    import Services.dataset_gen.core.augment as aug
    import Services.layer_render.effects as fx

    assert getattr(aug, name) is getattr(fx, name)


def test_a6_private_uniform_is_not_reexported_by_augment():
    import Services.dataset_gen.core.augment as aug
    import Services.layer_render.effects  # noqa: F401  (граница: в effects _uniform есть, в augment — нет)

    assert not hasattr(aug, "_uniform")


def test_a6_uniform_lives_in_effects_module():
    import Services.layer_render.effects as fx

    rng = np.random.default_rng(1)
    got = fx._uniform(rng, (2.0, 4.0))
    ref = float(np.random.default_rng(1).uniform(2.0, 4.0))
    assert got == ref and isinstance(got, float)


def test_a6_line_sim_factory_uses_the_moved_occlusion_unchanged():
    import Services.layer_render.effects as fx
    from Services.line_sim.core import factory

    assert factory.apply_occlusion is fx.apply_occlusion
    canvas = np.zeros((10, 10, 3), dtype=np.float32)
    out = factory.apply_occlusion(canvas, (2, 3, 4, 2), (60.0, 60.0, 60.0))
    assert out.shape == canvas.shape
    assert np.all(out[3:5, 2:6] == 60.0)
    assert out.sum() == 60.0 * 3 * (4 * 2)  # закрашено ровно 4x2 пикселя
    assert canvas.sum() == 0.0  # вход не тронут


# --------------------------------------------------------------------------------------------------
# A8 (AST-часть) — layer_render не импортирует dataset_gen/line_sim/ml_train.
# --------------------------------------------------------------------------------------------------

_FORBIDDEN = {"dataset_gen", "line_sim", "ml_train"}


def _forbidden_imports(source: str) -> list[str]:
    """Имена запрещённых пакетов, импортируемых в `source` (любые формы: import / from / relative / from X
    import dataset_gen)."""
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found += [p for p in alias.name.split(".") if p in _FORBIDDEN]
        elif isinstance(node, ast.ImportFrom):
            found += [p for p in (node.module or "").split(".") if p in _FORBIDDEN]
            found += [a.name for a in node.names if a.name in _FORBIDDEN]
    return found


@pytest.mark.parametrize(
    "snippet",
    [
        "import Services.dataset_gen.core.augment",
        "from Services.dataset_gen.core.augment import apply_occlusion",
        "from Services import line_sim",
        "from ..ml_train import x",
        "import ml_train",
    ],
)
def test_a8_import_scanner_detects_forbidden_forms(snippet):
    """Контроль сканера: без него «0 находок» не доказывает ничего."""
    assert _forbidden_imports(snippet)


def test_a8_import_scanner_ignores_innocent_imports():
    assert not _forbidden_imports("import cv2\nfrom Services.layer_render.compose import composite")


def _layer_render_sources() -> list[Path]:
    return [p for p in _LAYER_RENDER.rglob("*.py") if "tests" not in p.relative_to(_LAYER_RENDER).parts]


def test_a8_layer_render_non_test_sources_import_no_forbidden_package():
    files = _layer_render_sources()
    assert len(files) >= 5, files  # анти-вакуум: сканер что-то да видит
    bad = {str(p.relative_to(_ROOT)): _forbidden_imports(p.read_text(encoding="utf-8")) for p in files}
    assert {k: v for k, v in bad.items() if v} == {}


def test_a8_effects_module_exists_and_is_among_scanned_sources():
    effects = _LAYER_RENDER / "effects.py"
    assert effects.is_file(), "Services/layer_render/effects.py не создан"
    assert effects in _layer_render_sources()
    assert _forbidden_imports(effects.read_text(encoding="utf-8")) == []
