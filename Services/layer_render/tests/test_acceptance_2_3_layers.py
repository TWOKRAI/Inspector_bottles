"""Task 2.3 (слепой тест тестера): `Services/layer_render/layers.py` — `compose_layers`, `transform_layer`,
`load_layer_sprite`, `canvas_size`, `LayerSpec`/`LayerAugment`; `LayeredObject` остаётся обёрткой.

Пишется по acceptance-критериям A1, A2, A4, A4b, A5, A6, A7 и DESIGN плана `layer-render/phase-2-core.md`
(раздел «Task 2.3»). Реализации в дереве нет по построению (worktree на коммите до кода).

ЗЕЛЁНЫЕ ДО ЗАДАЧИ (страховочная сеть — снимки литералов на коде ДО переноса; после задачи обязаны остаться зелёными):
  * A1  `LayeredObject(...).render()` sha256 + `layer_params`/`defect` — 7 стеков x 3 seed
  * A4  `LayeredObject._transform` — идентичность при нулевом трансформе, копия при любом одном ненулевом,
        sha256 на (0.9, 37.0, 30.0, (10, 20, 30))
  * A5  (часть через `LayeredObject`) read-only, провайдер ровно раз, spawn родительского rng
  * A6  тексты и типы ошибок через `LayeredObject` (точные литералы)
  * ловушки: `color_rgb` defect-слоя до `continue`, `hue_deg == 0.0` без HSV-округления
  * A7  AST по уже существующим файлам `layer_render` (пакет не тянет запрещённые корни)
КРАСНЫЕ ДО ЗАДАЧИ (новый API — `ImportError`/`AttributeError`/`ModuleNotFoundError`, импорт внутри каждого теста):
  * A2  `compose_layers` напрямую на тех же входах -> те же sha256 и `layer_params`
  * A4  тождества `is` между `line_sim` и `layer_render.layers`, `transform_layer`, `canvas_size`, `load_layer_sprite`
  * A4b `__all__` (11 имён), реэкспорты `Services.line_sim.*`
  * A5  детерминизм/чистота/writeable у `compose_layers`; `ComposedLayers`
  * A6  те же ошибки через `compose_layers(..., label=...)`
  * A7  `layers.py` существует, входит в сканируемый набор, не импортирует запрещённое (в т.ч. в рантайме)

Ожидаемые значения — литералы, снятые одноразовым скриптом на коде ДО задачи (Python 3.12, numpy 2.x, opencv 4.13);
в тесте они не вычисляются из проверяемого кода. Входы детерминированы: спрайты из `np.random.default_rng(<seed>)`,
файлов с диска нет.
"""

from __future__ import annotations

import ast
import hashlib
import importlib
import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

_ROOT = Path(__file__).resolve().parents[3]
_LAYER_RENDER = _ROOT / "Services" / "layer_render"

_SEEDS = (0, 7, 2025)

# Одиннадцать имён Module contract (A4b).
_CONTRACT_NAMES = (
    "LayerMode",
    "RangeF",
    "SpriteSource",
    "AUGMENT_FIELDS",
    "LayerAugment",
    "LayerSpec",
    "ComposedLayers",
    "load_layer_sprite",
    "transform_layer",
    "canvas_size",
    "compose_layers",
)

# ---------------------------------------------------------------------------------------------------------------
# Входы (детерминированы, без файлов)
# ---------------------------------------------------------------------------------------------------------------


def _sprite(seed: int, h: int, w: int) -> np.ndarray:
    """RGBA uint8 HxWx4 из `default_rng(seed)`: случайные цвета, альфа 255 на ~80% пикселей, прочие 0..199."""
    rng = np.random.default_rng(seed)
    rgb = rng.integers(0, 256, size=(h, w, 3), dtype=np.uint8)
    mask = rng.random((h, w)) < 0.8
    alpha = np.where(mask, 255, rng.integers(0, 200, size=(h, w))).astype(np.uint8)
    return np.dstack([rgb, alpha])


def _sha(arr: np.ndarray) -> str:
    return hashlib.sha256(np.ascontiguousarray(arr).tobytes()).hexdigest()


def _params_sha(params: dict) -> str:
    return hashlib.sha256(json.dumps(params, sort_keys=True).encode("utf-8")).hexdigest()


def _specs():
    """Конструкторы `LayerSpec`/`LayerAugment` из ТЕКУЩЕГО места (`line_sim.interfaces`) — тот же класс, что после
    задачи (A4 это пин) — поэтому снимки A1 живут на старом коде и проверяются на новом без правки."""
    from Services.line_sim.interfaces import LayerAugment, LayerSpec

    return LayerSpec, LayerAugment


def _stack(case: str):
    """Стек слоёв `case` -> `(layers, object_angle_deg, forced_defect_string_or_None)`. Каждый вызов — свежие
    массивы/объекты, чтобы мутация в одном тесте не протекла в другой."""
    LayerSpec, LayerAugment = _specs()
    base = LayerSpec(name="base", mode="static", sprite_source=_sprite(11, 24, 16))
    if case == "static_one":
        return [base], 0.0, None
    label_aug = LayerAugment(
        offset_x_px=(-2.0, 2.0),
        offset_y_px=(-1.0, 1.0),
        angle_deg=(-15.0, 15.0),
        scale=(0.8, 1.2),
        hue_shift_deg=(-30.0, 30.0),
    )
    label_arr = _sprite(12, 8, 10)
    label = LayerSpec(
        name="label",
        mode="augmented",
        sprite_source=lambda: label_arr,  # callable-провайдер на пути A1
        offset_px=(3.0, -2.0),
        angle_deg=5.0,
        augment=label_aug,
    )
    if case == "static_augmented":
        return [base, label], 0.0, None
    if case == "angle90":
        return [base, label], 90.0, None
    if case == "angle37":
        return [base, label], 37.0, None
    if case == "augmented_hue_color":
        tint = LayerSpec(
            name="tint",
            mode="augmented",
            sprite_source=_sprite(13, 10, 10),
            offset_px=(1.0, 1.0),
            scale=1.1,
            augment=LayerAugment(
                offset_x_px=(-3.0, 3.0),
                offset_y_px=(-3.0, 3.0),
                angle_deg=(-10.0, 10.0),
                scale=(0.9, 1.1),
                hue_shift_deg=(-60.0, 60.0),
            ),
            color_rgb=(200, 40, 40),
        )
        flat = LayerSpec(
            name="flat", mode="static", sprite_source=_sprite(14, 6, 6), offset_px=(-4.0, 2.0), color_rgb=(13, 77, 201)
        )
        return [base, tint, flat], 0.0, None
    scratch = LayerSpec(
        name="scratch", mode="defect", sprite_source=_sprite(15, 6, 12), offset_px=(2.0, 3.0), defect_probability=0.5
    )
    stain = LayerSpec(
        name="stain",
        mode="defect",
        sprite_source=_sprite(16, 9, 9),
        offset_px=(-3.0, -2.0),
        defect_probability=0.5,
        color_rgb=(200, 17, 99),
    )
    if case == "defect_p05":
        return [base, scratch, stain], 0.0, None
    if case == "forced_defect":
        never = replace_p(scratch, 0.0)
        never_stain = replace_p(stain, 0.0)
        # Порядок в строке не совпадает с порядком слоёв, есть пробел: разбор строки — в обёртке (strip/split).
        return [base, label, never, never_stain], 0.0, "stain, scratch"
    raise KeyError(case)


def replace_p(layer, p: float):
    """Копия `LayerSpec` с другой `defect_probability` (frozen-модель)."""
    return layer.model_copy(update={"defect_probability": p})


_CASES = (
    "static_one",
    "static_augmented",
    "augmented_hue_color",
    "defect_p05",
    "forced_defect",
    "angle90",
    "angle37",
)


def _passport(object_id: str = "obj-1", angle_deg: float = 0.0, defect: str | None = None):
    from Services.line_sim.interfaces import ObjectPassport

    return ObjectPassport(
        object_id=object_id, class_name="bottle", angle_deg=angle_deg, defect=defect, spawn_encoder=0.0
    )


