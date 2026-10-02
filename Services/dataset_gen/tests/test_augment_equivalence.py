"""Task 2.2 (слепой тест тестера): эквивалентность `apply_photometric` после переезда в `layer_render.effects`.

Оракул — ДОСЛОВНАЯ копия тел из `Services/dataset_gen/core/augment.py` на коммите ДО задачи (b294a6afe).
Копия самодостаточна (не зовёт ни `dataset_gen.core.augment`, ни `layer_render.effects`), иначе после переезда
оракул и проверяемый код стали бы одним объектом и тест согласился бы с любым ответом.
sha256-литералы сняты на том же коде и вписаны как строки — не пересчитываются из проверяемого кода.

Покрытие: A1 (побайтово + состояние rng, 3 конфига x 50 seed), A1b (sha-литералы), A4 (EFFECT_PARAMS == поля
AugmentConfig), а также поведение `augment_config_to_effects` и покэффектный реестр `EFFECTS`.
`Services.layer_render.effects` импортируется внутри теста — каждый красный тест красен сам по себе.
"""

from __future__ import annotations

import hashlib

import cv2
import numpy as np
import pytest

from Services.dataset_gen.core.config import AugmentConfig

# --------------------------------------------------------------------------------------------------
# Оракул: дословные копии (имена с префиксом _o_, чтобы не путать с проверяемыми).
# --------------------------------------------------------------------------------------------------


def _o_apply_glare(frame, center_xy, radius_px, intensity):
    h, w = frame.shape[:2]
    cx, cy = center_xy
    yy, xx = np.ogrid[:h, :w]
    dist = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2).astype(np.float32)
    falloff = np.clip(1.0 - dist / float(radius_px), 0.0, 1.0) ** 2
    return frame + (intensity * falloff)[:, :, None]


def _o_make_motion_kernel(length, angle_deg):
    size = max(3, int(length) | 1)  # нечётный размер, центр в середине
    kernel = np.zeros((size, size), dtype=np.float32)
    c = size // 2
    rad = np.deg2rad(angle_deg)
    dx, dy = np.cos(rad) * (length / 2.0), np.sin(rad) * (length / 2.0)
    p1 = (int(round(c - dx)), int(round(c - dy)))
    p2 = (int(round(c + dx)), int(round(c + dy)))
    cv2.line(kernel, p1, p2, 1.0, thickness=1)
    s = kernel.sum()
    if s == 0:
        kernel[c, c] = 1.0
        s = 1.0
    return kernel / s


def _o_apply_motion_blur(frame, length, angle_deg):
    return cv2.filter2D(frame, -1, _o_make_motion_kernel(length, angle_deg))


def _o_apply_brightness_contrast(frame, brightness, contrast):
    return (frame - 127.5) * contrast + 127.5 + brightness


def _o_apply_color_temperature(frame, shift):
    out = frame.copy()
    out[:, :, 0] *= 1.0 + shift
    out[:, :, 2] *= 1.0 - shift
    return out


def _o_apply_channel_shift(frame, shifts):
    return frame + np.asarray(shifts, dtype=np.float32)[None, None, :]


def _o_apply_shadow(frame, angle_deg, offset, strength, softness):
    h, w = frame.shape[:2]
    rad = np.deg2rad(angle_deg)
    yy, xx = np.ogrid[:h, :w]
    proj = (xx / max(w - 1, 1)) * np.cos(rad) + (yy / max(h - 1, 1)) * np.sin(rad)
    proj = (proj - proj.min()) / max(proj.max() - proj.min(), 1e-6)  # → [0..1]
    mask = np.clip((proj - offset) / softness, 0.0, 1.0).astype(np.float32)
    return frame * (1.0 - strength * mask)[:, :, None]


def _o_apply_occlusion(frame, rect_xywh, color):
    fh, fw = frame.shape[:2]
    x, y, w, h = rect_xywh
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(fw, x + w), min(fh, y + h)
    out = frame.copy()
    if x0 < x1 and y0 < y1:
        out[y0:y1, x0:x1] = np.asarray(color, dtype=np.float32)
    return out


def _o_apply_gamma(frame, gamma):
    norm = np.clip(frame, 0, 255) / 255.0
    return np.power(norm, gamma, dtype=np.float32) * 255.0


