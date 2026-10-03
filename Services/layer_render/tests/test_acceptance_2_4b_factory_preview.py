"""Task 2.4b (слепой тест тестера): `ObjectFactory` и превью переезжают в `Services/layer_render`.

Пишется по acceptance-критериям A1-A8 плана `layer-render/phase-2-core-2.4b.md` (A9 и A10 — проверки лида, не pytest).
Реализации в дереве нет по построению (worktree на коммите до кода): модулей `layer_render.{factory,preview}` нет,
у `layer_render.{catalog,io,layers}` нет `load_catalog` / `load_image_rgba` / `json_safe`, у `LayeredObject` нет
`from_rendered`. Импорт нового API идёт ВНУТРИ теста (`importlib`), не при сборе: нет одного модуля — падают его кейсы,
а не весь файл.

ЗЕЛЁНЫЕ ДО ЗАДАЧИ (страховочная сеть — те же свойства через СТАРЫЕ пути, `line_sim.ObjectFactory.make` и
`line_sim.core.preview`; такими они обязаны остаться и после переезда):
  * A3 дорога `make`      литералы объекта: sha256 `rgba`, shape, класс, угол, дефект, layer_params, расход rng
  * A4 текст ошибки       `line_sim.ObjectFactory.make("obj-7", ...)` на прозрачном спрайте
  * A5 флаг оператора     `force_defect_next` / `force_defect_pending`, флаг переживает исключение `render`
  * A6 дорога «старый путь»  превью побайтно прежнее
  * A7 цикл импорта       чистый процесс на модуль (нижние восемь из двенадцати — старые модули)
  * A1 / A2 / A8 часть    guard-кейсы старых модулей (`__all__` превью, `canvas_size` в `layered_object.__all__`)
КРАСНЫЕ ДО ЗАДАЧИ (новый API — `ModuleNotFoundError` / `AttributeError`):
  * A1 идентичности и `__module__`; A2 наследование и AST; A3 дорога `render`; A4 `from_rendered` и ошибка базы;
  * A5 «у базы нет флага»; A6 дорога «новый путь»; A7 для новых модулей; A8 `Services.layer_render.__all__`.

ОРАКУЛЫ. Ожидаемые значения — литералы, снятые одноразовым скриптом на коде ДО переезда (`line_sim.ObjectFactory.make`,
`line_sim.core.preview.render_preview_grid` / `render_layout`, `line_sim.interfaces._json_safe`) и вписанные ниже;
в тесте они не вычисляются из проверяемого кода. Деревья пресетов тест строит сам во `tmp_path` из детерминированных
массивов (`np.random.default_rng(<seed>)`): спрайты со случайными цветами и круглой альфой, не константы — sha256 различает
перестановку пикселей. Окружение снимка: Windows-10-10.0.19045-SP0, CPython 3.12.12, numpy 2.4.4, cv2 5.0.0.
На другой платформе возможны расхождения `INTER_AREA` / поворота / кодировщика PNG — прецедент в тестах 2.1, 2.3, 6.1.
Для PNG превью проверяются ДВА хэша: байтов файла (требование A6) и декодированных пикселей — расхождение только
первого значит «другой кодировщик», не «другая картинка».
"""

# ruff: noqa: E501 -- литералы снимка (sha256, JSON) длинные; перенос строки ломает сверку глазами
from __future__ import annotations

import ast
import copy
import dataclasses
import hashlib
import importlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import pytest

_ROOT = Path(__file__).resolve().parents[3]
_SEEDS = range(5)
_VARIANTS = ("class_layer", "auto_base", "no_catalog", "defect_half")
_ROADS = (pytest.param("make", id="make"), pytest.param("render", id="render"))


# --------------------------------------------------------------------------- #
# Фикстуры: деревья пресетов во tmp_path                                       #
# --------------------------------------------------------------------------- #


def _rand_sprite(rng: np.random.Generator, side: int) -> np.ndarray:
    """RGBA-спрайт со случайными цветами и круглой альфой (не константа)."""
    sprite = rng.integers(0, 256, size=(side, side, 4), dtype=np.uint8)
    yy, xx = np.mgrid[:side, :side]
    inside = (yy - side / 2) ** 2 + (xx - side / 2) ** 2 <= (side / 2) ** 2
    sprite[:, :, 3] = np.where(inside, 255, 0)
    return sprite


def _write_png(path: Path, rgba: np.ndarray) -> None:
    from Services.layer_render.io import imwrite_unicode

    imwrite_unicode(path, cv2.cvtColor(rgba, cv2.COLOR_RGBA2BGRA))


def build_presets(root: Path) -> dict[str, Any]:
    """Четыре пресета A3 (ключи `_VARIANTS`) + `transparent` (A4): файлы лежат в `root`."""
    from Services.layer_render import CLASS_SPRITE_SOURCE, LayerAugment, LayerSpec, ScenePreset

    data_rng = np.random.default_rng(1234)
    for cls in ("A", "B", "C", "D"):
        (root / "cat" / cls).mkdir(parents=True)
        _write_png(root / "cat" / cls / "0.png", _rand_sprite(data_rng, 40))
    _write_png(root / "disk.png", _rand_sprite(data_rng, 56))
    _write_png(root / "ring.png", _rand_sprite(data_rng, 32))
    clear = np.zeros((20, 20, 4), dtype=np.uint8)
    clear[:, :, :3] = 200  # цвет есть, альфа везде 0 -> объект прозрачен
    _write_png(root / "clear.png", clear)

    disk = LayerSpec(name="disk", mode="static", sprite_source=str(root / "disk.png"))
    ring = LayerSpec(
        name="ring",
        mode="augmented",
        sprite_source=str(root / "ring.png"),
        offset_px=(3.0, 2.0),
        augment=LayerAugment(
            offset_x_px=(-4.0, 4.0), angle_deg=(-15.0, 15.0), scale=(0.8, 1.2), hue_shift_deg=(-20.0, 20.0)
        ),
    )
    letter = LayerSpec(name="letter", mode="static", sprite_source=CLASS_SPRITE_SOURCE)
    return {
        # слой class:// между дисками: позиция в стеке — часть контракта seed
        "class_layer": ScenePreset(
            catalog_dir=str(root / "cat"),
            angle_range_deg=(-30.0, 30.0),
            defect_probability=0.0,
            layers=[disk, letter, ring],
        ),
        # каталог без class:// -> авто-слой `base` под слоями пресета
        "auto_base": ScenePreset(
            catalog_dir=str(root / "cat"),
            angle_range_deg=(-30.0, 30.0),
            defect_probability=0.0,
            layers=[disk.model_copy(update={"offset_px": (5.0, -3.0), "angle_deg": 20.0, "scale": 1.1})],
        ),
        # нет каталога -> только слои, класса нет
        "no_catalog": ScenePreset(angle_range_deg=(-30.0, 30.0), defect_probability=0.0, layers=[disk, ring]),
        # розыгрыш брака: seed 0..4 дают оба исхода
        "defect_half": ScenePreset(
            catalog_dir=str(root / "cat"),
            angle_range_deg=(-30.0, 30.0),
            defect_probability=0.5,
            layers=[ring],
        ),
        # A4: БЕЗ catalog_dir, единственный слой — прозрачный PNG (с каталогом спрайт класса непрозрачен)
        "transparent": ScenePreset(
            angle_range_deg=(-10.0, 10.0),
            defect_probability=0.0,
            layers=[LayerSpec(name="clear", mode="static", sprite_source=str(root / "clear.png"))],
        ),
    }