def _layered(case: str, seed: int):
    """`LayeredObject` на стеке `case`, seed `seed` (текущий публичный путь)."""
    from Services.line_sim.core.layered_object import LayeredObject

    layers, angle, forced = _stack(case)
    return LayeredObject(_passport(angle_deg=angle, defect=forced), layers, np.random.default_rng(seed))


def _composed(case: str, seed: int):
    """`compose_layers` напрямую на ТЕХ ЖЕ входах, что `_layered` (A2)."""
    layers_mod = importlib.import_module("Services.layer_render.layers")
    layers, angle, forced = _stack(case)
    names = [n.strip() for n in (forced or "").split(",") if n.strip()]
    return layers_mod.compose_layers(layers, np.random.default_rng(seed), angle, tuple(names))


# ---------------------------------------------------------------------------------------------------------------
# Снимки A1 (литералы, снятые на коде ДО задачи). {(case, seed): (rgba_sha256, shape, params_sha256, defect)}
# ---------------------------------------------------------------------------------------------------------------

_A1: dict = {
    ("static_one", 0): (
        "901675d18ba3111dccb5e513d0342f1781405e1d6d2bdecb3b2252381b97077b",
        (24, 16, 4),
        "44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a",
        None,
    ),
    ("static_one", 7): (
        "901675d18ba3111dccb5e513d0342f1781405e1d6d2bdecb3b2252381b97077b",
        (24, 16, 4),
        "44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a",
        None,
    ),
    ("static_one", 2025): (
        "901675d18ba3111dccb5e513d0342f1781405e1d6d2bdecb3b2252381b97077b",
        (24, 16, 4),
        "44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a",
        None,
    ),
    ("static_augmented", 0): (
        "2f5197425fc62fc3d4654c5aa891b12b4f9643265821ba6e0adeb7f429e7440a",
        (24, 20, 4),
        "d73dfed6fdd8143a33a555efb89d6a6a2e9c4f2aa8a1679f4c7feb7698345259",
        None,
    ),
    ("static_augmented", 7): (
        "c8d4a7199e939a820da971aa8af4b6afa48a986fe0609f1df71ba419652248da",
        (24, 16, 4),
        "2515ce5c8ae8d1acad7a2957c82264a642df78a6f7d0c10c9d70850ad9e0c260",
        None,
    ),
    ("static_augmented", 2025): (
        "70e591bc723b0cdee7b98bb6b109221d0824919ea960d8489b4a9cb6a4b9d175",
        (24, 22, 4),
        "f9909fc9f6975b4d894a5de52c5deea2a9bd3994bfdb2f205a7989b800a42dce",
        None,
    ),
    ("augmented_hue_color", 0): (
        "546844962056860e81d2f9eb80a72c6d550e9781888f81f2dda90c0a57e5155b",
        (24, 18, 4),
        "0843d0d8344d3d789761e2ab16a00024f1e9f7062bba1a03b0ec86811d9dcc99",
        None,
    ),
    ("augmented_hue_color", 7): (
        "c2eb45c85fecd2067f251641added944e9824acace3f1299891806d927dd966c",
        (24, 16, 4),
        "8acab327065a103de81b0e53603b85bb5419f951fb3a1a02a303fdbfad36b956",
        None,
    ),
    ("augmented_hue_color", 2025): (
        "4f794bc83836dd7ca9905ceaf83b1a9513ce363672d25b7759687ec8d8a7ed16",
        (24, 18, 4),
        "3f26313d9a289b61f78c517d6d4efb44de53e3768e90e3b281a0c45a526bdf54",
        None,
    ),
    ("defect_p05", 0): (
        "901675d18ba3111dccb5e513d0342f1781405e1d6d2bdecb3b2252381b97077b",
        (24, 16, 4),
        "58d2fbffa302e4f78ad3ab28191ea12aeadb15c93bf7c447ede3c8284ed3561f",
        None,
    ),
    ("defect_p05", 7): (
        "da5ac2745f37150c1ae31d073de6f0e74d94ebb2188e79383270dcb658cca132",
        (24, 16, 4),
        "76513a075abfafb8d156cb933b24a435837e9c1e1b827a38f25515676915b035",
        "scratch",
    ),
    ("defect_p05", 2025): (
        "901675d18ba3111dccb5e513d0342f1781405e1d6d2bdecb3b2252381b97077b",
        (24, 16, 4),
        "58d2fbffa302e4f78ad3ab28191ea12aeadb15c93bf7c447ede3c8284ed3561f",
        None,
    ),
    ("forced_defect", 0): (
        "1de5218c7faecb0d8433d5abf3f79d2c425e2cb3648d6a205421dc1ce3101f09",
        (24, 20, 4),
        "03ce95eda35e236f8e2da2776180b2ee2d0db6a077c7524fdf13f8762876d051",
        "scratch,stain",
    ),
    ("forced_defect", 7): (
        "9f5ee3d76cf291f60987ea39bc117ea36348c4aeeaeab6af1063de4bc0f862ec",
        (24, 16, 4),
        "64976f48f2a581d0c6a5382f10b73a243df0e8acf740d2c4a2ea089fce3f935a",
        "scratch,stain",
    ),
    ("forced_defect", 2025): (
        "17ff0ed708f78cb69d29b9d3a91c5da4a0afed3b17a7d470b47105e5660975ce",
        (24, 22, 4),
        "a4885d281d65a2458f054fc853b3bfe6703c7e8f3f512c213e82317dadc99699",
        "scratch,stain",
    ),
    ("angle90", 0): (
        "e30e2cda15516c7c427ebe9e50ef1affb9108493917f7c73b4b96f71735a1e47",
        (20, 24, 4),
        "d73dfed6fdd8143a33a555efb89d6a6a2e9c4f2aa8a1679f4c7feb7698345259",
        None,
    ),
    ("angle90", 7): (
        "33c512b963d1f585babb0f3a100faa62d879b4054043cd9025576426d3cde87d",
        (16, 24, 4),
        "2515ce5c8ae8d1acad7a2957c82264a642df78a6f7d0c10c9d70850ad9e0c260",
        None,
    ),
    ("angle90", 2025): (
        "c7e35b278fe349783d50d8e3a91ae430d4f75d36763a9b0ce74e942e7156092b",
        (22, 24, 4),
        "f9909fc9f6975b4d894a5de52c5deea2a9bd3994bfdb2f205a7989b800a42dce",
        None,
    ),
    ("angle37", 0): (
        "bcac20d60e3ebb71dc6570cf825fbc57a0f7d7bdbe7643fc760a862012e629cb",
        (32, 31, 4),
        "d73dfed6fdd8143a33a555efb89d6a6a2e9c4f2aa8a1679f4c7feb7698345259",
        None,
    ),
    ("angle37", 7): (
        "a94b7b86fac954d103d22bef2e0b12bf2187277f428d7204724203e0543b739c",
        (29, 28, 4),
        "2515ce5c8ae8d1acad7a2957c82264a642df78a6f7d0c10c9d70850ad9e0c260",
        None,
    ),
    ("angle37", 2025): (
        "c77fa0619f3aa25297667682969a9ff7882d730e366b9da114aade8795bad9fc",
        (33, 33, 4),
        "f9909fc9f6975b4d894a5de52c5deea2a9bd3994bfdb2f205a7989b800a42dce",
        None,
    ),
}

_PARAMS = [(c, s) for c in _CASES for s in _SEEDS]


def _ids(p):
    return f"{p[0]}-s{p[1]}"


# ---------------------------------------------------------------------------------------------------------------
# A1 — страховочная сеть: LayeredObject (ЗЕЛЁНЫЙ до и после задачи)
# ---------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("case,seed", _PARAMS, ids=[_ids(p) for p in _PARAMS])
def test_a1_layered_object_render_sha256_unchanged(case, seed):
    """A1: побайтный RGBA `LayeredObject.render()` на 7 стеках x 3 seed не меняется после переноса.
    Ловит: любое «попутное улучшение» (смена порядка `uniform`, `spawn` не по индексу, округление вместо
    премультипликации, interpolation вместо `rot90`, лишний `+0.5` при распремультипликации)."""
    sha, shape, _, _ = _A1[(case, seed)]
    rgba = _layered(case, seed).render()
    assert (_sha(rgba), rgba.shape) == (sha, shape)