def _o_apply_vignette(frame, strength, radius_frac):
    h, w = frame.shape[:2]
    cy, cx = (h - 1) / 2.0, (w - 1) / 2.0
    yy, xx = np.ogrid[:h, :w]
    dist = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
    max_dist = np.sqrt(cx**2 + cy**2)
    norm = np.clip((dist / max_dist - radius_frac) / max(1.0 - radius_frac, 1e-6), 0.0, 1.0)
    mask = (1.0 - strength * norm**2).astype(np.float32)
    return frame * mask[:, :, None]


def _o_apply_jpeg(frame_u8_rgb, quality):
    bgr = cv2.cvtColor(frame_u8_rgb, cv2.COLOR_RGB2BGR)
    ok, buf = cv2.imencode(".jpg", bgr, [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)])
    if not ok:
        return frame_u8_rgb
    decoded = cv2.imdecode(buf, cv2.IMREAD_COLOR)
    return cv2.cvtColor(decoded, cv2.COLOR_BGR2RGB)


def _o_uniform(rng, rng_pair):
    return float(rng.uniform(rng_pair[0], rng_pair[1]))


def _oracle_apply_photometric(frame_rgb_u8, cfg, rng):
    """Дословно `apply_photometric` (augment.py:180-258 до задачи), вызовы переименованы на _o_*."""
    x = frame_rgb_u8.astype(np.float32)
    h, w = x.shape[:2]

    g = cfg.glare
    if g.enabled and rng.random() < g.prob:
        radius = _o_uniform(rng, g.radius_frac) * min(h, w)
        center = (float(rng.uniform(0, w)), float(rng.uniform(0, h)))
        x = _o_apply_glare(x, center, radius, _o_uniform(rng, g.intensity))

    sh = cfg.shadow
    if sh.enabled and rng.random() < sh.prob:
        x = _o_apply_shadow(
            x,
            angle_deg=float(rng.uniform(0.0, 360.0)),
            offset=float(rng.uniform(0.2, 0.8)),
            strength=_o_uniform(rng, sh.strength),
            softness=_o_uniform(rng, sh.softness_frac),
        )

    oc = cfg.occlusion
    if oc.enabled and rng.random() < oc.prob:
        for _ in range(int(rng.integers(oc.count[0], oc.count[1] + 1))):
            side = _o_uniform(rng, oc.size_frac) * min(h, w)
            rw, rh = int(side * rng.uniform(0.6, 1.6)), int(side * rng.uniform(0.6, 1.6))
            rect = (int(rng.uniform(0, w - 1)), int(rng.uniform(0, h - 1)), max(1, rw), max(1, rh))
            color = tuple(float(c) for c in rng.uniform(0, 255, size=3))
            x = _o_apply_occlusion(x, rect, color)

    b = cfg.gaussian_blur
    if b.enabled and rng.random() < b.prob:
        sigma = _o_uniform(rng, b.sigma)
        x = cv2.GaussianBlur(x, (0, 0), sigmaX=sigma, sigmaY=sigma)

    m = cfg.motion_blur
    if m.enabled and rng.random() < m.prob:
        length = int(rng.integers(m.length[0], m.length[1] + 1))
        x = _o_apply_motion_blur(x, length, float(rng.uniform(0.0, 180.0)))

    vg = cfg.vignette
    if vg.enabled and rng.random() < vg.prob:
        x = _o_apply_vignette(x, _o_uniform(rng, vg.strength), _o_uniform(rng, vg.radius_frac))

    bc = cfg.brightness_contrast
    if bc.enabled and rng.random() < bc.prob:
        x = _o_apply_brightness_contrast(x, _o_uniform(rng, bc.brightness), _o_uniform(rng, bc.contrast))

    gm = cfg.gamma
    if gm.enabled and rng.random() < gm.prob:
        x = _o_apply_gamma(x, _o_uniform(rng, gm.gamma))

    t = cfg.color_temperature
    if t.enabled and rng.random() < t.prob:
        x = _o_apply_color_temperature(x, _o_uniform(rng, t.shift))

    cs = cfg.channel_shift
    if cs.enabled and rng.random() < cs.prob:
        shifts = tuple(float(s) for s in rng.uniform(-cs.max_shift, cs.max_shift, size=3))
        x = _o_apply_channel_shift(x, shifts)

    n = cfg.noise
    if n.enabled and rng.random() < n.prob:
        std = _o_uniform(rng, n.std)
        x += rng.standard_normal(x.shape, dtype=np.float32) * std

    out = np.clip(x, 0, 255).astype(np.uint8)

    j = cfg.jpeg
    if j.enabled and rng.random() < j.prob:
        quality = int(rng.integers(j.quality[0], j.quality[1] + 1))
        out = _o_apply_jpeg(out, quality)

    return out