@pytest.fixture(scope="module")
def presets(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    return build_presets(tmp_path_factory.mktemp("lr24b"))


# --------------------------------------------------------------------------- #
# Литералы снимка (A3, A4, A6) — снято на коде до переезда                     #
# --------------------------------------------------------------------------- #

# BEGIN LITERALS
# окружение снимка: Windows-10-10.0.19045-SP0, CPython 3.12.12, numpy 2.4.4, cv2 5.0.0
_A3: dict[tuple[str, int, bool], dict[str, Any]] = {
    ("class_layer", 0, False): {
        "sha256": "0b4396ad94fb836b33c9f29cc264391a056e8bfb248fe49a29f79dbe1e28049e",
        "shape": [68, 68, 4],
        "class_name": "D",
        "angle_deg": -13.81279717416778,
        "defect": None,
        "layer_params": '{"damaged": {"active": false}, "ring": {"angle_deg": 3.5284587414785307, "hue_shift_deg": -10.153633938165285, "offset_x_px": 2.7061691836572814, "offset_y_px": 0.0, "scale": 1.0811350343972639}}',
        "rng_parent_next": 0.04097352393619469,
        "rng_spawn_next": 0.6529725757834846,
    },
    ("class_layer", 0, True): {
        "sha256": "6011dcf2a6349a5505ff8eef79932fd06a962517195f29a4b15227b99ed3c793",
        "shape": [68, 68, 4],
        "class_name": "D",
        "angle_deg": -13.81279717416778,
        "defect": "damaged",
        "layer_params": '{"damaged": {"active": true}, "ring": {"angle_deg": 3.5284587414785307, "hue_shift_deg": -10.153633938165285, "offset_x_px": 2.7061691836572814, "offset_y_px": 0.0, "scale": 1.0811350343972639}}',
        "rng_parent_next": 0.04097352393619469,
        "rng_spawn_next": 0.6529725757834846,
    },
    ("class_layer", 1, False): {
        "sha256": "b940b8a0395330cddcb8aa23128172a8223328bba85fd5d6e6de82a372f32600",
        "shape": [76, 76, 4],
        "class_name": "B",
        "angle_deg": 27.02782177955612,
        "defect": None,
        "layer_params": '{"damaged": {"active": false}, "ring": {"angle_deg": -2.367006024586166, "hue_shift_deg": 8.944364495942946, "offset_x_px": -2.1346535711985357, "offset_y_px": 0.0, "scale": 1.0847036082135217}}',
        "rng_parent_next": 0.14415961271963373,
        "rng_spawn_next": 0.6110309345532344,
    },
    ("class_layer", 1, True): {
        "sha256": "46c0e2aaacce8ffea5d0ce63165448b2b8e4ebba1dfe6e45d15144530ee3490a",
        "shape": [76, 76, 4],
        "class_name": "B",
        "angle_deg": 27.02782177955612,
        "defect": "damaged",
        "layer_params": '{"damaged": {"active": true}, "ring": {"angle_deg": -2.367006024586166, "hue_shift_deg": 8.944364495942946, "offset_x_px": -2.1346535711985357, "offset_y_px": 0.0, "scale": 1.0847036082135217}}',
        "rng_parent_next": 0.14415961271963373,
        "rng_spawn_next": 0.6110309345532344,
    },
    ("class_layer", 2, False): {
        "sha256": "a21931e38be6ad38580c68aeb21de9186e1c84bf9f19ea7d7769ff621f9c3d26",
        "shape": [67, 67, 4],
        "class_name": "D",
        "angle_deg": -12.090531395152603,
        "defect": None,
        "layer_params": '{"damaged": {"active": false}, "ring": {"angle_deg": 4.9247624221369115, "hue_shift_deg": -1.662163471547771, "offset_x_px": -1.275288260906363, "offset_y_px": 0.0, "scale": 1.085577493365013}}',
        "rng_parent_next": 0.8142257405942803,
        "rng_spawn_next": 0.03183214910423604,
    },
    ("class_layer", 2, True): {
        "sha256": "162f0eb2a85ec34979e954ee985bb75a6e6619e8b9aec8948603ffa725a582eb",
        "shape": [67, 67, 4],
        "class_name": "D",
        "angle_deg": -12.090531395152603,
        "defect": "damaged",
        "layer_params": '{"damaged": {"active": true}, "ring": {"angle_deg": 4.9247624221369115, "hue_shift_deg": -1.662163471547771, "offset_x_px": -1.275288260906363, "offset_y_px": 0.0, "scale": 1.085577493365013}}',
        "rng_parent_next": 0.8142257405942803,
        "rng_spawn_next": 0.03183214910423604,
    },
    ("class_layer", 3, False): {
        "sha256": "16e252604df6b6ce61fd025b394b8fb5954906c9af045eefe298705594f35895",
        "shape": [70, 70, 4],
        "class_name": "D",
        "angle_deg": -15.791369604234017,
        "defect": None,
        "layer_params": '{"damaged": {"active": false}, "ring": {"angle_deg": 12.975542088417846, "hue_shift_deg": -1.4846547773968268, "offset_x_px": -3.555081241051812, "offset_y_px": 0.0, "scale": 1.1556168062187342}}',
        "rng_parent_next": 0.8012744652063969,
        "rng_spawn_next": 0.7827393065271728,
    },
    ("class_layer", 3, True): {
        "sha256": "6e2c95e0d10c140ddd483399a747addb64cfdd82f94994fc19888e706f3628d8",
        "shape": [70, 70, 4],
        "class_name": "D",
        "angle_deg": -15.791369604234017,
        "defect": "damaged",
        "layer_params": '{"damaged": {"active": true}, "ring": {"angle_deg": 12.975542088417846, "hue_shift_deg": -1.4846547773968268, "offset_x_px": -3.555081241051812, "offset_y_px": 0.0, "scale": 1.1556168062187342}}',
        "rng_parent_next": 0.8012744652063969,
        "rng_spawn_next": 0.7827393065271728,
    },
    ("class_layer", 4, False): {
        "sha256": "9dcbaca1e1cb7277143c8e30bdca16c62a58831784730a0077504e5d48fe1b69",
        "shape": [57, 57, 4],
        "class_name": "C",
        "angle_deg": 0.6796531688616945,
        "defect": None,
        "layer_params": '{"damaged": {"active": false}, "ring": {"angle_deg": 7.005805232588923, "hue_shift_deg": 13.239669405735299, "offset_x_px": -3.3220083001670933, "offset_y_px": 0.0, "scale": 0.9029596495602393}}',
        "rng_parent_next": 0.9762437057077041,
        "rng_spawn_next": 0.5554484626129981,
    },
    ("class_layer", 4, True): {
        "sha256": "bc45255003e0f1b5a849cf1a5be96161dea70055adc05387020a4f390300300e",
        "shape": [57, 57, 4],
        "class_name": "C",
        "angle_deg": 0.6796531688616945,
        "defect": "damaged",
        "layer_params": '{"damaged": {"active": true}, "ring": {"angle_deg": 7.005805232588923, "hue_shift_deg": 13.239669405735299, "offset_x_px": -3.3220083001670933, "offset_y_px": 0.0, "scale": 0.9029596495602393}}',
        "rng_parent_next": 0.9762437057077041,
        "rng_spawn_next": 0.5554484626129981,
    },
    ("auto_base", 0, False): {
        "sha256": "1b8d8927812ac71999e63cca9ff69a4c4274861ba7622f47c5a8a0ea4543f237",
        "shape": [106, 108, 4],
        "class_name": "D",
        "angle_deg": -13.81279717416778,
        "defect": None,
        "layer_params": '{"damaged": {"active": false}}',
        "rng_parent_next": 0.04097352393619469,
        "rng_spawn_next": 0.3644334333698406,
    },
    ("auto_base", 0, True): {
        "sha256": "3e352a6b5c857b9eab5af2675c00ad54ee74389a25528553f4e7347079e87288",
        "shape": [106, 108, 4],
        "class_name": "D",
        "angle_deg": -13.81279717416778,
        "defect": "damaged",
        "layer_params": '{"damaged": {"active": true}}',
        "rng_parent_next": 0.04097352393619469,
        "rng_spawn_next": 0.3644334333698406,
    },
    ("auto_base", 1, False): {
        "sha256": "b2084733a01929317bfdd627d4593bbad1b6e0b7ff6091df170a9f24e9825746",
        "shape": [118, 120, 4],
        "class_name": "B",
        "angle_deg": 27.02782177955612,
        "defect": None,
        "layer_params": '{"damaged": {"active": false}}',
        "rng_parent_next": 0.14415961271963373,
        "rng_spawn_next": 0.1141246529720964,
    },
    ("auto_base", 1, True): {
        "sha256": "8ec118329a8137ef62203c5d5fad47e35731afd9197db6d95d194249d49bcd33",
        "shape": [118, 120, 4],
        "class_name": "B",
        "angle_deg": 27.02782177955612,
        "defect": "damaged",
        "layer_params": '{"damaged": {"active": true}}',
        "rng_parent_next": 0.14415961271963373,
        "rng_spawn_next": 0.1141246529720964,
    },
    ("auto_base", 2, False): {
        "sha256": "b1c79f69dca0b6f558a73befde1cda6b35269711fbbc743d9feced0e0d2fa1c2",
        "shape": [103, 107, 4],
        "class_name": "D",
        "angle_deg": -12.090531395152603,
        "defect": None,
        "layer_params": '{"damaged": {"active": false}}',
        "rng_parent_next": 0.8142257405942803,
        "rng_spawn_next": 0.2189446388667029,
    },
    ("auto_base", 2, True): {
        "sha256": "3256dc5fb83a1fb55ff9e9bd9b1ec9124f243d4382e7f9cdc5531cfc4ab2360a",
        "shape": [103, 107, 4],
        "class_name": "D",
        "angle_deg": -12.090531395152603,
        "defect": "damaged",
        "layer_params": '{"damaged": {"active": true}}',
        "rng_parent_next": 0.8142257405942803,
        "rng_spawn_next": 0.2189446388667029,
    },
    ("auto_base", 3, False): {
        "sha256": "f1b4055f725567b5effc374089d78241dc24958cdd8b464b7783ad590fb48dd9",
        "shape": [108, 111, 4],
        "class_name": "D",
        "angle_deg": -15.791369604234017,
        "defect": None,
        "layer_params": '{"damaged": {"active": false}}',
        "rng_parent_next": 0.8012744652063969,
        "rng_spawn_next": 0.3726446071004952,
    },
    ("auto_base", 3, True): {
        "sha256": "3f709307be6b18ad5a7690a9cacc2f29870540564ca90a3be467ac50b1e20403",
        "shape": [108, 111, 4],
        "class_name": "D",
        "angle_deg": -15.791369604234017,
        "defect": "damaged",
        "layer_params": '{"damaged": {"active": true}}',
        "rng_parent_next": 0.8012744652063969,
        "rng_spawn_next": 0.3726446071004952,
    },
    ("auto_base", 4, False): {
        "sha256": "8972586584b39b51441498d70bbadb3582dd487def86cf2aa3b34a3a861fc698",
        "shape": [88, 92, 4],
        "class_name": "C",
        "angle_deg": 0.6796531688616945,
        "defect": None,
        "layer_params": '{"damaged": {"active": false}}',
        "rng_parent_next": 0.9762437057077041,
        "rng_spawn_next": 0.7057556751866344,
    },
    ("auto_base", 4, True): {
        "sha256": "a2625438b6d6fcc19ba48a948cf714266a165c611692d1d7ff77816c4ab5daac",
        "shape": [88, 92, 4],
        "class_name": "C",
        "angle_deg": 0.6796531688616945,
        "defect": "damaged",
        "layer_params": '{"damaged": {"active": true}}',
        "rng_parent_next": 0.9762437057077041,
        "rng_spawn_next": 0.7057556751866344,
    },
    ("no_catalog", 0, False): {
        "sha256": "0e4cbc5abcd6ba1aedc63d39bdb044622c50d507ba6562d406a8bc455f82d209",
        "shape": [64, 64, 4],
        "class_name": "",
        "angle_deg": 8.217701239287258,
        "defect": None,
        "layer_params": '{"damaged": {"active": false}, "ring": {"angle_deg": 3.3529138896543564, "hue_shift_deg": 12.939749858294917, "offset_x_px": 1.4175748558008152, "offset_y_px": 0.0, "scale": 0.9692399319284539}}',
        "rng_parent_next": 0.2697867137638703,
        "rng_spawn_next": 0.3644334333698406,
    },
    ("no_catalog", 0, True): {
        "sha256": "8af47690f681e5e10d5e6eb7b3b0e71f5555a931eb873ed79592ac0a7bf4c19f",
        "shape": [64, 64, 4],
        "class_name": "",
        "angle_deg": 8.217701239287258,
        "defect": "damaged",
        "layer_params": '{"damaged": {"active": true}, "ring": {"angle_deg": 3.3529138896543564, "hue_shift_deg": 12.939749858294917, "offset_x_px": 1.4175748558008152, "offset_y_px": 0.0, "scale": 0.9692399319284539}}',
        "rng_parent_next": 0.2697867137638703,
        "rng_spawn_next": 0.3644334333698406,
    },
    ("no_catalog", 1, False): {
        "sha256": "3e40a66268d3225c51fa9495ead68c47e11e63f5073ef841c0dc27417ee36d7c",
        "shape": [57, 57, 4],
        "class_name": "",
        "angle_deg": 0.7092974820154012,
        "defect": None,
        "layer_params": '{"damaged": {"active": false}, "ring": {"angle_deg": -7.647413278918042, "hue_shift_deg": 4.514232848784033, "offset_x_px": -0.19388385128007535, "offset_y_px": 0.0, "scale": 0.8901565605804612}}',
        "rng_parent_next": 0.9504636963259353,
        "rng_spawn_next": 0.1141246529720964,
    },
    ("no_catalog", 1, True): {
        "sha256": "7e017f4df2938eb4f388f562fec390ce5cc3d33b3dde4511ccf4c8db683e5fb4",
        "shape": [57, 57, 4],
        "class_name": "",
        "angle_deg": 0.7092974820154012,
        "defect": "damaged",
        "layer_params": '{"damaged": {"active": true}, "ring": {"angle_deg": -7.647413278918042, "hue_shift_deg": 4.514232848784033, "offset_x_px": -0.19388385128007535, "offset_y_px": 0.0, "scale": 0.8901565605804612}}',
        "rng_parent_next": 0.9504636963259353,
        "rng_spawn_next": 0.1141246529720964,
    },
    ("no_catalog", 2, False): {
        "sha256": "99c483ff2f623a60e287cecb5a072143ab559806be01f65bfd2985031b5a9167",
        "shape": [69, 69, 4],
        "class_name": "",
        "angle_deg": -14.303271945041017,
        "defect": None,
        "layer_params": '{"damaged": {"active": false}, "ring": {"angle_deg": 1.723665733999887, "hue_shift_deg": 16.398585446157377, "offset_x_px": 3.410571608504892, "offset_y_px": 0.0, "scale": 1.1303847729045873}}',
        "rng_parent_next": 0.2984911434141233,
        "rng_spawn_next": 0.2189446388667029,
    },
    ("no_catalog", 2, True): {
        "sha256": "46a88f2ab7c8a88a24200497784f8ec95b2a8770b5bba7d5a9476709d1954c6c",
        "shape": [69, 69, 4],
        "class_name": "",
        "angle_deg": -14.303271945041017,
        "defect": "damaged",
        "layer_params": '{"damaged": {"active": true}, "ring": {"angle_deg": 1.723665733999887, "hue_shift_deg": 16.398585446157377, "offset_x_px": 3.410571608504892, "offset_y_px": 0.0, "scale": 1.1303847729045873}}',
        "rng_parent_next": 0.2984911434141233,
        "rng_spawn_next": 0.2189446388667029,
    },
    ("no_catalog", 3, False): {
        "sha256": "4914fc4071531da289d4f6e66080043b2583c8dcbcca25fa58d9dd6e7154f299",
        "shape": [75, 75, 4],
        "class_name": "",
        "angle_deg": -24.86104997138254,
        "defect": None,
        "layer_params": '{"damaged": {"active": false}, "ring": {"angle_deg": 0.8665044039145915, "hue_shift_deg": 11.524590245841328, "offset_x_px": -3.197311770707202, "offset_y_px": 0.0, "scale": 1.165515439261267}}',
        "rng_parent_next": 0.2368105065960997,
        "rng_spawn_next": 0.3726446071004952,
    },
    ("no_catalog", 3, True): {
        "sha256": "d970c00c8e237baacede76b4744e1d8e37a2f4b7c37a69a3b55a78ad2b474122",
        "shape": [75, 75, 4],
        "class_name": "",
        "angle_deg": -24.86104997138254,
        "defect": "damaged",
        "layer_params": '{"damaged": {"active": true}, "ring": {"angle_deg": 0.8665044039145915, "hue_shift_deg": 11.524590245841328, "offset_x_px": -3.197311770707202, "offset_y_px": 0.0, "scale": 1.165515439261267}}',
        "rng_parent_next": 0.2368105065960997,
        "rng_spawn_next": 0.3726446071004952,
    },
    ("no_catalog", 4, False): {
        "sha256": "1240c2883c57405192d43800c7ecbfd43751c2ec0696e49874dc56f6ccdbb771",
        "shape": [76, 76, 4],
        "class_name": "",
        "angle_deg": 26.58336633434206,
        "defect": None,
        "layer_params": '{"damaged": {"active": false}, "ring": {"angle_deg": -2.4830005320499247, "hue_shift_deg": 9.614916664605925, "offset_x_px": 3.819717042036892, "offset_y_px": 0.0, "scale": 1.0294932770755114}}',
        "rng_parent_next": 0.5113275528143616,
        "rng_spawn_next": 0.7057556751866344,
    },
    ("no_catalog", 4, True): {
        "sha256": "f812dddd3d6285a348d6c1d9d44322b8e307c96d4b14786b7d3df1a23774ae24",
        "shape": [76, 76, 4],
        "class_name": "",
        "angle_deg": 26.58336633434206,
        "defect": "damaged",
        "layer_params": '{"damaged": {"active": true}, "ring": {"angle_deg": -2.4830005320499247, "hue_shift_deg": 9.614916664605925, "offset_x_px": 3.819717042036892, "offset_y_px": 0.0, "scale": 1.0294932770755114}}',
        "rng_parent_next": 0.5113275528143616,
        "rng_spawn_next": 0.7057556751866344,
    },
    ("defect_half", 0, False): {
        "sha256": "7b99633ceba9206e08bf8cd99cc9c2b1e8855adc24f3e49ccbbf4ac882a491dc",
        "shape": [49, 51, 4],
        "class_name": "D",
        "angle_deg": -13.81279717416778,
        "defect": None,
        "layer_params": '{"damaged": {"active": false}, "ring": {"angle_deg": 3.3529138896543564, "hue_shift_deg": 12.939749858294917, "offset_x_px": 1.4175748558008152, "offset_y_px": 0.0, "scale": 0.9692399319284539}}',
        "rng_parent_next": 0.04097352393619469,
        "rng_spawn_next": 0.3644334333698406,
    },
    ("defect_half", 0, True): {
        "sha256": "65258538843cbd2f1d9019428fc4c102a256a2ef6c80b53c145dbeaa70e8d5c7",
        "shape": [49, 51, 4],
        "class_name": "D",
        "angle_deg": -13.81279717416778,
        "defect": "damaged",
        "layer_params": '{"damaged": {"active": true}, "ring": {"angle_deg": 3.3529138896543564, "hue_shift_deg": 12.939749858294917, "offset_x_px": 1.4175748558008152, "offset_y_px": 0.0, "scale": 0.9692399319284539}}',
        "rng_parent_next": 0.04097352393619469,
        "rng_spawn_next": 0.3644334333698406,
    },
    ("defect_half", 1, False): {
        "sha256": "c12bd6bf886abf5e654e2939fc6e6f52219a1c0ad9896a724e9a5beb93a25981",
        "shape": [54, 54, 4],
        "class_name": "B",
        "angle_deg": 27.02782177955612,
        "defect": "damaged",
        "layer_params": '{"damaged": {"active": true}, "ring": {"angle_deg": -7.647413278918042, "hue_shift_deg": 4.514232848784033, "offset_x_px": -0.19388385128007535, "offset_y_px": 0.0, "scale": 0.8901565605804612}}',
        "rng_parent_next": 0.14415961271963373,
        "rng_spawn_next": 0.1141246529720964,
    },
    ("defect_half", 1, True): {
        "sha256": "c12bd6bf886abf5e654e2939fc6e6f52219a1c0ad9896a724e9a5beb93a25981",
        "shape": [54, 54, 4],
        "class_name": "B",
        "angle_deg": 27.02782177955612,
        "defect": "damaged",
        "layer_params": '{"damaged": {"active": true}, "ring": {"angle_deg": -7.647413278918042, "hue_shift_deg": 4.514232848784033, "offset_x_px": -0.19388385128007535, "offset_y_px": 0.0, "scale": 0.8901565605804612}}',
        "rng_parent_next": 0.14415961271963373,
        "rng_spawn_next": 0.1141246529720964,
    },
    ("defect_half", 2, False): {
        "sha256": "ca2f58ad507e727a35194e79f811b70a34baac2035b75349d460ec7e38036b34",
        "shape": [52, 60, 4],
        "class_name": "D",
        "angle_deg": -12.090531395152603,
        "defect": "damaged",
        "layer_params": '{"damaged": {"active": true}, "ring": {"angle_deg": 1.723665733999887, "hue_shift_deg": 16.398585446157377, "offset_x_px": 3.410571608504892, "offset_y_px": 0.0, "scale": 1.1303847729045873}}',
        "rng_parent_next": 0.8142257405942803,
        "rng_spawn_next": 0.2189446388667029,
    },
    ("defect_half", 2, True): {
        "sha256": "ca2f58ad507e727a35194e79f811b70a34baac2035b75349d460ec7e38036b34",
        "shape": [52, 60, 4],
        "class_name": "D",
        "angle_deg": -12.090531395152603,
        "defect": "damaged",
        "layer_params": '{"damaged": {"active": true}, "ring": {"angle_deg": 1.723665733999887, "hue_shift_deg": 16.398585446157377, "offset_x_px": 3.410571608504892, "offset_y_px": 0.0, "scale": 1.1303847729045873}}',
        "rng_parent_next": 0.8142257405942803,
        "rng_spawn_next": 0.2189446388667029,
    },
    ("defect_half", 3, False): {
        "sha256": "d68af2628d26fd70ce89ae088c14b2ceefd164796a290abacd083b289b0bdbc4",
        "shape": [52, 50, 4],
        "class_name": "D",
        "angle_deg": -15.791369604234017,
        "defect": "damaged",
        "layer_params": '{"damaged": {"active": true}, "ring": {"angle_deg": 0.8665044039145915, "hue_shift_deg": 11.524590245841328, "offset_x_px": -3.197311770707202, "offset_y_px": 0.0, "scale": 1.165515439261267}}',
        "rng_parent_next": 0.8012744652063969,
        "rng_spawn_next": 0.3726446071004952,
    },
    ("defect_half", 3, True): {
        "sha256": "d68af2628d26fd70ce89ae088c14b2ceefd164796a290abacd083b289b0bdbc4",
        "shape": [52, 50, 4],
        "class_name": "D",
        "angle_deg": -15.791369604234017,
        "defect": "damaged",
        "layer_params": '{"damaged": {"active": true}, "ring": {"angle_deg": 0.8665044039145915, "hue_shift_deg": 11.524590245841328, "offset_x_px": -3.197311770707202, "offset_y_px": 0.0, "scale": 1.165515439261267}}',
        "rng_parent_next": 0.8012744652063969,
        "rng_spawn_next": 0.3726446071004952,
    },
    ("defect_half", 4, False): {
        "sha256": "07695f1875448fa40337aa17ba3a979d792347500f093ebabe455edf26fb9a75",
        "shape": [41, 51, 4],
        "class_name": "C",
        "angle_deg": 0.6796531688616945,
        "defect": "damaged",
        "layer_params": '{"damaged": {"active": true}, "ring": {"angle_deg": -2.4830005320499247, "hue_shift_deg": 9.614916664605925, "offset_x_px": 3.819717042036892, "offset_y_px": 0.0, "scale": 1.0294932770755114}}',
        "rng_parent_next": 0.9762437057077041,
        "rng_spawn_next": 0.7057556751866344,
    },
    ("defect_half", 4, True): {
        "sha256": "07695f1875448fa40337aa17ba3a979d792347500f093ebabe455edf26fb9a75",
        "shape": [41, 51, 4],
        "class_name": "C",
        "angle_deg": 0.6796531688616945,
        "defect": "damaged",
        "layer_params": '{"damaged": {"active": true}, "ring": {"angle_deg": -2.4830005320499247, "hue_shift_deg": 9.614916664605925, "offset_x_px": 3.819717042036892, "offset_y_px": 0.0, "scale": 1.0294932770755114}}',
        "rng_parent_next": 0.9762437057077041,
        "rng_spawn_next": 0.7057556751866344,
    },
}
_A4_ERROR_TEXT = "LayeredObject 'obj-7': итоговый RGBA полностью прозрачен"
_A6_GRID: dict[str, dict[str, Any]] = {
    "class_layer": {
        "png_sha256": "641f04da46c495117064cc5e7c536d1bc6a62c8cbbf90f6e1a0f21436f718bab",
        "pixels_shape": [64, 256, 3],
        "pixels_sha256": "bbe52263a4f4645c638e636ad8a63afbdccb20fe9a69b6b10392805e74bfdd5a",
        "tiles_json": '[{"class_name": "D", "layer_params": {"damaged": {"active": false}, "ring": {"angle_deg": 3.5284587414785307, "hue_shift_deg": -10.153633938165285, "offset_x_px": 2.7061691836572814, "offset_y_px": 0.0, "scale": 1.0811350343972639}}, "seed": 0}, {"class_name": "B", "layer_params": {"damaged": {"active": false}, "ring": {"angle_deg": -2.367006024586166, "hue_shift_deg": 8.944364495942946, "offset_x_px": -2.1346535711985357, "offset_y_px": 0.0, "scale": 1.0847036082135217}}, "seed": 1}, {"class_name": "D", "layer_params": {"damaged": {"active": false}, "ring": {"angle_deg": 4.9247624221369115, "hue_shift_deg": -1.662163471547771, "offset_x_px": -1.275288260906363, "offset_y_px": 0.0, "scale": 1.085577493365013}}, "seed": 2}, {"class_name": "D", "layer_params": {"damaged": {"active": false}, "ring": {"angle_deg": 12.975542088417846, "hue_shift_deg": -1.4846547773968268, "offset_x_px": -3.555081241051812, "offset_y_px": 0.0, "scale": 1.1556168062187342}}, "seed": 3}]',
    },
    "no_catalog": {
        "png_sha256": "93c423f133f676001f7b0f73587982a925f577eaa21abb4eb276ee5f318fe419",
        "pixels_shape": [64, 256, 3],
        "pixels_sha256": "fefedca6a0374d5fb9d394abda52ca42b57a99bfea9dcd820945af22758d68e8",
        "tiles_json": '[{"class_name": "", "layer_params": {"damaged": {"active": false}, "ring": {"angle_deg": 3.3529138896543564, "hue_shift_deg": 12.939749858294917, "offset_x_px": 1.4175748558008152, "offset_y_px": 0.0, "scale": 0.9692399319284539}}, "seed": 0}, {"class_name": "", "layer_params": {"damaged": {"active": false}, "ring": {"angle_deg": -7.647413278918042, "hue_shift_deg": 4.514232848784033, "offset_x_px": -0.19388385128007535, "offset_y_px": 0.0, "scale": 0.8901565605804612}}, "seed": 1}, {"class_name": "", "layer_params": {"damaged": {"active": false}, "ring": {"angle_deg": 1.723665733999887, "hue_shift_deg": 16.398585446157377, "offset_x_px": 3.410571608504892, "offset_y_px": 0.0, "scale": 1.1303847729045873}}, "seed": 2}, {"class_name": "", "layer_params": {"damaged": {"active": false}, "ring": {"angle_deg": 0.8665044039145915, "hue_shift_deg": 11.524590245841328, "offset_x_px": -3.197311770707202, "offset_y_px": 0.0, "scale": 1.165515439261267}}, "seed": 3}]',
    },
}
_A6_LAYOUT: dict[tuple[str, int], str] = {
    ("class_layer", 0): "b5cafd9fedbfbc172154f7d4dcfd595b58a272c5dd4dadb8b3370378acaba05e",
    ("class_layer", 1): "4a6dcfc8737f15699b60bc0e415cdbaaf06ca64d66ab28f7f298cdf228134189",
    ("class_layer", 2): "b5cafd9fedbfbc172154f7d4dcfd595b58a272c5dd4dadb8b3370378acaba05e",
    ("auto_base", 0): "85c804f6c9340f2db41dd91be40d0fbfea118c9e5c731b0e89fbee2af76d3e5b",
    ("auto_base", 1): "b77c77fbad54ce31e10911321bd698aa2b7d323cdceee142d08c04d7ebaf725a",
    ("auto_base", 2): "85c804f6c9340f2db41dd91be40d0fbfea118c9e5c731b0e89fbee2af76d3e5b",
    ("no_catalog", 0): "18a7aaa34910bde755a3edd2d81e7bf700b86b1d9d842a26860130c49b299471",
    ("no_catalog", 1): "18a7aaa34910bde755a3edd2d81e7bf700b86b1d9d842a26860130c49b299471",
    ("no_catalog", 2): "18a7aaa34910bde755a3edd2d81e7bf700b86b1d9d842a26860130c49b299471",
}
# END LITERALS


# --------------------------------------------------------------------------- #
# Вспомогательное: получить объект по дороге                                  #
# --------------------------------------------------------------------------- #

_RESULT_CACHE: dict[tuple[int, str, str, int, bool], dict[str, Any]] = {}


def _fingerprint(
    rgba: np.ndarray, class_name: str, angle_deg: float, defect: str | None, layer_params: Any, rng: np.random.Generator
) -> dict[str, Any]:
    # после вызова: расход родителя (класс, угол, спрайт) и счётчик spawn (compose_layers зовёт spawn ровно раз)
    parent_next = float(rng.random())
    spawn_next = float(rng.spawn(1)[0].random())
    return {
        "sha256": hashlib.sha256(rgba.tobytes()).hexdigest(),
        "shape": list(rgba.shape),
        "class_name": class_name,
        "angle_deg": float(angle_deg),
        "defect": defect,
        "layer_params": json.dumps(layer_params, sort_keys=True),
        "rng_parent_next": parent_next,
        "rng_spawn_next": spawn_next,
    }


def _produce(road: str, presets: dict[str, Any], variant: str, seed: int, force: bool) -> dict[str, Any]:
    """Объект по дороге `make` (`line_sim.ObjectFactory.make`) или `render` (`layer_render.factory`)."""
    key = (id(presets), road, variant, seed, force)
    if key in _RESULT_CACHE:
        return _RESULT_CACHE[key]
    rng = np.random.default_rng(seed)
    preset = presets[variant]
    if road == "make":
        from Services.line_sim import ObjectFactory

        factory = ObjectFactory(preset)
        if force:
            factory.force_defect_next()
        obj = factory.make("obj", 0.0, rng)
        params = obj.passport.to_dict()["layer_params"]
        fp = _fingerprint(
            obj.render(), obj.passport.class_name, obj.passport.angle_deg, obj.passport.defect, params, rng
        )
    else:
        factory_mod = importlib.import_module("Services.layer_render.factory")
        layers_mod = importlib.import_module("Services.layer_render.layers")
        factory = factory_mod.ObjectFactory(preset)
        rendered = factory.render(rng, force_defect=force)
        params = layers_mod.json_safe(rendered.layer_params)
        fp = _fingerprint(rendered.rgba, rendered.class_name, rendered.angle_deg, rendered.defect, params, rng)
    _RESULT_CACHE[key] = fp
    return fp


_A3_CASES = [
    pytest.param(road, variant, seed, force, id=f"{road}-{variant}-seed{seed}-force{int(force)}")
    for road in ("make", "render")
    for variant in _VARIANTS
    for seed in _SEEDS
    for force in (False, True)
]


# --------------------------------------------------------------------------- #
# A3. Фабрика даёт прежний объект: каждое свойство — отдельный тест           #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(("road", "variant", "seed", "force"), _A3_CASES)
def test_a3_rgba_bytes_and_shape(presets, road, variant, seed, force) -> None:
    got = _produce(road, presets, variant, seed, force)
    want = _A3[(variant, seed, force)]
    assert (got["shape"], got["sha256"]) == (want["shape"], want["sha256"])


@pytest.mark.parametrize(("road", "variant", "seed", "force"), _A3_CASES)
def test_a3_class_name_and_angle(presets, road, variant, seed, force) -> None:
    got = _produce(road, presets, variant, seed, force)
    want = _A3[(variant, seed, force)]
    assert (got["class_name"], got["angle_deg"]) == (want["class_name"], want["angle_deg"])


@pytest.mark.parametrize(("road", "variant", "seed", "force"), _A3_CASES)
def test_a3_defect(presets, road, variant, seed, force) -> None:
    got = _produce(road, presets, variant, seed, force)
    assert got["defect"] == _A3[(variant, seed, force)]["defect"]


@pytest.mark.parametrize(("road", "variant", "seed", "force"), _A3_CASES)
def test_a3_layer_params(presets, road, variant, seed, force) -> None:
    got = _produce(road, presets, variant, seed, force)
    assert got["layer_params"] == _A3[(variant, seed, force)]["layer_params"]


@pytest.mark.parametrize(("road", "variant", "seed", "force"), _A3_CASES)
def test_a3_parent_rng_stream_after_call(presets, road, variant, seed, force) -> None:
    """Расход родителя: класс -> угол -> спрайт; `spawn` поток родителя не двигает — см. следующий тест."""
    got = _produce(road, presets, variant, seed, force)
    assert got["rng_parent_next"] == _A3[(variant, seed, force)]["rng_parent_next"]


@pytest.mark.parametrize(("road", "variant", "seed", "force"), _A3_CASES)
def test_a3_spawn_counter_after_call(presets, road, variant, seed, force) -> None:
    """`compose_layers` зовёт `rng.spawn(len(layers))` ровно раз: второй вызов даёт ребёнка с индексом N."""
    got = _produce(road, presets, variant, seed, force)
    assert got["rng_spawn_next"] == _A3[(variant, seed, force)]["rng_spawn_next"]


@pytest.mark.parametrize("road", _ROADS)
def test_a3_probability_half_draws_both_outcomes_without_force(presets, road) -> None:
    """Иначе ветка розыгрыша не проверена: при p=0.5 среди seed 0..4 есть и None, и 'damaged'."""
    outcomes = {_produce(road, presets, "defect_half", s, False)["defect"] for s in _SEEDS}
    assert outcomes == {None, "damaged"}


@pytest.mark.parametrize("variant", _VARIANTS)
def test_a3_rendered_rgba_is_read_only(presets, variant) -> None:
    factory_mod = importlib.import_module("Services.layer_render.factory")
    rendered = factory_mod.ObjectFactory(presets[variant]).render(np.random.default_rng(0))
    assert rendered.rgba.flags.writeable is False


def test_a3_rendered_rgba_is_rgba_uint8(presets) -> None:
    factory_mod = importlib.import_module("Services.layer_render.factory")
    rendered = factory_mod.ObjectFactory(presets["class_layer"]).render(np.random.default_rng(0))
    assert (rendered.rgba.dtype, rendered.rgba.ndim, rendered.rgba.shape[2]) == (np.dtype(np.uint8), 3, 4)


def test_a3_rendered_object_is_frozen_and_not_value_comparable(presets) -> None:
    """DESIGN 2.4b: `@dataclass(frozen=True, eq=False)` — запись в поле падает; `==` по ndarray не бросает (сравнение по id)."""
    factory_mod = importlib.import_module("Services.layer_render.factory")
    factory = factory_mod.ObjectFactory(presets["class_layer"])
    a = factory.render(np.random.default_rng(0))
    b = factory.render(np.random.default_rng(0))
    with pytest.raises(dataclasses.FrozenInstanceError):
        a.class_name = "X"  # type: ignore[misc]
    assert (a == a, a == b) == (True, False)


def test_a3_render_label_defaults_to_empty_and_force_defect_defaults_to_false(presets) -> None:
    """Сигнатура: `render(rng, *, force_defect=False, label="")` — вызов только с rng возможен и не форсит брак."""
    factory_mod = importlib.import_module("Services.layer_render.factory")
    rendered = factory_mod.ObjectFactory(presets["class_layer"]).render(np.random.default_rng(0))
    assert rendered.defect is None


def test_a3_render_force_defect_is_keyword_only(presets) -> None:
    factory_mod = importlib.import_module("Services.layer_render.factory")
    factory = factory_mod.ObjectFactory(presets["class_layer"])
    with pytest.raises(TypeError):
        factory.render(np.random.default_rng(0), True)  # type: ignore[misc]


def test_a3_render_does_not_mutate_catalog_between_calls(presets) -> None:
    """Фабрика с кэшами слоёв — без состояния между вызовами: тот же seed дважды -> те же байты."""
    factory_mod = importlib.import_module("Services.layer_render.factory")
    factory = factory_mod.ObjectFactory(presets["class_layer"])
    first = factory.render(np.random.default_rng(2), force_defect=True).rgba.tobytes()
    factory.render(np.random.default_rng(3))
    second = factory.render(np.random.default_rng(2), force_defect=True).rgba.tobytes()
    assert first == second


def test_a3_base_factory_properties_num_classes_class_names_defect_probability(presets) -> None:
    factory_mod = importlib.import_module("Services.layer_render.factory")
    with_catalog = factory_mod.ObjectFactory(presets["defect_half"])
    without = factory_mod.ObjectFactory(presets["no_catalog"])
    assert (with_catalog.num_classes, with_catalog.class_names, with_catalog.defect_probability) == (
        4,
        ["A", "B", "C", "D"],
        0.5,
    )
    assert (without.num_classes, without.class_names, without.defect_probability) == (0, [], 0.0)


def test_a3_base_nominal_layers_names_and_read_only(presets) -> None:
    """`nominal_layers(rng)` в базе: слои без defect-слоя, массивы read-only; класс — как у render для того же rng."""
    factory_mod = importlib.import_module("Services.layer_render.factory")
    factory = factory_mod.ObjectFactory(presets["class_layer"])
    class_name, layers = factory.nominal_layers(np.random.default_rng(0))
    rendered = factory.render(np.random.default_rng(0))
    assert (
        [name for name, *_ in layers],
        [arr.flags.writeable for _, arr, *_ in layers],
        class_name == rendered.class_name,
    ) == (["disk", "letter", "ring"], [False, False, False], True)


# --------------------------------------------------------------------------- #
# A4. from_rendered и текст ошибки                                             #
# --------------------------------------------------------------------------- #


def _rendered(presets, variant="class_layer", seed=0, force=True):
    factory_mod = importlib.import_module("Services.layer_render.factory")
    return factory_mod.ObjectFactory(presets[variant]).render(np.random.default_rng(seed), force_defect=force)


def test_a4_from_rendered_passport_fields_equal_rendered_and_arguments(presets) -> None:
    from Services.line_sim.core.layered_object import LayeredObject

    r = _rendered(presets)
    obj = LayeredObject.from_rendered(r, object_id="o-1", spawn_encoder=12.5)
    p = obj.passport
    assert (p.object_id, p.class_name, p.angle_deg, p.defect, p.spawn_encoder, p.layer_params) == (
        "o-1",
        r.class_name,
        r.angle_deg,
        r.defect,
        12.5,
        r.layer_params,
    )


def test_a4_from_rendered_forced_defect_literal(presets) -> None:
    from Services.line_sim.core.layered_object import LayeredObject

    r = _rendered(presets, force=True)
    assert LayeredObject.from_rendered(r, object_id="o-1", spawn_encoder=12.5).passport.defect == "damaged"


def test_a4_from_rendered_lateral_px_is_default_zero(presets) -> None:
    from Services.line_sim.core.layered_object import LayeredObject

    obj = LayeredObject.from_rendered(_rendered(presets), object_id="o-1", spawn_encoder=12.5)
    assert obj.passport.lateral_px == 0.0


def test_a4_from_rendered_render_returns_the_same_array_without_copy(presets) -> None:
    from Services.line_sim.core.layered_object import LayeredObject

    r = _rendered(presets)
    obj = LayeredObject.from_rendered(r, object_id="o-1", spawn_encoder=12.5)
    assert obj.render() is r.rgba


def test_a4_from_rendered_does_not_change_rendered(presets) -> None:
    from Services.line_sim.core.layered_object import LayeredObject

    r = _rendered(presets)
    before = (
        r.defect,
        copy.deepcopy(r.layer_params),
        r.class_name,
        r.angle_deg,
        r.rgba.tobytes(),
        r.rgba.flags.writeable,
    )
    LayeredObject.from_rendered(r, object_id="o-1", spawn_encoder=12.5)
    after = (r.defect, r.layer_params, r.class_name, r.angle_deg, r.rgba.tobytes(), r.rgba.flags.writeable)
    assert after == before


def test_a4_from_rendered_keeps_prior_constructor(presets) -> None:
    """Прежний `__init__(passport, layers, rng)` остаётся — его зовут тесты 2.3 и `test_hazards_look_1_2.py`."""
    from Services.line_sim.core.layered_object import LayeredObject
    from Services.line_sim.interfaces import LayerSpec, ObjectPassport

    layer = LayerSpec(name="d", mode="static", sprite_source=_rand_sprite(np.random.default_rng(7), 24))
    passport = ObjectPassport(object_id="x", class_name="", angle_deg=0.0, defect=None, spawn_encoder=0.0)
    obj = LayeredObject(passport=passport, layers=[layer], rng=np.random.default_rng(0))
    assert obj.render().shape[2] == 4


@pytest.mark.parametrize("road", _ROADS)
def test_a4_transparent_object_error_text_is_the_pre_move_literal(presets, road) -> None:
    rng = np.random.default_rng(0)
    with pytest.raises(ValueError) as excinfo:
        if road == "make":
            from Services.line_sim import ObjectFactory

            ObjectFactory(presets["transparent"]).make("obj-7", 0.0, rng)
        else:
            factory_mod = importlib.import_module("Services.layer_render.factory")
            factory_mod.ObjectFactory(presets["transparent"]).render(rng, label="obj-7")
    assert str(excinfo.value) == _A4_ERROR_TEXT


@pytest.mark.parametrize("variant", _VARIANTS)
def test_a4_transparent_control_catalog_presets_do_not_raise(presets, variant) -> None:
    """Контроль: ошибка — свойство прозрачного пресета без каталога, а не любого пресета."""
    from Services.line_sim import ObjectFactory

    obj = ObjectFactory(presets[variant]).make("obj-7", 0.0, np.random.default_rng(0))
    assert obj.render().shape[2] == 4


# --------------------------------------------------------------------------- #
# A5. Флаг оператора остаётся в line_sim; у базы его нет                       #
# --------------------------------------------------------------------------- #


def test_a5_force_defect_next_gives_damaged_and_clears_the_flag(presets) -> None:
    from Services.line_sim import ObjectFactory

    factory = ObjectFactory(presets["class_layer"])  # defect_probability == 0.0
    factory.force_defect_next()
    pending_before = factory.force_defect_pending
    obj = factory.make("obj", 0.0, np.random.default_rng(0))
    assert (pending_before, obj.passport.defect, factory.force_defect_pending) == (True, "damaged", False)


def test_a5_without_force_probability_zero_gives_no_defect(presets) -> None:
    from Services.line_sim import ObjectFactory

    factory = ObjectFactory(presets["class_layer"])
    obj = factory.make("obj", 0.0, np.random.default_rng(0))
    assert (obj.passport.defect, factory.force_defect_pending) == (None, False)


def test_a5_flag_survives_a_failing_render_and_hits_the_next_success(presets) -> None:
    """Транзитная ошибка каталога не съедает нажатие оператора (подмена метода на ОБЪЕКТЕ каталога, как в test_hazards_3_2)."""
    from Services.line_sim import ObjectFactory

    factory = ObjectFactory(presets["class_layer"])
    original = factory._catalog.get_sprite

    def flaky(*_a: Any, **_k: Any) -> Any:
        raise RuntimeError("catalog blinked")

    factory.force_defect_next()
    factory._catalog.get_sprite = flaky
    with pytest.raises(RuntimeError, match="catalog blinked"):
        factory.make("obj", 0.0, np.random.default_rng(0))
    pending_after_failure = factory.force_defect_pending
    factory._catalog.get_sprite = original
    obj = factory.make("obj", 0.0, np.random.default_rng(0))
    assert (pending_after_failure, obj.passport.defect, factory.force_defect_pending) == (True, "damaged", False)


def test_a5_flag_survives_a_value_error_from_a_transparent_object(presets) -> None:
    """Другой тип отказа: прозрачный итог композиции поднимает ValueError (в `render`/`compose_layers`), флаг остаётся взведённым. Отказ внутри `from_rendered` этим тестом не достижим: он не падает на валидном `RenderedObject`."""
    from Services.line_sim import ObjectFactory

    factory = ObjectFactory(presets["transparent"])
    factory.force_defect_next()
    with pytest.raises(ValueError):
        factory.make("obj-7", 0.0, np.random.default_rng(0))
    assert factory.force_defect_pending is True


def test_a5_base_factory_has_no_operator_flag_on_class(presets) -> None:
    factory_mod = importlib.import_module("Services.layer_render.factory")
    cls = factory_mod.ObjectFactory
    assert (hasattr(cls, "force_defect_next"), hasattr(cls, "force_defect_pending")) == (False, False)


def test_a5_base_factory_has_no_operator_flag_on_instance(presets) -> None:
    factory_mod = importlib.import_module("Services.layer_render.factory")
    inst = factory_mod.ObjectFactory(presets["class_layer"])
    assert (hasattr(inst, "force_defect_next"), hasattr(inst, "force_defect_pending")) == (False, False)


# --------------------------------------------------------------------------- #
# A1. Идентичности имён                                                        #
# --------------------------------------------------------------------------- #

_PREVIEW_ALL = (
    "OUTSIDE_ROOTS_MESSAGE",
    "PREVIEW_DEFAULT_SEEDS",
    "PREVIEW_DEFAULT_TILE_PX",
    "PREVIEW_MAX_SEEDS",
    "PREVIEW_MAX_TILE_PX",
    "PREVIEW_MIN_TILE_PX",
    "PREVIEW_PIXEL_BUDGET",
    "PreviewLimitError",
    "confine_preset_paths",
    "render_layout",
    "render_preview_grid",
    "validate_preview_request",
)
_PREVIEW_CALLABLES = (
    "PreviewLimitError",
    "confine_preset_paths",
    "render_layout",
    "render_preview_grid",
    "validate_preview_request",
)


def test_a1_old_preview_all_is_the_literal_name_set() -> None:
    """Guard: список имён в параметризации ниже — это `__all__` старого модуля превью, без молчаливых потерь."""
    old = importlib.import_module("Services.line_sim.core.preview")
    assert sorted(old.__all__) == sorted(_PREVIEW_ALL)


@pytest.mark.parametrize("name", _PREVIEW_ALL)
def test_a1_preview_name_is_the_layer_render_object(name) -> None:
    old = importlib.import_module("Services.line_sim.core.preview")
    new = importlib.import_module("Services.layer_render.preview")
    assert getattr(old, name) is getattr(new, name)


@pytest.mark.parametrize("name", _PREVIEW_CALLABLES)
def test_a1_preview_function_or_class_module_is_the_new_module(name) -> None:
    old = importlib.import_module("Services.line_sim.core.preview")
    assert getattr(old, name).__module__ == "Services.layer_render.preview"


def test_a1_catalog_bridge_load_catalog_is_the_layer_render_function() -> None:
    bridge = importlib.import_module("Services.line_sim.core.catalog_bridge")
    catalog = importlib.import_module("Services.layer_render.catalog")
    assert bridge.load_catalog is catalog.load_catalog


def test_a1_catalog_bridge_load_image_rgba_is_the_layer_render_function() -> None:
    bridge = importlib.import_module("Services.line_sim.core.catalog_bridge")
    io_mod = importlib.import_module("Services.layer_render.io")
    assert bridge.load_image_rgba is io_mod.load_image_rgba


@pytest.mark.parametrize("name", ("load_catalog", "load_image_rgba"))
def test_a1_catalog_bridge_function_module_is_the_new_module(name) -> None:
    bridge = importlib.import_module("Services.line_sim.core.catalog_bridge")
    expected = {"load_catalog": "Services.layer_render.catalog", "load_image_rgba": "Services.layer_render.io"}[name]
    assert getattr(bridge, name).__module__ == expected


def test_a1_interfaces_json_safe_is_the_layer_render_function() -> None:
    interfaces = importlib.import_module("Services.line_sim.interfaces")
    layers = importlib.import_module("Services.layer_render.layers")
    assert interfaces._json_safe is layers.json_safe


def test_a1_json_safe_converts_numpy_scalars_recursively() -> None:
    """Тело `_json_safe` дословно: numpy-скаляры -> нативные типы, контейнеры обходятся, остальное не тронуто."""
    layers = importlib.import_module("Services.layer_render.layers")
    out = layers.json_safe({"a": np.float32(0.5), "b": [np.bool_(True), {"c": np.int64(3)}], "d": "s", "e": (1, 2)})
    assert (out, type(out["a"]), type(out["b"][0]), type(out["b"][1]["c"])) == (
        {"a": 0.5, "b": [True, {"c": 3}], "d": "s", "e": (1, 2)},
        float,
        bool,
        int,
    )


@pytest.mark.parametrize("name", ("_DEFECT_SIDE_FRAC", "_DEFECT_OFFSET_FRAC"))
def test_a1_line_sim_factory_defect_constants_equal_layer_render_values(name) -> None:
    old = importlib.import_module("Services.line_sim.core.factory")
    new = importlib.import_module("Services.layer_render.factory")
    assert getattr(old, name) == getattr(new, name)


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("_DEFECT_LAYER_NAME", "damaged"),
        ("_DEFECT_COLOR_RGB", (60.0, 60.0, 60.0)),
        ("_DEFECT_SIDE_FRAC", 0.35),
        ("_DEFECT_OFFSET_FRAC", 0.15),
    ],
)
def test_a1_layer_render_factory_defect_constant_literal(name, value) -> None:
    """Литерал константы: равенство «старый == новый» молчит, если обе копии испортили одинаково."""
    new = importlib.import_module("Services.layer_render.factory")
    assert getattr(new, name) == value


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("PREVIEW_MAX_SEEDS", 16),
        ("PREVIEW_DEFAULT_SEEDS", (1, 2, 3, 4, 5, 6, 7, 8)),
        ("PREVIEW_DEFAULT_TILE_PX", 160),
        ("PREVIEW_MIN_TILE_PX", 16),
        ("PREVIEW_MAX_TILE_PX", 256),
        ("PREVIEW_PIXEL_BUDGET", 204800),
        ("PREVIEW_BG_RGB", (90, 90, 90)),
        (
            "OUTSIDE_ROOTS_MESSAGE",
            "preset: путь изображения вне разрешённых каталогов (корень репозитория, каталог пресета)",
        ),
    ],
)
def test_a1_preview_constant_value_in_new_module(name, value) -> None:
    """`is` для малых int вакуумна (CPython кэширует -5..256): значение копии держит этот литерал."""
    new = importlib.import_module("Services.layer_render.preview")
    assert getattr(new, name) == value