@pytest.mark.parametrize("case,seed", _PARAMS, ids=[_ids(p) for p in _PARAMS])
def test_a1_layered_object_passport_params_and_defect_unchanged(case, seed):
    """A1: `passport.layer_params` и `passport.defect` после задачи прежние (sha канонического JSON + литерал defect).
    Ловит: потерю `color_rgb` в `layer_params`, смену набора ключей, порядка имён в `defect`."""
    _, _, params_sha, defect = _A1[(case, seed)]
    passport = _layered(case, seed).passport
    assert _params_sha(passport.layer_params) == params_sha
    assert passport.defect == defect


# ---------------------------------------------------------------------------------------------------------------
# A2 — compose_layers напрямую (КРАСНЫЙ до задачи)
# ---------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("case,seed", _PARAMS, ids=[_ids(p) for p in _PARAMS])
def test_a2_compose_layers_rgba_matches_a1_snapshot(case, seed):
    """A2: `compose_layers` на тех же входах даёт тот же RGBA, что A1. Ловит: функцию, которая считает иначе, чем
    прежний `LayeredObject.__init__` (другой rng-путь, другой порядок слоёв, `_compose` вне функции)."""
    sha, shape, _, _ = _A1[(case, seed)]
    out = _composed(case, seed)
    assert (_sha(out.rgba), out.rgba.shape) == (sha, shape)


@pytest.mark.parametrize("case,seed", _PARAMS, ids=[_ids(p) for p in _PARAMS])
def test_a2_compose_layers_params_and_active_defects_match_a1_snapshot(case, seed):
    """A2: `layer_params` как в A1; `active_defects` — кортеж имён активных defect-слоёв в порядке слоёв (склеен
    через запятую = `passport.defect` из A1). Ловит: список вместо кортежа, порядок по `forced_defects`, не по слоям."""
    _, _, params_sha, defect = _A1[(case, seed)]
    out = _composed(case, seed)
    assert _params_sha(out.layer_params) == params_sha
    assert isinstance(out.active_defects, tuple)
    assert (",".join(out.active_defects) or None) == defect


# ---------------------------------------------------------------------------------------------------------------
# Общий раннер: один и тот же сценарий через LayeredObject (зелёный до задачи) и compose_layers (красный до задачи)
# ---------------------------------------------------------------------------------------------------------------

_RUNNERS = [
    pytest.param("LayeredObject", id="LayeredObject[green]"),
    pytest.param("compose_layers", id="compose_layers[red]"),
]


def _run(runner: str, layers, seed: int = 0, forced=(), angle: float = 0.0, object_id: str = "obj-1", rng=None):
    """-> `(layer_params, active_defects: tuple[str, ...], rgba)`. `forced` — имена принудительных дефектов."""
    rng = np.random.default_rng(seed) if rng is None else rng
    if runner == "LayeredObject":
        from Services.line_sim.core.layered_object import LayeredObject

        obj = LayeredObject(_passport(object_id, angle, ", ".join(forced) or None), layers, rng)
        defect = obj.passport.defect
        return obj.passport.layer_params, tuple(defect.split(",")) if defect else (), obj.render()
    mod = importlib.import_module("Services.layer_render.layers")
    out = mod.compose_layers(layers, rng, angle, tuple(forced), label=object_id)
    return out.layer_params, out.active_defects, out.rgba


# ---------------------------------------------------------------------------------------------------------------
# A6 — ошибки: прежний тип и точный текст (литералы, снятые через LayeredObject на коде ДО задачи)
# ---------------------------------------------------------------------------------------------------------------

_E_STRING = (
    "TypeError",
    "слой 'a': sprite_source='some_id' — строка-идентификатор; загрузка спрайта по id — Task 3.2, делает "
    "ObjectFactory (Services.line_sim.core.factory), сюда нужен RGBA-массив или callable",
)
_E_RGB = (
    "ValueError",
    "слой 'a': ожидался RGBA uint8 HxWx4, получено shape=(4, 4, 3) dtype=uint8 (нет альфа-канала?)",
)
_E_FLOAT = (
    "ValueError",
    "слой 'a': ожидался RGBA uint8 HxWx4, получено shape=(4, 4, 4) dtype=float32 (нет альфа-канала?)",
)
_E_GRAY = (
    "ValueError",
    "слой 'a': ожидался RGBA uint8 HxWx4, получено shape=(4, 4) dtype=uint8 (нет альфа-канала?)",
)
_E_DUPES = (
    "ValueError",
    "LayeredObject 'obj-1': имена слоёв повторяются ['a'] — layer_params и defect адресуют слой по имени",
)
_E_UNKNOWN = (
    "ValueError",
    "LayeredObject 'obj-1': defect=['nope', 'ghost'] — нет таких defect-слоёв (есть: ['scratch', 'zz'])",
)
_E_UNKNOWN_NONE = (
    "ValueError",
    "LayeredObject 'obj-1': defect=['nope', 'ghost'] — нет таких defect-слоёв (есть: [])",
)
_E_CLEAR = ("ValueError", "LayeredObject 'obj-1': итоговый RGBA полностью прозрачен")

_ERRORS = {
    "empty": ("ValueError", "LayeredObject 'obj-1': пустой список слоёв — нечего рисовать"),
    "string_source": _E_STRING,
    "rgb_sprite": _E_RGB,
    "float_sprite": _E_FLOAT,
    "gray_sprite": _E_GRAY,
    "duplicates": _E_DUPES,
    "unknown_forced": _E_UNKNOWN,
    "transparent": _E_CLEAR,
    # приоритеты проверок: пустой -> спрайты -> дубли -> неизвестный дефект -> розыгрыш -> прозрачный
    "sprite_error_beats_duplicates": _E_RGB,
    "sprite_error_beats_unknown_forced": _E_RGB,
    "duplicates_beat_unknown_forced": _E_DUPES,
    "unknown_forced_beats_transparent": _E_UNKNOWN_NONE,
}


def _err_inputs(name: str):
    """-> `(layers, forced_names)` для ошибочного сценария `name`."""
    LayerSpec, _ = _specs()

    def static(n, src):
        return LayerSpec(name=n, mode="static", sprite_source=src)

    def defect(n):
        return LayerSpec(name=n, mode="defect", sprite_source=_sprite(3, 4, 4))

    ok = _sprite(1, 4, 4)
    rgb = np.zeros((4, 4, 3), np.uint8)
    clear = np.zeros((4, 4, 4), np.uint8)
    table = {
        "empty": ([], ()),
        "string_source": ([static("a", "some_id")], ()),
        "rgb_sprite": ([static("a", rgb)], ()),
        "float_sprite": ([static("a", np.zeros((4, 4, 4), np.float32))], ()),
        "gray_sprite": ([static("a", np.zeros((4, 4), np.uint8))], ()),
        "duplicates": ([static("a", ok), static("a", ok), static("b", ok)], ()),
        "unknown_forced": ([static("a", ok), defect("scratch"), defect("zz")], ("nope", "ghost")),
        "transparent": ([static("a", clear)], ()),
        "sprite_error_beats_duplicates": ([static("a", ok), static("a", rgb)], ()),
        "sprite_error_beats_unknown_forced": ([static("a", rgb), defect("scratch")], ("nope",)),
        "duplicates_beat_unknown_forced": ([static("a", ok), static("a", ok)], ("nope", "ghost")),
        "unknown_forced_beats_transparent": ([static("a", clear)], ("nope", "ghost")),
    }
    return table[name]


def _caught(fn):
    """-> `(имя типа исключения, текст)`; не бросило — тест падает (а не молча зеленеет)."""
    try:
        fn()
    except Exception as exc:  # noqa: BLE001 — тест сверяет тип и текст любой ошибки
        return type(exc).__name__, str(exc)
    pytest.fail("ожидалась ошибка, вызов завершился без исключения")