# --------------------------------------------------------------------------------------------------
# Фикстуры и литералы.
# --------------------------------------------------------------------------------------------------

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

# Кадр 64 (ширина) x 48 (высота) -> shape (48, 64, 3).
_FRAME_U8 = np.random.default_rng(2024).integers(0, 256, (48, 64, 3), dtype=np.uint8)
_FRAME_F32 = np.random.default_rng(7).uniform(0, 255, (48, 64, 3)).astype(np.float32)
_SEEDS = range(50)


def _cfg_all_enabled() -> AugmentConfig:
    return AugmentConfig(**{n: {"enabled": True, "prob": 1.0} for n in CANONICAL_ORDER})


def _cfg_default() -> AugmentConfig:
    return AugmentConfig()


def _cfg_all_disabled() -> AugmentConfig:
    return AugmentConfig(**{n: {"enabled": False} for n in CANONICAL_ORDER})


def _cfg_only(name: str) -> AugmentConfig:
    return AugmentConfig(**{n: {"enabled": n == name, "prob": 1.0} for n in CANONICAL_ORDER})


_CONFIGS = {
    "all_enabled_prob1": _cfg_all_enabled,
    "default": _cfg_default,
    "all_disabled": _cfg_all_disabled,
}

# sha256 по байтам 50 кадров подряд (seed 0..49), снято на коде ДО задачи оракулом/старым apply_photometric.
_SHA_50_FRAMES = {
    "all_enabled_prob1": "18cd20522f0d1dd58540d6669f34a42e6bdee1d954106d5873daf9c1cda5a9bb",
    "default": "9a6e3683c2e17fcea073611ca6789aa48040db247dabbf220307d83dfd4c1923",
    "all_disabled": "4705fcf0ae956299035fdf9ab2b3218e378c1cc433c5af7fdf518e2d4193eae8",
}

# sha256 по каждой из 11 функций эффектов на фиксированных параметрах (_FRAME_F32 / uint8-копия для jpeg).
_SHA_FUNCS = {
    "apply_glare": "2a28457a9ae7d4ddb7cce96622ae1b38dbadbb86091abd4b3f4a1f0839a8c837",
    "make_motion_kernel": "63c429f68fba25fd0502b1b8c271ff9e2e15d296338b0f700d560c9f1f4ac0e2",
    "apply_motion_blur": "044805e154e5ef9080dcac14bfcac1a209e3c2f73fd0b8703b969815a7b60d39",
    "apply_brightness_contrast": "1d4049d48d6fdf993377dd279b1f0e740c39e76e1ada2c6b7591ce29fbef8b52",
    "apply_color_temperature": "e7431b0200c55623161afd9003c77c93d0813ce01e34889782de8c08084578cd",
    "apply_channel_shift": "4bb891b770f45852698710d2ee0eaf2b0be1ded75f2f32a14087935d143c183e",
    "apply_shadow": "f4b4194a0f532b16cd220286496a53dbfc959c6eef9ea7aebd39b214c9257bca",
    "apply_occlusion": "53c9154cc121e1659a9033f509089e231f8ec5084feb9e831056923f7e6e143a",
    "apply_gamma": "6a0ea78757997c5cf8f605071c7e7ec758e0053a566c42f3f11d120f9256221d",
    "apply_vignette": "4d0cd9286072456a460f70da24f5088c8649c6d97501c61f98b3e4e52b09dcfa",
    "apply_jpeg": "28255abd1a0d2500dba14085fa5b31f8b48b65607e1b3b5171cc591462c3b240",
}