@pytest.mark.parametrize(
    "name", ("render_preview_grid", "validate_preview_request", "confine_preset_paths", "PreviewLimitError")
)
def test_a1_package_level_name_is_the_layer_render_object(name) -> None:
    pkg = importlib.import_module("Services.line_sim")
    new = importlib.import_module("Services.layer_render.preview")
    assert getattr(pkg, name) is getattr(new, name)


def test_a1_core_package_outside_roots_message_is_the_layer_render_object() -> None:
    core = importlib.import_module("Services.line_sim.core")
    new = importlib.import_module("Services.layer_render.preview")
    assert core.OUTSIDE_ROOTS_MESSAGE is new.OUTSIDE_ROOTS_MESSAGE


@pytest.mark.parametrize(
    "name", ("render_preview_grid", "validate_preview_request", "confine_preset_paths", "PreviewLimitError")
)
def test_a1_core_package_level_name_is_the_layer_render_object(name) -> None:
    core = importlib.import_module("Services.line_sim.core")
    new = importlib.import_module("Services.layer_render.preview")
    assert getattr(core, name) is getattr(new, name)


@pytest.mark.parametrize(
    ("name", "owner"),
    [
        ("apply_occlusion", "Services.layer_render.effects"),
        ("load_layer_sprite", "Services.layer_render.layers"),
    ],
)
def test_a1_line_sim_factory_module_keeps_globals_that_tests_read(name, owner) -> None:
    """Потребители глобалов модуля (`test_acceptance_2_2_effects.py:339`, `test_acceptance_2_3_layers.py:1172`)."""
    old = importlib.import_module("Services.line_sim.core.factory")
    assert getattr(old, name) is getattr(importlib.import_module(owner), name)