@pytest.mark.parametrize("name", list(_ERRORS))
@pytest.mark.parametrize("runner", _RUNNERS)
def test_a6_error_type_and_text_unchanged(runner, name):
    """A6: тип и точный текст каждой ошибки прежние (через LayeredObject — прежний путь; через compose_layers с
    `label="obj-1"` — тот же текст побайтно). Ловит: переписанный текст, другой тип (`TypeError`<->`ValueError`),
    другой приоритет проверок (прозрачность раньше дублей и т. п.), потерю префикса `LayeredObject '<id>':`."""
    layers, forced = _err_inputs(name)
    assert _caught(lambda: _run(runner, layers, forced=forced)) == _ERRORS[name]


@pytest.mark.parametrize(
    "name", [n for n in _ERRORS if n not in ("empty",) and _ERRORS[n][1].startswith("LayeredObject 'obj-1'")]
)
def test_a6_compose_layers_label_replaces_object_id_in_text(name):
    """A6: `label="X"` стоит на месте `passport.object_id` — текст тот же с `'X'` вместо `'obj-1'`, префикс
    `LayeredObject 'X':` остаётся. Ловит: константный `''` вместо метки, label в конце текста, потерю кавычек."""
    layers, forced = _err_inputs(name)
    kind, text = _ERRORS[name]
    got = _caught(lambda: _run("compose_layers", layers, forced=forced, object_id="X"))
    assert got == (kind, text.replace("'obj-1'", "'X'"))
    assert got[1].startswith("LayeredObject 'X':")


def test_a6_compose_layers_empty_list_names_the_label():
    """A6: пустой список через `compose_layers(..., label="X")` — `"'X'" in str(e)`, тип `ValueError`."""
    kind, text = _caught(lambda: _run("compose_layers", [], object_id="X"))
    assert kind == "ValueError"
    assert text == "LayeredObject 'X': пустой список слоёв — нечего рисовать"


def test_a6_sprite_errors_name_the_layer_not_the_object():
    """A6: ошибки спрайта называют слой, а не объект — метка в текст не попадает. Ловит: оборачивание ошибок
    загрузки спрайта в префикс объекта (смена текста A6)."""
    layers, _ = _err_inputs("rgb_sprite")
    _, text = _caught(lambda: _run("compose_layers", layers, object_id="X"))
    assert "'X'" not in text
    assert text.startswith("слой 'a':")


@pytest.mark.parametrize("name", ["duplicates", "unknown_forced"])
@pytest.mark.parametrize("runner", _RUNNERS)
def test_a6_checks_fail_before_any_rng_draw(runner, name):
    """DESIGN: проверки (дубли, неизвестный дефект) идут ДО розыгрыша — родительский rng не тронут
    (`n_children_spawned == 0`). Ловит: `rng.spawn` выше проверок (ошибка оставляет вызывающему сдвинутый rng)."""
    layers, forced = _err_inputs(name)
    rng = np.random.default_rng(3)
    assert _caught(lambda: _run(runner, layers, forced=forced, rng=rng))[0] == "ValueError"
    assert rng.bit_generator.seed_seq.n_children_spawned == 0


def _counting_stack():
    """Слои с callable-провайдерами и счётчиками вызовов: static, augmented, defect p=0.5, defect p=0.0."""
    LayerSpec, LayerAugment = _specs()
    counts = [0, 0, 0, 0]

    def provider(i, seed, h, w):
        def call():
            counts[i] += 1
            return _sprite(seed, h, w)

        return call

    layers = [
        LayerSpec(name="s", mode="static", sprite_source=provider(0, 31, 12, 12)),
        LayerSpec(
            name="g",
            mode="augmented",
            sprite_source=provider(1, 32, 6, 6),
            augment=LayerAugment(offset_x_px=(-1.0, 1.0)),
        ),
        LayerSpec(name="d1", mode="defect", sprite_source=provider(2, 33, 4, 4), defect_probability=0.5),
        LayerSpec(name="d2", mode="defect", sprite_source=provider(3, 34, 4, 4), defect_probability=0.0),
    ]
    return layers, counts


@pytest.mark.parametrize("runner", _RUNNERS)
def test_a5_provider_called_exactly_once_per_layer_including_inactive_defects(runner):
    """A5: callable-провайдер зовётся ровно один раз на слой (в т. ч. на невыпавший defect-слой). Ловит: ленивую
    загрузку только активных слоёв, повторный вызов при трансформе/композиции."""
    layers, counts = _counting_stack()
    _run(runner, layers, seed=0)
    assert counts == [1, 1, 1, 1]


@pytest.mark.parametrize("runner", _RUNNERS)
def test_a6_providers_called_once_each_even_when_duplicates_raise(runner):
    """A6/DESIGN: спрайты грузятся ДО проверки дублей — к моменту ошибки каждый провайдер вызван ровно раз.
    Ловит: проверку дублей перед загрузкой спрайтов (другой приоритет ошибок и другой счёт вызовов)."""
    LayerSpec, _ = _specs()
    counts = [0, 0, 0]

    def provider(i):
        def call():
            counts[i] += 1
            return _sprite(40 + i, 4, 4)

        return call

    layers = [LayerSpec(name=n, mode="static", sprite_source=provider(i)) for i, n in enumerate("aab")]
    assert _caught(lambda: _run(runner, layers))[0] == "ValueError"
    assert counts == [1, 1, 1]


# ---------------------------------------------------------------------------------------------------------------
# A5 — детерминизм, чистота, writeable
# ---------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("case", ["augmented_hue_color", "defect_p05"])
def test_a5_compose_layers_same_seed_twice_gives_identical_bytes_and_params(case):
    """A5: два вызова `compose_layers` с одним seed — побайтно тот же RGBA и те же `layer_params`/`active_defects`.
    Ловит: скрытое глобальное состояние (глобальный rng, счётчик, кэш между вызовами)."""
    first = _composed(case, 7)
    second = _composed(case, 7)
    assert first.rgba.tobytes() == second.rgba.tobytes()
    assert first.layer_params == second.layer_params
    assert first.active_defects == second.active_defects


def test_a5_compose_layers_result_arrays_are_independent_between_calls():
    """A5: два вызова — два разных массива; запись в один не видна в другом. Ловит: возврат закэшированного
    массива/общей канвы (функция не знает про кэш — кэш у обёртки)."""
    first = _composed("static_augmented", 0)
    second = _composed("static_augmented", 0)
    assert first.rgba is not second.rgba
    before = second.rgba.tobytes()
    first.rgba[:] = 0
    assert second.rgba.tobytes() == before


@pytest.mark.parametrize("case", ["static_one", "static_augmented"])
def test_a5_compose_layers_rgba_is_writeable(case):
    """A5: `compose_layers(...).rgba.flags.writeable is True` (read-only ставит обёртка). Ловит: преждевременный
    `writeable = False` внутри функции и возврат read-only-вида кэша."""
    assert _composed(case, 0).rgba.flags.writeable is True


@pytest.mark.parametrize("case", ["static_one", "defect_p05"])
def test_a5_layered_object_render_is_one_readonly_array(case):
    """A5: `LayeredObject.render()` — один и тот же read-only массив; запись в него запрещена. Ловит: потерю
    `writeable = False` при переносе в обёртку (кэш объекта портится через ссылку)."""
    obj = _layered(case, 0)
    rgba = obj.render()
    assert rgba is obj.render()
    assert rgba.flags.writeable is False
    with pytest.raises(ValueError, match="read-only"):
        rgba[0, 0, 0] = 1


@pytest.mark.parametrize("case", ["augmented_hue_color", "defect_p05"])
@pytest.mark.parametrize("runner", _RUNNERS)
def test_a5_inputs_are_not_mutated(runner, case):
    """A5: входной список слоёв, `LayerSpec`-ы и массивы-спрайты не мутированы (заливка `color_rgb` и сдвиг тона
    работают на копии). Ловит: заливку цветом на месте (`sprite[:, :, 0] = ...` без `.copy()`), `list.sort`/`pop`
    над входным списком, перезапись `writeable` у входного спрайта."""
    layers, _, _ = _stack(case)
    held = list(layers)
    arrays = [(i, ly.sprite_source) for i, ly in enumerate(layers) if isinstance(ly.sprite_source, np.ndarray)]
    assert arrays, "стек без массивных спрайтов — тест вакуумный"
    snapshot = [(a.tobytes(), a.flags.writeable, a.shape) for _, a in arrays]
    dumps = [ly.model_dump(exclude={"sprite_source"}) for ly in layers]

    _run(runner, layers, seed=2025)

    assert layers == held and all(a is b for a, b in zip(layers, held, strict=True))
    assert [(a.tobytes(), a.flags.writeable, a.shape) for _, a in arrays] == snapshot
    assert [ly.model_dump(exclude={"sprite_source"}) for ly in layers] == dumps