def _sha(*arrays: np.ndarray) -> str:
    h = hashlib.sha256()
    for a in arrays:
        h.update(np.ascontiguousarray(a).tobytes())
    return h.hexdigest()


def _sha_of_50_frames(fn, cfg) -> str:
    return _sha(*[fn(_FRAME_U8, cfg, np.random.default_rng(seed)) for seed in _SEEDS])


def _call_funcs(ns: dict) -> dict[str, str]:
    """Фиксированные вызовы 11 функций; `ns` — словарь имя -> функция (оракул или модуль)."""
    f32 = _FRAME_F32
    u8 = _FRAME_F32.astype(np.uint8)
    return {
        "apply_glare": _sha(ns["apply_glare"](f32, (20.5, 15.0), 18.0, 80.0)),
        "make_motion_kernel": _sha(
            *[
                ns["make_motion_kernel"](length, angle)
                for length, angle in [(7, 30.0), (1, 0.0), (8, 135.0), (15, 90.0)]
            ]
        ),
        "apply_motion_blur": _sha(ns["apply_motion_blur"](f32, 5, 45.0)),
        "apply_brightness_contrast": _sha(ns["apply_brightness_contrast"](f32, 12.5, 1.2)),
        "apply_color_temperature": _sha(ns["apply_color_temperature"](f32, 0.05)),
        "apply_channel_shift": _sha(ns["apply_channel_shift"](f32, (5.0, -3.0, 10.0))),
        "apply_shadow": _sha(ns["apply_shadow"](f32, 33.0, 0.4, 0.3, 0.5)),
        "apply_occlusion": _sha(
            ns["apply_occlusion"](f32, (10, 5, 20, 15), (200.0, 100.0, 50.0)),
            ns["apply_occlusion"](f32, (-5, -5, 10, 10), (1.0, 2.0, 3.0)),  # обрезка по границе кадра
        ),
        "apply_gamma": _sha(ns["apply_gamma"](f32, 1.3)),
        "apply_vignette": _sha(ns["apply_vignette"](f32, 0.3, 0.5)),
        "apply_jpeg": _sha(ns["apply_jpeg"](u8, 70)),
    }


_ORACLE_FUNCS = {
    "apply_glare": _o_apply_glare,
    "make_motion_kernel": _o_make_motion_kernel,
    "apply_motion_blur": _o_apply_motion_blur,
    "apply_brightness_contrast": _o_apply_brightness_contrast,
    "apply_color_temperature": _o_apply_color_temperature,
    "apply_channel_shift": _o_apply_channel_shift,
    "apply_shadow": _o_apply_shadow,
    "apply_occlusion": _o_apply_occlusion,
    "apply_gamma": _o_apply_gamma,
    "apply_vignette": _o_apply_vignette,
    "apply_jpeg": _o_apply_jpeg,
}


def _norm(v):
    """Кортеж <-> список: приводим к кортежам (рекурсивно)."""
    if isinstance(v, (list, tuple)):
        return tuple(_norm(i) for i in v)
    return v


# --------------------------------------------------------------------------------------------------
# A1 — побайтная эквивалентность + состояние rng (страховочная сеть: зелёная и до, и после задачи).
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("cfg_name", list(_CONFIGS))
def test_a1_apply_photometric_equals_oracle_bytes_and_rng_state(cfg_name):
    from Services.dataset_gen.core.augment import apply_photometric

    cfg = _CONFIGS[cfg_name]()
    for seed in _SEEDS:
        rng_new, rng_old = np.random.default_rng(seed), np.random.default_rng(seed)
        out_new = apply_photometric(_FRAME_U8, cfg, rng_new)
        out_old = _oracle_apply_photometric(_FRAME_U8, cfg, rng_old)
        assert out_new.dtype == np.uint8 and out_new.shape == _FRAME_U8.shape, f"seed={seed}"
        assert out_new.tobytes() == out_old.tobytes(), f"{cfg_name} seed={seed}: кадры расходятся"
        assert rng_new.bit_generator.state == rng_old.bit_generator.state, f"{cfg_name} seed={seed}: состояние rng"