@pytest.mark.parametrize("name", ("_DEFECT_SIDE_FRAC", "_DEFECT_OFFSET_FRAC", "apply_occlusion", "load_layer_sprite"))
def test_a1_line_sim_factory_all_lists_the_reexported_globals(name) -> None:
    """Без `__all__` ruff снимет неиспользуемый импорт, и глобал исчезнет молча."""
    old = importlib.import_module("Services.line_sim.core.factory")
    assert name in old.__all__


def test_a1_layered_object_all_still_has_canvas_size() -> None:
    old = importlib.import_module("Services.line_sim.core.layered_object")
    assert "canvas_size" in old.__all__


# --------------------------------------------------------------------------- #
# A2. Наследование и AST                                                       #
# --------------------------------------------------------------------------- #


def test_a2_line_sim_object_factory_subclasses_the_base() -> None:
    from Services.line_sim import ObjectFactory as Sim

    base = importlib.import_module("Services.layer_render.factory").ObjectFactory
    assert issubclass(Sim, base)


def test_a2_the_two_classes_are_different_objects() -> None:
    from Services.line_sim import ObjectFactory as Sim

    base = importlib.import_module("Services.layer_render.factory").ObjectFactory
    assert Sim is not base


def test_a2_package_level_and_core_object_factory_is_the_same_subclass() -> None:
    import Services.line_sim as pkg
    from Services.line_sim.core.factory import ObjectFactory as core_cls

    assert pkg.ObjectFactory is core_cls