def test_a5_writing_into_compose_layers_result_does_not_touch_the_input_sprite():
    """A5: для одного статического слоя с нулевым трансформом результат не алиасит входной спрайт. Ловит:
    «короткий путь» `return sprite` вместо компоновки в новую канву."""
    layers, _, _ = _stack("static_one")
    sprite = layers[0].sprite_source
    before = sprite.tobytes()
    out = _composed_from(layers, 0)
    out.rgba[:] = 7
    assert sprite.tobytes() == before


def _composed_from(layers, seed: int, angle: float = 0.0, forced=()):
    mod = importlib.import_module("Services.layer_render.layers")
    return mod.compose_layers(layers, np.random.default_rng(seed), angle, tuple(forced))


@pytest.mark.parametrize("runner", _RUNNERS)
def test_a5_parent_rng_advances_by_one_spawn_of_len_layers_and_its_stream_is_untouched(runner):
    """DESIGN (`rng.spawn(len(layers))`): после вызова у родительского rng `n_children_spawned == len(layers)`, а его
    собственный поток нетронут (`rng.random()` равен свежему `default_rng(5).random()`). Ловит: розыгрыш напрямую
    из родительского rng (сдвиг потока вызывающего), несколько spawn-ов, отсутствие spawn."""
    layers, _, _ = _stack("defect_p05")  # три слоя
    rng = np.random.default_rng(5)
    _run(runner, layers, rng=rng)
    assert rng.bit_generator.seed_seq.n_children_spawned == 3
    assert rng.random() == np.random.default_rng(5).random()


def test_a5_compose_layers_signature_and_result_type():
    """Module contract: `compose_layers(layers, rng, object_angle_deg=0.0, forced_defects=(), *, label="")`,
    `ComposedLayers` — NamedTuple `(rgba, layer_params, active_defects)`. Ловит: `label` позиционным, другие
    умолчания, другой порядок полей результата."""
    import inspect

    mod = importlib.import_module("Services.layer_render.layers")
    params = list(inspect.signature(mod.compose_layers).parameters.values())
    assert [p.name for p in params] == ["layers", "rng", "object_angle_deg", "forced_defects", "label"]
    assert [p.default for p in params[2:]] == [0.0, (), ""]
    assert [p.kind.name for p in params] == [
        "POSITIONAL_OR_KEYWORD",
        "POSITIONAL_OR_KEYWORD",
        "POSITIONAL_OR_KEYWORD",
        "POSITIONAL_OR_KEYWORD",
        "KEYWORD_ONLY",
    ]
    assert issubclass(mod.ComposedLayers, tuple)
    assert mod.ComposedLayers._fields == ("rgba", "layer_params", "active_defects")


def test_a5_compose_layers_active_defects_follow_layer_order_not_forced_order():
    """A2/DESIGN: `active_defects` — `tuple[str, ...]` в порядке СЛОЁВ; принудительные имена в обратном порядке
    дают тот же порядок. Ловит: порядок по `forced_defects` и тип `list`."""
    layers, _, _ = _stack("forced_defect")
    out = _composed_from(layers, 0, forced=("stain", "scratch"))
    assert out.active_defects == ("scratch", "stain")
    assert out.layer_params["scratch"]["active"] is True
    assert out.layer_params["stain"]["active"] is True


def test_a5_compose_layers_without_forced_defects_leaves_p0_defects_inactive():
    """A2: `forced_defects=()` по умолчанию — defect с p=0.0 неактивен, `active_defects == ()`. Ловит: умолчание,
    принудительно включающее все defect-слои."""
    layers, _, _ = _stack("forced_defect")
    out = _composed_from(layers, 0)
    assert out.active_defects == ()
    assert out.layer_params["scratch"]["active"] is False
    assert out.layer_params["stain"] == {"active": False, "color_rgb": [200, 17, 99]}


# ---------------------------------------------------------------------------------------------------------------
# Ловушки TRAPS (литералы со снимка на коде ДО задачи)
# ---------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("runner", _RUNNERS)
def test_trap_inactive_defect_layer_still_records_color_rgb_exactly(runner):
    """TRAP: `color_rgb` defect-слоя пишется в `layer_params` ДО `continue` невыпавшего слоя, значение — как есть
    (`dhue = 0.0`, без HSV-округления: (200, 17, 99) через HSV-круг дало бы (200, 17, 96)). Static-слой с заливкой —
    единственный ключ `color_rgb`, (13, 77, 201) как есть (через HSV было бы (13, 76, 201)).
    Ловит: `continue` раньше записи цвета; `_hue_shift_color` без короткого пути при `hue_deg == 0.0`."""
    LayerSpec, _ = _specs()
    layers = [
        LayerSpec(name="base", mode="static", sprite_source=_sprite(11, 24, 16)),
        LayerSpec(
            name="d",
            mode="defect",
            sprite_source=_sprite(5, 4, 4),
            defect_probability=0.0,
            color_rgb=(200, 17, 99),
        ),
        LayerSpec(name="flat", mode="static", sprite_source=_sprite(6, 4, 4), color_rgb=(13, 77, 201)),
    ]
    params, active, _ = _run(runner, layers)
    assert params == {"d": {"active": False, "color_rgb": [200, 17, 99]}, "flat": {"color_rgb": [13, 77, 201]}}
    assert active == ()


@pytest.mark.parametrize("runner", _RUNNERS)
def test_trap_active_defect_layer_records_active_and_exact_color(runner):
    """TRAP: активный defect-слой с цветом: `{"active": True, "color_rgb": [...]}` как есть (без сдвига тона —
    у defect-слоя `dhue` всегда 0). Ловит: применение hue к defect-слою, потерю `active`."""
    LayerSpec, _ = _specs()
    layers = [
        LayerSpec(name="base", mode="static", sprite_source=_sprite(11, 24, 16)),
        LayerSpec(
            name="d",
            mode="defect",
            sprite_source=_sprite(5, 4, 4),
            defect_probability=1.0,
            color_rgb=(255, 0, 0),
        ),
    ]
    params, active, _ = _run(runner, layers)
    assert params == {"d": {"active": True, "color_rgb": [255, 0, 0]}}
    assert active == ("d",)


@pytest.mark.parametrize("runner", _RUNNERS)
def test_trap_augmented_color_is_recorded_after_hue_shift(runner):
    """TRAP: у augmented-слоя `color_rgb` в `layer_params` — ПОСЛЕ сдвига тона (красный +60 deg = жёлтый),
    рядом пять выбранных полей `LayerAugment`. Ловит: запись исходного `LayerSpec.color_rgb`, потерю
    `hue_shift_deg`, другой знак/масштаб сдвига (OpenCV: H в градусах/2)."""
    LayerSpec, LayerAugment = _specs()
    layers = [
        LayerSpec(name="base", mode="static", sprite_source=_sprite(11, 24, 16)),
        LayerSpec(
            name="t",
            mode="augmented",
            sprite_source=_sprite(6, 4, 4),
            color_rgb=(255, 0, 0),
            augment=LayerAugment(hue_shift_deg=(60.0, 60.0)),
        ),
    ]
    params, active, _ = _run(runner, layers)
    assert params == {
        "t": {
            "offset_x_px": 0.0,
            "offset_y_px": 0.0,
            "angle_deg": 0.0,
            "scale": 1.0,
            "hue_shift_deg": 60.0,
            "color_rgb": [255, 255, 0],
        }
    }
    assert active == ()