def test_a1_all_disabled_returns_copy_without_draws():
    from Services.dataset_gen.core.augment import apply_photometric

    rng = np.random.default_rng(5)
    before = rng.bit_generator.state
    out = apply_photometric(_FRAME_U8, _cfg_all_disabled(), rng)
    assert out.tobytes() == _FRAME_U8.tobytes()
    assert out is not _FRAME_U8 and not np.shares_memory(out, _FRAME_U8)
    assert rng.bit_generator.state == before


# --------------------------------------------------------------------------------------------------
# A1b — sha256-литералы: тела перенесены дословно.
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("cfg_name", list(_CONFIGS))
def test_a1b_oracle_copy_matches_literal(cfg_name):
    """Контроль самого оракула: копия в этом файле == литерал, снятый на коде до задачи."""
    assert _sha_of_50_frames(_oracle_apply_photometric, _CONFIGS[cfg_name]()) == _SHA_50_FRAMES[cfg_name]


@pytest.mark.parametrize("cfg_name", list(_CONFIGS))
def test_a1b_apply_photometric_50_frames_sha_literal(cfg_name):
    from Services.dataset_gen.core.augment import apply_photometric

    assert _sha_of_50_frames(apply_photometric, _CONFIGS[cfg_name]()) == _SHA_50_FRAMES[cfg_name]


def test_a1b_oracle_function_copies_match_literals():
    """Контроль копий функций-оракулов: те же вызовы на копиях дают литералы."""
    assert _call_funcs(_ORACLE_FUNCS) == _SHA_FUNCS


@pytest.mark.parametrize("name", list(_SHA_FUNCS))
def test_a1b_effect_function_sha_literal(name):
    import Services.dataset_gen.core.augment as aug

    got = _call_funcs({n: getattr(aug, n) for n in _SHA_FUNCS})
    assert got[name] == _SHA_FUNCS[name]


@pytest.mark.parametrize("name", list(_SHA_FUNCS))
def test_a1b_effect_function_sha_literal_via_layer_render(name):
    """После переезда тела живут в layer_render.effects — те же литералы (красный до задачи)."""
    import Services.layer_render.effects as fx

    got = _call_funcs({n: getattr(fx, n) for n in _SHA_FUNCS})
    assert got[name] == _SHA_FUNCS[name]


# --------------------------------------------------------------------------------------------------
# A4 — EFFECT_PARAMS равен полям AugmentConfig (кроме enabled/prob).
# --------------------------------------------------------------------------------------------------


def test_a4_effect_params_keys_are_exactly_the_12_effects():
    from Services.layer_render.effects import EFFECT_PARAMS

    assert set(EFFECT_PARAMS) == set(CANONICAL_ORDER)


@pytest.mark.parametrize("name", CANONICAL_ORDER)
def test_a4_effect_params_equal_augment_config_fields(name):
    from Services.layer_render.effects import EFFECT_PARAMS

    expected = getattr(AugmentConfig(), name).model_dump(exclude={"enabled", "prob"})
    assert _norm(dict(EFFECT_PARAMS[name])) == _norm(expected)


# Литералы ключей: ловят «пустой» EFFECT_PARAMS у обоих сторон одновременно (сравнение выше — с моделью).
_PARAM_KEYS_LITERAL = {
    "glare": {"intensity", "radius_frac"},
    "shadow": {"strength", "softness_frac"},
    "occlusion": {"count", "size_frac"},
    "gaussian_blur": {"sigma"},
    "motion_blur": {"length"},
    "vignette": {"strength", "radius_frac"},
    "brightness_contrast": {"brightness", "contrast"},
    "gamma": {"gamma"},
    "color_temperature": {"shift"},
    "channel_shift": {"max_shift"},
    "noise": {"std"},
    "jpeg": {"quality"},
}


@pytest.mark.parametrize("name", CANONICAL_ORDER)
def test_a4_effect_params_key_set_literal(name):
    from Services.layer_render.effects import EFFECT_PARAMS

    assert set(EFFECT_PARAMS[name]) == _PARAM_KEYS_LITERAL[name]


# --------------------------------------------------------------------------------------------------
# augment_config_to_effects (DESIGN; в acceptance входит косвенно через A1).
# --------------------------------------------------------------------------------------------------