def test_a2_build_defect_blob_is_inherited_not_redefined() -> None:
    from Services.line_sim import ObjectFactory as Sim

    base = importlib.import_module("Services.layer_render.factory").ObjectFactory
    assert Sim._build_defect_blob is base._build_defect_blob


def _parse(rel: str) -> ast.Module:
    path = _ROOT / rel
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _defined_function_names(tree: ast.Module) -> set[str]:
    return {n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}


def _assigned_names(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
            targets = [node.target]
        for target in targets:
            for sub in ast.walk(target):
                if isinstance(sub, ast.Name):
                    names.add(sub.id)
                elif isinstance(sub, ast.Attribute):
                    names.add(sub.attr)
    return names


@pytest.mark.parametrize("name", ("render", "nominal_layers", "_resolve_bottom_layers", "_build_defect_blob"))
def test_a2_line_sim_factory_defines_no_method_named(name) -> None:
    tree = _parse("Services/line_sim/core/factory.py")
    assert name not in _defined_function_names(tree)


@pytest.mark.parametrize(
    "name", ("_DEFECT_LAYER_NAME", "_DEFECT_COLOR_RGB", "_DEFECT_SIDE_FRAC", "_DEFECT_OFFSET_FRAC")
)
def test_a2_line_sim_factory_does_not_assign(name) -> None:
    tree = _parse("Services/line_sim/core/factory.py")
    assert name not in _assigned_names(tree)


@pytest.mark.parametrize("rel", ("Services/line_sim/core/preview.py", "Services/line_sim/core/catalog_bridge.py"))
def test_a2_reexport_modules_define_no_function_or_class(rel) -> None:
    tree = _parse(rel)
    defined = {n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}
    assert defined == set()


@pytest.mark.parametrize("rel", ("Services/line_sim/core/preview.py", "Services/line_sim/core/catalog_bridge.py"))
def test_a2_reexport_modules_assign_nothing_but_dunder_all(rel) -> None:
    tree = _parse(rel)
    assert _assigned_names(tree) - {"__all__"} == set()


@pytest.mark.parametrize("rel", ("Services/line_sim/core/preview.py", "Services/line_sim/core/catalog_bridge.py"))
def test_a2_reexport_modules_declare_dunder_all(rel) -> None:
    """Реэкспорт без `__all__` ruff F401 снимет."""
    assert "__all__" in _assigned_names(_parse(rel))


def test_a2_interfaces_does_not_define_json_safe() -> None:
    tree = _parse("Services/line_sim/interfaces.py")
    assert "_json_safe" not in _defined_function_names(tree)


def test_a2_interfaces_keeps_the_name_json_safe_importable() -> None:
    from Services.line_sim.interfaces import _json_safe

    assert _json_safe({"x": np.float32(1.5)}) == {"x": 1.5}


# --------------------------------------------------------------------------- #
# A6. Превью побайтно прежнее                                                  #
# --------------------------------------------------------------------------- #

_PREVIEW_ROADS = (
    pytest.param("Services.line_sim.core.preview", id="old"),
    pytest.param("Services.layer_render.preview", id="new"),
)
_GRID_VARIANTS = ("class_layer", "no_catalog")


def _grid(module: str, preset: Any) -> tuple[bytes, list[dict]]:
    return importlib.import_module(module).render_preview_grid(preset, [0, 1, 2, 3], 64)


@pytest.mark.parametrize("module", _PREVIEW_ROADS)
@pytest.mark.parametrize("variant", _GRID_VARIANTS)
def test_a6_grid_png_file_bytes_sha256(presets, module, variant) -> None:
    png, _ = _grid(module, presets[variant])
    assert hashlib.sha256(png).hexdigest() == _A6_GRID[variant]["png_sha256"]


@pytest.mark.parametrize("module", _PREVIEW_ROADS)
@pytest.mark.parametrize("variant", _GRID_VARIANTS)
def test_a6_grid_decoded_pixels_sha256(presets, module, variant) -> None:
    png, _ = _grid(module, presets[variant])
    pixels = cv2.imdecode(np.frombuffer(png, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
    assert (list(pixels.shape), hashlib.sha256(pixels.tobytes()).hexdigest()) == (
        _A6_GRID[variant]["pixels_shape"],
        _A6_GRID[variant]["pixels_sha256"],
    )


@pytest.mark.parametrize("module", _PREVIEW_ROADS)
@pytest.mark.parametrize("variant", _GRID_VARIANTS)
def test_a6_grid_tiles_json(presets, module, variant) -> None:
    _, tiles = _grid(module, presets[variant])
    assert json.dumps(tiles, sort_keys=True) == _A6_GRID[variant]["tiles_json"]


@pytest.mark.parametrize("module", _PREVIEW_ROADS)
def test_a6_grid_is_stable_across_a_cache_hit(presets, module) -> None:
    """Второй вызов с тем же пресетом идёт через кэш фабрики и обязан дать те же байты."""
    first, _ = _grid(module, presets["class_layer"])
    second, _ = _grid(module, presets["class_layer"])
    assert (
        hashlib.sha256(second).hexdigest() == hashlib.sha256(first).hexdigest() == _A6_GRID["class_layer"]["png_sha256"]
    )


@pytest.mark.parametrize("module", _PREVIEW_ROADS)
@pytest.mark.parametrize("variant", ("class_layer", "auto_base", "no_catalog"))
@pytest.mark.parametrize("seed", (0, 1, 2))
def test_a6_layout_sha256(presets, module, variant, seed) -> None:
    layout = importlib.import_module(module).render_layout(presets[variant], seed)
    assert hashlib.sha256(json.dumps(layout, sort_keys=True).encode("utf-8")).hexdigest() == _A6_LAYOUT[(variant, seed)]


def test_a6_new_preview_tile_class_name_matches_the_make_road(presets) -> None:
    """Плитка строится через `ObjectFactory.render(default_rng(seed), label=f"preview-{seed}")`: класс тот же, что у `make`."""
    from Services.line_sim import ObjectFactory

    new = importlib.import_module("Services.layer_render.preview")
    _, tiles = new.render_preview_grid(presets["class_layer"], [0, 1, 2, 3], 64)
    factory = ObjectFactory(presets["class_layer"])
    via_make = [factory.make(f"preview-{s}", 0.0, np.random.default_rng(s)).passport.class_name for s in range(4)]
    assert [t["class_name"] for t in tiles] == via_make


def test_a6_cache_holds_the_layer_render_base_factory(presets) -> None:
    new = importlib.import_module("Services.layer_render.preview")
    base = importlib.import_module("Services.layer_render.factory").ObjectFactory
    new.render_preview_grid(presets["class_layer"], [0], 32)
    cached = new._factory_cache
    assert cached is not None and type(cached[1]) is base


@pytest.mark.parametrize("module", _PREVIEW_ROADS)
def test_a6_limit_error_text_is_unchanged(module) -> None:
    mod = importlib.import_module(module)
    with pytest.raises(mod.PreviewLimitError) as excinfo:
        mod.validate_preview_request([0] * 17, 64)
    assert str(excinfo.value) == "preset.preview: seeds — список 1..16 целых >= 0"


# --------------------------------------------------------------------------- #
# A7. Цикла импорта нет в любом порядке: чистый процесс, модуль — первым      #
# --------------------------------------------------------------------------- #

_IMPORT_FIRST = (
    "Services.layer_render",
    "Services.layer_render.factory",
    "Services.layer_render.preview",
    "Services.line_sim",
    "Services.line_sim.core.factory",
    "Services.line_sim.core.preview",
    "Services.line_sim.core.catalog_bridge",
    "Services.line_sim.core.layered_object",
    "Services.line_sim.interfaces",
    "Services.dataset_gen",
    "Plugins.sim.layer_preview.plugin",
    "Plugins.sim.scene_source.plugin",
)


@pytest.mark.parametrize("module", _IMPORT_FIRST)
def test_a7_module_imports_first_in_a_clean_process(module) -> None:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(_ROOT)
    proc = subprocess.run(
        [sys.executable, "-c", f"import {module}"],
        cwd=str(_ROOT),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=150,
    )
    assert proc.returncode == 0, f"import {module} -> rc={proc.returncode}\nSTDERR:\n{proc.stderr[-2000:]}"


# --------------------------------------------------------------------------- #
# A8. Services.layer_render.__all__                                            #
# --------------------------------------------------------------------------- #

_A8_OWNERS = {
    "ObjectFactory": "Services.layer_render.factory",
    "RenderedObject": "Services.layer_render.factory",
    "render_preview_grid": "Services.layer_render.preview",
    "render_layout": "Services.layer_render.preview",
    "validate_preview_request": "Services.layer_render.preview",
    "confine_preset_paths": "Services.layer_render.preview",
    "PreviewLimitError": "Services.layer_render.preview",
    "OUTSIDE_ROOTS_MESSAGE": "Services.layer_render.preview",
    "load_catalog": "Services.layer_render.catalog",
    "load_image_rgba": "Services.layer_render.io",
    "json_safe": "Services.layer_render.layers",
}


@pytest.mark.parametrize("name", sorted(_A8_OWNERS))
def test_a8_name_is_in_package_all(name) -> None:
    pkg = importlib.import_module("Services.layer_render")
    assert name in pkg.__all__


@pytest.mark.parametrize("name", sorted(_A8_OWNERS))
def test_a8_package_name_is_the_object_of_its_module(name) -> None:
    pkg = importlib.import_module("Services.layer_render")
    owner = importlib.import_module(_A8_OWNERS[name])
    assert getattr(pkg, name) is getattr(owner, name)


def test_a8_package_all_has_no_private_names() -> None:
    pkg = importlib.import_module("Services.layer_render")
    assert [n for n in pkg.__all__ if n.startswith("_")] == []


def test_a8_package_all_has_no_duplicates() -> None:
    pkg = importlib.import_module("Services.layer_render")
    dups = sorted({n for n in pkg.__all__ if pkg.__all__.count(n) > 1})
    assert dups == []


def test_a8_every_name_in_package_all_resolves() -> None:
    pkg = importlib.import_module("Services.layer_render")
    assert [n for n in pkg.__all__ if not hasattr(pkg, n)] == []


def test_a8_package_all_kept_the_names_it_had_before() -> None:
    """Страховка от потери прежних имён при правке `__all__` (литерал — состав до 2.4b)."""
    pkg = importlib.import_module("Services.layer_render")
    before = {
        "AUGMENT_FIELDS",
        "CLASS_SPRITE_SOURCE",
        "CatalogConfig",
        "ClassEntry",
        "ClassMeta",
        "ComposedLayers",
        "EFFECTS",
        "EFFECT_PARAMS",
        "EffectSpec",
        "LayerAugment",
        "LayerMode",
        "LayerSpec",
        "RangeF",
        "ScrollingTile",
        "ScenePreset",
        "SolidFill",
        "SpriteCatalog",
        "SpriteSource",
        "SymmetryType",
        "apply_effects",
        "background_layers_from_config",
        "canvas_size",
        "cast_contact_shadow",
        "compose_layers",
        "composite",
        "crop_to_alpha",
        "fit_longest_side",
        "fold_background",
        "imread_unicode",
        "imwrite_unicode",
        "load_layer_sprite",
        "load_meta",
        "procedural_background",
        "render_background",
        "resize_square",
        "rotate_expand",
        "side_from_radius",
        "square_crop",
        "transform_layer",
        "write_meta",
    }
    assert sorted(before - set(pkg.__all__)) == []