@pytest.mark.parametrize("runner", _RUNNERS)
def test_forced_defect_string_parsing_strips_and_follows_layer_order(runner):
    """Обёртка: `passport.defect` ' zz , scratch ,,' -> имена `zz`, `scratch` (strip, пустые отброшены) ->
    результат в порядке слоёв: `'scratch,zz'`. Ловит: потерю `strip`, порядок по строке, пустое имя как 'неизвестное'
    (для `compose_layers` — тот же результат на уже разобранных именах)."""
    LayerSpec, _ = _specs()
    layers = [
        LayerSpec(name="base", mode="static", sprite_source=_sprite(1, 4, 4)),
        LayerSpec(name="scratch", mode="defect", sprite_source=_sprite(3, 4, 4)),
        LayerSpec(name="zz", mode="defect", sprite_source=_sprite(3, 4, 4)),
    ]
    if runner == "LayeredObject":
        from Services.line_sim.core.layered_object import LayeredObject

        obj = LayeredObject(_passport("obj-1", 0.0, " zz , scratch ,,"), layers, np.random.default_rng(0))
        assert obj.passport.defect == "scratch,zz"
    else:
        out = _composed_from(layers, 0, forced=("zz", "scratch"))
        assert ",".join(out.active_defects) == "scratch,zz"


def test_layered_object_does_not_mutate_the_input_passport():
    """Обёртка: входной `passport` не мутируется — у объекта своя копия (`replace`), у входного прежние `defect` и
    пустые `layer_params`. Ловит: запись `layer_params`/`defect` в исходный паспорт при выносе тела в функцию."""
    from Services.line_sim.core.layered_object import LayeredObject

    layers, _, _ = _stack("defect_p05")
    passport = _passport("obj-1", 0.0, None)
    obj = LayeredObject(passport, layers, np.random.default_rng(7))
    assert obj.passport is not passport
    assert (passport.defect, passport.layer_params) == (None, {})
    assert obj.passport.defect == "scratch"


# ---------------------------------------------------------------------------------------------------------------
# A4 — transform_layer / LayeredObject._transform
# ---------------------------------------------------------------------------------------------------------------

_TRANSFORMS = [
    pytest.param("LayeredObject._transform", id="LayeredObject._transform[green]"),
    pytest.param("transform_layer", id="transform_layer[red]"),
]

# sha256 `_transform(_sprite(21, 16, 12), 0.9, 37.0, 30.0, (10, 20, 30))` до задачи.
_A4_SHA = "a11750f60e1be6781b1fd0005847721be85eaceb000381bac30f2281d83d605a"
_A4_SHAPE = (18, 18, 4)


def _transform_fn(which: str):
    if which == "LayeredObject._transform":
        from Services.line_sim.core.layered_object import LayeredObject

        return LayeredObject._transform
    return importlib.import_module("Services.layer_render.layers").transform_layer


@pytest.mark.parametrize("which", _TRANSFORMS)
def test_a4_transform_sha256_with_every_step_active(which):
    """A4: `_transform(s, 0.9, 37.0, 30.0, (10, 20, 30))` побайтно как до задачи (заливка -> scale -> rotate_expand
    -> сдвиг тона). Ловит: смену порядка шагов, interpolation, округления размера, пересчёт hue."""
    s = _sprite(21, 16, 12)
    out = _transform_fn(which)(s, 0.9, 37.0, 30.0, (10, 20, 30))
    assert (_sha(out), out.shape) == (_A4_SHA, _A4_SHAPE)


@pytest.mark.parametrize("which", _TRANSFORMS)
def test_a4_transform_returns_the_sprite_itself_when_all_neutral(which):
    """A4/TRAP: scale 1.0, angle 0.0, hue 0.0, color None -> `is s` (кэш фабрики, не копия). Ловит: «защитное»
    `.copy()` в начале функции — идентичность держит read-only вид фабрики без копии."""
    s = _sprite(21, 16, 12)
    assert _transform_fn(which)(s, 1.0, 0.0, 0.0, None) is s


@pytest.mark.parametrize("which", _TRANSFORMS)
@pytest.mark.parametrize(
    "args",
    [(1.2, 0.0, 0.0, None), (1.0, 10.0, 0.0, None), (1.0, 0.0, 20.0, None), (1.0, 0.0, 0.0, (9, 9, 9))],
    ids=["scale", "angle", "hue", "color"],
)
def test_a4_transform_any_single_non_neutral_argument_gives_a_new_array_and_spares_the_input(which, args):
    """A4: достаточно ОДНОГО ненулевого аргумента — результат новый массив, входной спрайт нетронут. Ловит: проверку
    идентичности по неполному набору аргументов (например, только по scale), заливку цветом на месте."""
    s = _sprite(21, 16, 12)
    before = s.tobytes()
    out = _transform_fn(which)(s, *args)
    assert out is not s
    assert s.tobytes() == before


@pytest.mark.parametrize("which", _TRANSFORMS)
def test_a4_transform_color_fill_sets_rgb_and_keeps_alpha(which):
    """A4: заливка цветом — RGB := color везде, альфа спрайта не тронута (оракул — прямой numpy, не код). Ловит:
    заливку альфы, перестановку каналов."""
    s = _sprite(21, 16, 12)
    out = _transform_fn(which)(s, 1.0, 0.0, 0.0, (10, 20, 30))
    assert out.shape == s.shape
    assert np.all(out[:, :, :3] == np.array([10, 20, 30], np.uint8))
    assert np.array_equal(out[:, :, 3], s[:, :, 3])


@pytest.mark.parametrize("which", _TRANSFORMS)
@pytest.mark.parametrize("angle,k", [(90.0, 1), (180.0, 2), (270.0, 3), (-90.0, 3), (450.0, 1)])
def test_a4_transform_right_angles_are_exact_rot90_without_interpolation(which, angle, k):
    """A4/DESIGN: кратные 90 deg — `np.rot90` побайтно (оракул — `np.rot90(s, k)`), знак: положительный — CCW.
    Ловит: `rotate_expand` на прямых углах (холст на 1 px больше, полупиксельный сдвиг), неверный знак."""
    s = _sprite(21, 16, 12)
    out = _transform_fn(which)(s, 1.0, angle, 0.0, None)
    assert out.shape == np.rot90(s, k).shape
    assert np.array_equal(out, np.rot90(s, k))


@pytest.mark.parametrize("which", _TRANSFORMS)
@pytest.mark.parametrize("scale,shape", [(0.1, (2, 1, 4)), (1.5, (24, 18, 4)), (0.01, (1, 1, 4))])
def test_a4_transform_scale_rounds_size_and_never_collapses_below_one_pixel(which, scale, shape):
    """A4: размер после scale = `round(размер * scale)`, но не меньше 1 px (спрайт 16x12 HxW: 0.1 -> 2x1, 1.5 ->
    24x18, 0.01 -> 1x1). Ловит: усечение `int()` вместо `round`, потерю `max(1, ...)`, перепутанные ось h/w."""
    s = _sprite(21, 16, 12)
    assert _transform_fn(which)(s, scale, 0.0, 0.0, None).shape == shape


# ---------------------------------------------------------------------------------------------------------------
# canvas_size, load_layer_sprite
# ---------------------------------------------------------------------------------------------------------------

_CANVAS = [
    pytest.param("layered_object", id="layered_object.canvas_size[green]"),
    pytest.param("layers", id="layers.canvas_size[red]"),
]


def _canvas_fn(which: str):
    if which == "layered_object":
        from Services.line_sim.core.layered_object import canvas_size

        return canvas_size
    return importlib.import_module("Services.layer_render.layers").canvas_size


def _blank(h: int, w: int) -> np.ndarray:
    return np.zeros((h, w, 4), np.uint8)