def test_config_to_effects_default_config_enabled_only_in_canonical_order_with_probs():
    from Services.dataset_gen.core.augment import augment_config_to_effects

    specs = augment_config_to_effects(AugmentConfig())
    # По умолчанию включены 4 фотометрических эффекта; порядок — канонический, а не порядок полей AugmentConfig.
    assert [s.name for s in specs] == ["gaussian_blur", "brightness_contrast", "color_temperature", "noise"]
    assert [s.prob for s in specs] == [0.5, 1.0, 0.5, 0.7]
    assert _norm(dict(specs[0].params)) == {"sigma": (0.4, 1.8)}
    assert _norm(dict(specs[3].params)) == {"std": (2.0, 10.0)}


def test_config_to_effects_all_disabled_is_empty_list():
    from Services.dataset_gen.core.augment import augment_config_to_effects

    assert augment_config_to_effects(_cfg_all_disabled()) == []


def test_config_to_effects_all_enabled_gives_all_12_in_canonical_order_geometry_excluded():
    from Services.dataset_gen.core.augment import augment_config_to_effects

    specs = augment_config_to_effects(_cfg_all_enabled())
    assert [s.name for s in specs] == CANONICAL_ORDER
    assert all(s.prob == 1.0 for s in specs)
    # Геометрия (rotation/scale/shift/contact_shadow) включена по умолчанию у rotation/shift/scale — в список не входит.
    assert not {"rotation", "scale", "shift", "contact_shadow"} & {s.name for s in specs}


def test_config_to_effects_passes_custom_prob_and_params():
    from Services.dataset_gen.core.augment import augment_config_to_effects

    cfg = AugmentConfig(
        noise={"enabled": True, "prob": 0.25, "std": (1.0, 2.0)},
        gaussian_blur={"enabled": False},
        brightness_contrast={"enabled": False},
        color_temperature={"enabled": False},
    )
    (spec,) = augment_config_to_effects(cfg)
    assert spec.name == "noise"
    assert spec.prob == 0.25
    assert _norm(dict(spec.params)) == {"std": (1.0, 2.0)}


def test_config_to_effects_drives_apply_photometric_with_custom_params():
    """Нестандартные параметры доходят до сэмплинга: узкий диапазон шума меняет побайтный результат оракула."""
    from Services.dataset_gen.core.augment import apply_photometric

    cfg = AugmentConfig(
        noise={"enabled": True, "prob": 1.0, "std": (30.0, 31.0)},
        gaussian_blur={"enabled": False},
        brightness_contrast={"enabled": False},
        color_temperature={"enabled": False},
    )
    for seed in range(5):
        a = apply_photometric(_FRAME_U8, cfg, np.random.default_rng(seed))
        b = _oracle_apply_photometric(_FRAME_U8, cfg, np.random.default_rng(seed))
        assert a.tobytes() == b.tobytes(), f"seed={seed}"


# --------------------------------------------------------------------------------------------------
# Покэффектный реестр EFFECTS[name](frame, params, rng): тот же поток rng и тот же кадр, что у блока оракула.
# Локализует поломку (TRAPS: shadow-порядок kwargs, occlusion 6 вызовов на прямоугольник, noise dtype/форма).
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("name", CANONICAL_ORDER)
def test_registry_entry_matches_oracle_block_and_rng_state(name):
    from Services.layer_render.effects import EFFECT_PARAMS, EFFECTS

    cfg = _cfg_only(name)
    for seed in range(20):
        rng_old = np.random.default_rng(seed)
        expected = _oracle_apply_photometric(_FRAME_U8, cfg, rng_old)

        rng_new = np.random.default_rng(seed)
        rng_new.random()  # розыгрыш prob делает apply_effects, запись реестра его не делает
        if name == "jpeg":
            frame = _FRAME_U8.copy()  # U8-эффект получает clip->uint8
            got = EFFECTS[name](frame, EFFECT_PARAMS[name], rng_new)
        else:
            got = np.clip(EFFECTS[name](_FRAME_U8.astype(np.float32), EFFECT_PARAMS[name], rng_new), 0, 255).astype(
                np.uint8
            )
        assert got.tobytes() == expected.tobytes(), f"{name} seed={seed}: кадр"
        assert rng_new.bit_generator.state == rng_old.bit_generator.state, f"{name} seed={seed}: состояние rng"