@pytest.mark.parametrize("which", _CANVAS)
@pytest.mark.parametrize(
    "placed,expected",
    [
        ([(_blank(10, 20), 0.0, 0.0)], (20, 10)),
        ([(_blank(3, 5), 2.3, -4.0)], (10, 12)),
        ([(_blank(10, 20), 0.0, 0.0), (_blank(3, 5), 2.3, -4.0)], (20, 12)),
        ([(_blank(5, 7), -6.5, 1.0), (_blank(9, 3), 0.0, -3.5)], (20, 16)),
    ],
    ids=["centered", "offset_rounds_up_to_even", "max_of_two_layers", "negative_offsets_use_abs"],
)
def test_a4_canvas_size_literals(which, placed, expected):
    """canvas_size: `(w, h) = (2*ceil(max(|ox| + w/2)), 2*ceil(max(|oy| + h/2)))` — канва симметрична и чётна
    (значения выведены вручную). Ловит: `round` вместо `ceil`, потерю `abs`, перепутанные w/h, `max` -> `sum`."""
    assert _canvas_fn(which)(placed) == expected


def test_a4_load_layer_sprite_returns_ndarray_source_itself():
    """load_layer_sprite: массивный источник отдаётся как есть (`is`) — фабрика строит read-only виды без копий.
    Ловит: защитное копирование при загрузке."""
    LayerSpec, _ = _specs()
    arr = _sprite(1, 4, 4)
    mod = importlib.import_module("Services.layer_render.layers")
    assert mod.load_layer_sprite(LayerSpec(name="a", mode="static", sprite_source=arr)) is arr


def test_a4_load_layer_sprite_calls_a_provider_exactly_once_and_returns_its_array():
    """load_layer_sprite: callable зовётся ровно один раз, результат — его массив. Ловит: двойной вызов (проверка
    + загрузка)."""
    LayerSpec, _ = _specs()
    arr = _sprite(1, 4, 4)
    calls = []

    def provider():
        calls.append(1)
        return arr

    mod = importlib.import_module("Services.layer_render.layers")
    assert mod.load_layer_sprite(LayerSpec(name="a", mode="static", sprite_source=provider)) is arr
    assert calls == [1]


@pytest.mark.parametrize(
    "source,expected",
    [
        ("some_id", _E_STRING),
        (np.zeros((4, 4, 3), np.uint8), _E_RGB),
        (np.zeros((4, 4, 4), np.float32), _E_FLOAT),
        (np.zeros((4, 4), np.uint8), _E_GRAY),
    ],
    ids=["string_id", "rgb", "float32", "gray"],
)
def test_a6_load_layer_sprite_errors_have_the_same_type_and_text(source, expected):
    """A6: ошибки загрузки спрайта — прежние тип и текст (называют слой `'a'`). Ловит: смену типа
    (`TypeError`<->`ValueError`), переписанный текст, потерю формы/dtype в тексте."""
    LayerSpec, _ = _specs()
    mod = importlib.import_module("Services.layer_render.layers")
    layer = LayerSpec(name="a", mode="static", sprite_source=source)
    assert _caught(lambda: mod.load_layer_sprite(layer)) == expected


# ---------------------------------------------------------------------------------------------------------------
# LayerSpec / LayerAugment: поля и валидаторы переезжают дословно
# ---------------------------------------------------------------------------------------------------------------

_API = [
    pytest.param("Services.line_sim.interfaces", id="line_sim.interfaces[green]"),
    pytest.param("Services.layer_render.layers", id="layer_render.layers[red]"),
]


@pytest.mark.parametrize("module", _API)
def test_layer_models_keep_field_names_and_augment_fields_order(module):
    """DESIGN: имена/состав полей `LayerSpec`, `LayerAugment` и порядок `AUGMENT_FIELDS` прежние (на них стоят
    `pult_web` и YAML пресетов; порядок `AUGMENT_FIELDS` = порядок розыгрыша `uniform`). Ловит: переименование,
    перестановку полей."""
    mod = importlib.import_module(module)
    assert tuple(mod.LayerSpec.model_fields) == (
        "name",
        "mode",
        "sprite_source",
        "offset_px",
        "angle_deg",
        "scale",
        "augment",
        "defect_probability",
        "color_rgb",
    )
    assert tuple(mod.LayerAugment.model_fields) == (
        "offset_x_px",
        "offset_y_px",
        "angle_deg",
        "scale",
        "hue_shift_deg",
    )
    assert mod.AUGMENT_FIELDS == ("offset_x_px", "offset_y_px", "angle_deg", "scale", "hue_shift_deg")


@pytest.mark.parametrize("module", _API)
@pytest.mark.parametrize(
    "kwargs,message",
    [
        ({"color_rgb": (1, 2)}, "слой 'x': color_rgb должен быть тройкой (r, g, b), получено (1, 2)"),
        ({"color_rgb": (300, 0, 0)}, "слой 'x': color_rgb.r=300 — должен быть int в диапазоне [0, 255]"),
        (
            {"augment": {"angle_deg": (5.0, 1.0)}},
            "слой 'x': augment.angle_deg: lo=5.0 > hi=1.0",
        ),
        (
            {"augment": {"scale": (0.0, 1.0)}},
            "слой 'x': augment.scale: нижняя граница должна быть > 0",
        ),
        (
            {"mode": "static", "augment": {}},
            "слой 'x': augment задан при mode='static' — диапазоны допустимы только у слоя mode='augmented'",
        ),
    ],
    ids=["color_len", "color_range", "augment_lo_gt_hi", "augment_scale_lo", "augment_on_static"],
)
def test_layer_spec_validators_keep_their_error_texts(module, kwargs, message):
    """Оба валидатора `LayerSpec` переехали дословно: тексты с именем слоя и заголовок pydantic `for LayerSpec`
    (имя класса не меняется). Ловит: потерю валидатора при переносе, смену текста, переименование класса."""
    mod = importlib.import_module(module)
    args = {"name": "x", "mode": "augmented", "sprite_source": _sprite(1, 4, 4), **kwargs}
    if "augment" in args:
        args["augment"] = mod.LayerAugment(**args["augment"])
    from pydantic import ValidationError

    with pytest.raises(ValidationError) as info:
        mod.LayerSpec(**args)
    text = str(info.value)
    assert message in text
    assert "for LayerSpec" in text


@pytest.mark.parametrize("module", _API)
def test_layer_models_are_frozen_and_forbid_extra_fields(module):
    """DESIGN: `frozen=True, extra="forbid"` сохранены. Ловит: потерю `model_config` при переносе."""
    from pydantic import ValidationError

    mod = importlib.import_module(module)
    layer = mod.LayerSpec(name="x", mode="static", sprite_source=_sprite(1, 4, 4))
    with pytest.raises(ValidationError):
        layer.name = "y"
    with pytest.raises(ValidationError):
        mod.LayerSpec(name="x", mode="static", sprite_source=_sprite(1, 4, 4), bogus=1)
    with pytest.raises(ValidationError):
        mod.LayerAugment(bogus=(0.0, 1.0))


# ---------------------------------------------------------------------------------------------------------------
# A4 / A4b — тождества и публичный API
# ---------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["LayerMode", "RangeF", "SpriteSource", "AUGMENT_FIELDS", "LayerAugment", "LayerSpec"])
def test_a4_line_sim_interfaces_reexports_the_six_types_from_layer_render_layers(name):
    """A4: `Services.line_sim.interfaces.<n> is Services.layer_render.layers.<n>` для шести типов (один объект,
    не копия). Ловит: дубль класса в `line_sim` (два `LayerSpec` — `isinstance` расходится)."""
    from Services.line_sim import interfaces

    layers = importlib.import_module("Services.layer_render.layers")
    assert getattr(interfaces, name) is getattr(layers, name)


def test_a4_line_sim_interfaces_all_lists_the_six_reexported_types():
    """A4/Files п.2: в `interfaces.__all__` — шесть реэкспортов (иначе ruff F401 снесёт «неиспользуемый» импорт).
    Ловит: реэкспорт без `__all__`. Собственные `ObjectPassport`/`Protocol` в `__all__` НЕ требуются: план
    (Files п.2) этого не говорит."""
    from Services.line_sim import interfaces

    expected = {"LayerMode", "RangeF", "SpriteSource", "AUGMENT_FIELDS", "LayerAugment", "LayerSpec"}
    assert expected <= set(getattr(interfaces, "__all__", ()))


def test_a4_object_passport_and_scene_protocol_stay_defined_in_line_sim():
    """A4/Files п.2: `ObjectPassport` и `SceneCompositorProtocol` остаются в `line_sim.interfaces` (в `layer_render`
    паспорта нет). Ловит: вынос паспорта в `layer_render`."""
    from Services.line_sim import interfaces

    assert interfaces.ObjectPassport.__module__ == "Services.line_sim.interfaces"
    assert interfaces.SceneCompositorProtocol.__module__ == "Services.line_sim.interfaces"


def test_a4_layered_object_canvas_size_is_the_layers_function_and_is_exported():
    """A4/TRAP: `layered_object.canvas_size is layers.canvas_size` и имя в `layered_object.__all__` (потребитель
    `core/preview.py`; без `__all__` pre-commit ruff --fix снесёт неиспользуемый импорт)."""
    from Services.line_sim.core import layered_object

    layers = importlib.import_module("Services.layer_render.layers")
    assert layered_object.canvas_size is layers.canvas_size
    assert "canvas_size" in getattr(layered_object, "__all__", ())


def test_a4_layered_object_transform_is_the_layers_function():
    """A4: `LayeredObject._transform is layers.transform_layer` (потребители — `core/factory.py`,
    `tests/test_hazards_look_1_2.py`). Ловит: обёртку-делегат вместо `staticmethod(transform_layer)`."""
    from Services.line_sim.core.layered_object import LayeredObject

    layers = importlib.import_module("Services.layer_render.layers")
    assert LayeredObject._transform is layers.transform_layer


def test_a4_factory_uses_the_shared_sprite_loader():
    """Files п.4: `core/factory.py` берёт `load_layer_sprite` из `Services.layer_render` (тот же объект); приватный
    `_load_sprite` в публичный API не просачивается."""
    from Services.line_sim.core import factory

    pkg = importlib.import_module("Services.layer_render")
    assert factory.load_layer_sprite is pkg.load_layer_sprite


def test_a4b_all_eleven_contract_names_are_in_layer_render_all_and_are_the_layers_objects():
    """A4b: все 11 имён Module contract — в `Services.layer_render.__all__`, и каждое — тот же объект, что в
    `layers` (образец — `test_acceptance_6_1_crop.py:596-602`). Ловит: забытое имя в `__all__`, подмену копией."""
    pkg = importlib.import_module("Services.layer_render")
    layers = importlib.import_module("Services.layer_render.layers")
    missing = [n for n in _CONTRACT_NAMES if n not in pkg.__all__]
    assert missing == []
    assert [n for n in _CONTRACT_NAMES if getattr(pkg, n) is not getattr(layers, n)] == []


def test_a4b_layer_render_all_has_no_private_names_and_no_duplicates():
    """A4b: приватные имена (`_compose_canvas`, `_rotate`, …) не реэкспортируются; повторов в `__all__` нет
    (правило `docs/maps/layer_render.md`)."""
    pkg = importlib.import_module("Services.layer_render")
    assert [n for n in pkg.__all__ if n.startswith("_")] == []
    assert len(pkg.__all__) == len(set(pkg.__all__))
    assert "LayerSpec" in pkg.__all__  # анти-вакуум: __all__ вообще содержит новые имена


@pytest.mark.parametrize("name", ["LayerSpec", "LayerAugment"])
def test_a4b_line_sim_package_exports_the_layer_render_classes(name):
    """A4b: `Services.line_sim.LayerSpec is Services.layer_render.LayerSpec` (и `LayerAugment`)."""
    line_sim = importlib.import_module("Services.line_sim")
    pkg = importlib.import_module("Services.layer_render")
    assert getattr(line_sim, name) is getattr(pkg, name)


# ---------------------------------------------------------------------------------------------------------------
# A7 — границы слоёв (AST + рантайм)
# ---------------------------------------------------------------------------------------------------------------

_FORBIDDEN_PARTS = {"dataset_gen", "line_sim", "ml_train"}


def _forbidden_imports(source: str) -> list[str]:
    """Имена запрещённых пакетов в импортах `source` (любые формы, включая локальные внутри функций)."""
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found += [p for p in alias.name.split(".") if p in _FORBIDDEN_PARTS]
        elif isinstance(node, ast.ImportFrom):
            found += [p for p in (node.module or "").split(".") if p in _FORBIDDEN_PARTS]
            found += [a.name for a in node.names if a.name in _FORBIDDEN_PARTS]
    return found


@pytest.mark.parametrize(
    "snippet",
    [
        "from Services.line_sim.interfaces import ObjectPassport",
        "def f():\n    import Services.dataset_gen.core.compose",
        "from Services import line_sim",
        "from ..ml_train import x",
    ],
)
def test_a7_scanner_control_detects_forbidden_forms(snippet):
    """Контроль сканера A7: без него «0 находок» в `layers.py` не доказывает ничего."""
    assert _forbidden_imports(snippet)


def _layer_render_sources() -> list[Path]:
    return [p for p in _LAYER_RENDER.rglob("*.py") if "tests" not in p.relative_to(_LAYER_RENDER).parts]


def test_a7_layers_module_exists_is_scanned_and_imports_no_forbidden_package():
    """A7: `layers.py` существует, входит в сканируемый набор (анти-вакуум: сканер его видит) и не импортирует
    `dataset_gen`/`line_sim`/`ml_train`. Ловит: импорт `composite`/`rotate_expand` через `dataset_gen.core.compose`
    (как в старом `layered_object.py:21`), локальный импорт внутри функции."""
    layers_py = _LAYER_RENDER / "layers.py"
    assert layers_py.is_file(), "Services/layer_render/layers.py не создан"
    assert layers_py in _layer_render_sources()
    assert _forbidden_imports(layers_py.read_text(encoding="utf-8")) == []


def test_a7_layers_module_never_mentions_object_passport():
    """A7/DESIGN: `layer_render` не знает паспорта — имя `ObjectPassport` не встречается ни как импорт, ни как
    идентификатор. Ловит: аннотацию/параметр `passport` в `compose_layers`."""
    layers_py = _LAYER_RENDER / "layers.py"
    assert layers_py.is_file(), "Services/layer_render/layers.py не создан"
    tree = ast.parse(layers_py.read_text(encoding="utf-8"))
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    names |= {a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom | ast.Import) for a in n.names}
    names |= {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert "ObjectPassport" not in names


_PROBE = """
import json, sys
import numpy as np
{body}
roots = (["Services", "line_sim"], ["Services", "dataset_gen"], ["Services", "ml_train"])
bad = sorted(m for m in sys.modules if m.split(".")[:2] in roots)
print(json.dumps(bad))
"""

_COMPOSE_BODY = """
from Services.layer_render import layers
spec = layers.LayerSpec(name="a", mode="static", sprite_source=np.full((6, 6, 4), 255, np.uint8))
out = layers.compose_layers([spec], np.random.default_rng(0), 37.0, (), label="p")
assert out.rgba.shape[2] == 4
"""


def _probe(body: str) -> tuple[int, str, str]:
    env = {**os.environ, "PYTHONPATH": str(_ROOT)}
    proc = subprocess.run(
        [sys.executable, "-c", _PROBE.format(body=body)],
        cwd=_ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )
    return proc.returncode, proc.stdout.strip(), proc.stderr[-800:]


def test_a7_probe_control_flags_a_line_sim_import():
    """Контроль рантайм-зонда A7: импорт `Services.line_sim` попадает в список запрещённых модулей — иначе пустой
    список ниже ничего не доказывает."""
    code, out, err = _probe("import Services.line_sim")
    assert code == 0, err
    assert "Services.line_sim" in json.loads(out)


def test_a7_importing_and_running_compose_layers_loads_no_line_sim_dataset_gen_or_ml_train():
    """A7 (рантайм): в свежем интерпретаторе импорт `Services.layer_render.layers` и вызов `compose_layers` (с
    поворотом объекта — ветка `rotate_expand`) не загружают `Services.line_sim|dataset_gen|ml_train`. Ловит:
    динамический импорт (`importlib`, `__import__`), который AST по именам не увидит."""
    code, out, err = _probe(_COMPOSE_BODY)
    assert code == 0, err
    assert json.loads(out) == []
