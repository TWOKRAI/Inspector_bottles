# -*- coding: utf-8 -*-
"""Слепые acceptance-тесты Task 2.1 `layer-render`: compose/io переезжают в `Services/layer_render`.

Источник контракта: `plans/layer-render/phase-2-core.md`, Task 2.1 (DESIGN + Acceptance A1-A6; A7/A8 - у лида).
Написаны ДО реализации: `Services.layer_render.compose` / `.io` в этом дереве нет по конструкции
(worktree на коммите fdfb5c1e, «только планы»), поэтому всё, что их трогает, падает с ModuleNotFoundError.

A5 - главный. Литералы sha256 в `_EXPECTED_DIGESTS` СНЯТЫ ОДИН РАЗ на коде ДО переезда
(`Services.dataset_gen.core.compose` на коммите fdfb5c1e) скриптом из отчёта
`docs/reviews/2026-10-01_task-2.1-tester.md` и вставлены сюда буквами. Они НЕ вычисляются из тестируемого
кода: тест вызывает `Services.layer_render.compose`, а ожидание берёт из литерала. Хэш = sha256 от
`"<shape>|<dtype>|" + bytes(массив)`, т.е. форма входит в хэш.

Входы строятся арифметикой по индексам, а не `np.random`: поток ГСЧ numpy не гарантирован между версиями,
а литералы обязаны пережить обновление numpy. Формула асимметрична по x/y/каналу (перепутанные оси или
каналы меняют хэш).

Импорты нового пакета - внутри хелперов, а не в шапке: пока модулей нет, КАЖДЫЙ тест падает сам
(ModuleNotFoundError), а не одной ошибкой сбора на весь файл.
"""

from __future__ import annotations

import ast
import hashlib
import importlib
import os
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

# Services/layer_render/tests/<файл>: parents[1] == Services/layer_render, parents[3] == корень репо
_PKG_DIR = Path(__file__).resolve().parents[1]
_REPO_ROOT = Path(__file__).resolve().parents[3]
_OLD_COMPOSE_FILE = _REPO_ROOT / "Services" / "dataset_gen" / "core" / "compose.py"

_NEW_COMPOSE = "Services.layer_render.compose"
_NEW_IO = "Services.layer_render.io"
_OLD_COMPOSE = "Services.dataset_gen.core.compose"
_OLD_CATALOG = "Services.dataset_gen.core.catalog"

_COMPOSE_NAMES = ("composite", "rotate_expand", "crop_to_alpha", "fit_longest_side", "cast_contact_shadow")
_IO_NAMES = ("imread_unicode", "imwrite_unicode")

_FORBIDDEN_PREFIXES = ("Services.dataset_gen", "Services.line_sim", "Services.ml_train")


def _compose():
    return importlib.import_module(_NEW_COMPOSE)


def _io():
    return importlib.import_module(_NEW_IO)


# --------------------------------------------------------------------------- #
# A1. Идентичность старого и нового местоположения, __module__ определения
# --------------------------------------------------------------------------- #

_A1_PAIRS = [(_OLD_COMPOSE, _NEW_COMPOSE, n) for n in _COMPOSE_NAMES] + [(_OLD_CATALOG, _NEW_IO, n) for n in _IO_NAMES]


@pytest.mark.parametrize("old_mod,new_mod,name", _A1_PAIRS, ids=[p[2] for p in _A1_PAIRS])
def test_a1_old_location_is_the_same_object(old_mod, new_mod, name):
    """Старое место отдаёт ТОТ ЖЕ объект, что и новое (реэкспорт, а не копия)."""
    new = getattr(importlib.import_module(new_mod), name)
    old = getattr(importlib.import_module(old_mod), name)
    assert old is new


@pytest.mark.parametrize("old_mod,new_mod,name", _A1_PAIRS, ids=[p[2] for p in _A1_PAIRS])
def test_a1_defined_in_new_module(old_mod, new_mod, name):
    """Функция ОПРЕДЕЛЕНА в новом модуле (а не просто видна из него)."""
    new = getattr(importlib.import_module(new_mod), name)
    assert new.__module__ == new_mod


# --------------------------------------------------------------------------- #
# A2. В старом compose.py нет def/class - только реэкспорт
# --------------------------------------------------------------------------- #


def test_a2_old_compose_has_no_definitions():
    """AST: ни `def`, ни `async def`, ни `class` на любой глубине вложенности."""
    tree = ast.parse(_OLD_COMPOSE_FILE.read_text(encoding="utf-8"))
    defs = [
        f"{type(n).__name__} {n.name} (строка {n.lineno})"
        for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    ]
    assert defs == []


# --------------------------------------------------------------------------- #
# A3. layer_render не зависит от dataset_gen / line_sim / ml_train
# --------------------------------------------------------------------------- #


def _is_forbidden(dotted: str) -> bool:
    return any(dotted == p or dotted.startswith(p + ".") for p in _FORBIDDEN_PREFIXES)


def _forbidden_imports(source: str, module_dotted: str, is_package: bool = False) -> list[str]:
    """Запрещённые импорты в исходнике: `import x[.y]`, `from x import y`, `from . import`, `import_module("x")`.

    `module_dotted` - имя самого модуля (нужно, чтобы раскрыть относительные импорты).
    Форма `from Services import dataset_gen` ловится: проверяется и `module`, и `module.alias`.
    """
    pkg_parts = module_dotted.split(".") if is_package else module_dotted.split(".")[:-1]
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found += [a.name for a in node.names if _is_forbidden(a.name)]
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = pkg_parts[: len(pkg_parts) - (node.level - 1)]
                module = ".".join(base + ([node.module] if node.module else []))
            else:
                module = node.module or ""
            if _is_forbidden(module):
                found.append(module)
            found += [f"{module}.{a.name}" for a in node.names if _is_forbidden(f"{module}.{a.name}")]
        elif isinstance(node, ast.Call):
            fn = node.func
            name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
            if name in ("import_module", "__import__") and node.args:
                a0 = node.args[0]
                if isinstance(a0, ast.Constant) and isinstance(a0.value, str) and _is_forbidden(a0.value):
                    found.append(a0.value)
    return found


def _layer_render_sources() -> list[tuple[str, Path]]:
    """(dotted-имя, путь) каждого не-тестового `.py` под Services/layer_render."""
    out = []
    for p in sorted(_PKG_DIR.rglob("*.py")):
        rel = p.relative_to(_PKG_DIR)
        if "tests" in rel.parts:
            continue
        parts = ["Services", "layer_render", *rel.with_suffix("").parts]
        out.append((".".join(parts), p))
    return out


@pytest.mark.parametrize(
    "source",
    [
        "import Services.dataset_gen",
        "import Services.dataset_gen.core.compose as c",
        "import Services.line_sim.core",
        "from Services.ml_train import x",
        "from Services.dataset_gen.core.compose import composite",
        "from Services import line_sim",
        "from ..dataset_gen.core import compose",
        "from .. import ml_train",
        "import importlib\nimportlib.import_module('Services.dataset_gen.core.compose')",
        "__import__('Services.line_sim')",
    ],
)
def test_a3_detector_catches_every_import_form(source):
    """Самопроверка детектора: без неё «ничего не найдено» могло бы значить «искал не то»."""
    assert _forbidden_imports(source, "Services.layer_render.compose") != []


@pytest.mark.parametrize(
    "source",
    [
        "import numpy as np\nimport cv2",
        "from Services.layer_render.interfaces import SolidFill",
        "from .interfaces import SolidFill",
        "from Services import layer_render",
        "x = 'Services.dataset_gen mentioned in a string'",
        "import Services.dataset_gen_helpers_but_not_really_it",
    ],
)
def test_a3_detector_ignores_clean_sources(source):
    """Детектор не срабатывает на чистое (в т.ч. на упоминание в строке и на префикс-омоним)."""
    assert _forbidden_imports(source, "Services.layer_render.compose") == []


def test_a3_layer_render_never_imports_consumers():
    """AST по всем не-тестовым `.py` Services/layer_render: ни одного запрещённого импорта."""
    sources = _layer_render_sources()
    # якорь: скан реально что-то видит (пустая выборка дала бы вакуозный «зелёный»)
    assert {"background.py", "interfaces.py", "__init__.py"} <= {p.name for _, p in sources}
    offenders = {}
    for dotted, path in sources:
        hits = _forbidden_imports(path.read_text(encoding="utf-8"), dotted, is_package=path.name == "__init__.py")
        if hits:
            offenders[str(path.relative_to(_PKG_DIR))] = hits
    assert offenders == {}


def test_a3_importing_new_modules_does_not_pull_consumers():
    """Импорт `layer_render.compose` и `.io` в чистом интерпретаторе не тянет dataset_gen/line_sim/ml_train."""
    code = (
        "import sys, json\n"
        f"import {_NEW_COMPOSE}, {_NEW_IO}\n"
        f"prefixes = {list(_FORBIDDEN_PREFIXES)!r}\n"
        "bad = sorted(m for m in sys.modules if any(m == p or m.startswith(p + '.') for p in prefixes))\n"
        "print(json.dumps(bad))\n"
    )
    env = {**os.environ, "PYTHONPATH": str(_REPO_ROOT)}
    r = subprocess.run(
        [sys.executable, "-c", code], cwd=str(_REPO_ROOT), env=env, capture_output=True, text=True, timeout=150
    )
    assert r.returncode == 0, r.stderr[-600:]
    assert r.stdout.strip().splitlines()[-1] == "[]"


# --------------------------------------------------------------------------- #
# A4. imwrite_unicode -> imread_unicode на не-ASCII пути
# --------------------------------------------------------------------------- #


def _ramp(h: int, w: int, c: int, salt: int) -> np.ndarray:
    i = np.arange(h, dtype=np.int64)[:, None, None]
    j = np.arange(w, dtype=np.int64)[None, :, None]
    k = np.arange(c, dtype=np.int64)[None, None, :]
    return ((i * 37 + j * 91 + k * 53 + i * j * 5 + salt * 29) % 256).astype(np.uint8)


def _sprite_rgba(h: int, w: int, salt: int = 1) -> np.ndarray:
    """RGBA-спрайт: асимметричный цвет, частично прозрачная альфа (0..255), нулевая рамка 1 px."""
    rgb = _ramp(h, w, 3, salt)
    i = np.arange(h, dtype=np.int64)[:, None]
    j = np.arange(w, dtype=np.int64)[None, :]
    alpha = ((i * 11 + j * 17 + salt * 7) % 256).astype(np.uint8)
    alpha[0, :] = alpha[-1, :] = 0
    alpha[:, 0] = alpha[:, -1] = 0
    return np.dstack([rgb, alpha])


def _cyr_path(tmp_path: Path, name: str) -> Path:
    d = tmp_path / "папка_Ёж_данные"
    d.mkdir()
    return d / name


def test_a4_bgr_round_trip_on_cyrillic_path(tmp_path):
    img = _ramp(17, 23, 3, salt=3)
    p = _cyr_path(tmp_path, "изображение_Ж.png")
    _io().imwrite_unicode(p, img)
    assert p.is_file()
    back = _io().imread_unicode(p)
    assert back.shape == (17, 23, 3) and back.dtype == np.uint8
    assert np.array_equal(back, img)


def test_a4_bgra_round_trip_keeps_alpha_by_default(tmp_path):
    """Флаг по умолчанию (IMREAD_UNCHANGED) сохраняет 4-й канал; байты те же."""
    img = _sprite_rgba(17, 23, salt=5)
    assert img[:, :, 3].min() == 0 and img[:, :, 3].max() > 200  # вход действительно с полупрозрачностью
    p = _cyr_path(tmp_path, "спрайт_ЪЫ.png")
    _io().imwrite_unicode(p, img)
    back = _io().imread_unicode(p)
    assert back.shape == (17, 23, 4)
    assert np.array_equal(back[:, :, 3], img[:, :, 3])
    assert np.array_equal(back[:, :, :3][img[:, :, 3] > 0], img[:, :, :3][img[:, :, 3] > 0])


def test_a4_explicit_flag_is_honoured(tmp_path):
    """Явный флаг передаётся в cv2: GRAYSCALE даёт 2-мерный массив."""
    p = _cyr_path(tmp_path, "серое_Ё.png")
    _io().imwrite_unicode(p, _ramp(9, 11, 3, salt=2))
    assert _io().imread_unicode(p, cv2.IMREAD_GRAYSCALE).shape == (9, 11)


def test_a4_path_without_suffix_is_written_as_png(tmp_path):
    """Нет суффикса -> формат png (пишется под тем же именем, читается по содержимому)."""
    img = _ramp(8, 8, 3, salt=4)
    p = _cyr_path(tmp_path, "без_расширения")
    _io().imwrite_unicode(p, img)
    assert p.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    assert np.array_equal(_io().imread_unicode(p), img)


def test_a4_unreadable_file_raises_value_error(tmp_path):
    p = _cyr_path(tmp_path, "мусор.png")
    p.write_bytes(b"this is not an image at all")
    with pytest.raises(ValueError):
        _io().imread_unicode(p)


# --------------------------------------------------------------------------- #
# A5. Поведение compose не изменилось: sha256-литералы с кода ДО переезда
# --------------------------------------------------------------------------- #


def _digest(a: np.ndarray) -> str:
    return hashlib.sha256(f"{a.shape}|{a.dtype}|".encode() + np.ascontiguousarray(a).tobytes()).hexdigest()


def _bg() -> np.ndarray:
    return _ramp(48, 64, 3, salt=9)


def _spr() -> np.ndarray:
    return _sprite_rgba(20, 16, salt=2)  # h=20, w=16, частичная альфа + нулевая рамка


def _crop_input_box() -> np.ndarray:
    """30x40 RGBA; альфа > 0 только в боксе строки 5..21, столбцы 8..30 (частичная, есть дырка альфа=0 внутри)."""
    s = _ramp(30, 40, 4, salt=6)
    s[:, :, 3] = 0
    i = np.arange(30, dtype=np.int64)[:, None]
    j = np.arange(40, dtype=np.int64)[None, :]
    inner = (((i * 11 + j * 17) % 255) + 1).astype(np.uint8)  # 1..255, без нулей
    s[5:22, 8:31, 3] = inner[5:22, 8:31]
    s[12:15, 15:19, 3] = 0  # дырка внутри бокса: bbox не должен сжаться
    return s


def _crop_input_alpha1() -> np.ndarray:
    """Альфа = 1 (минимально возможная) всего в двух пикселях: порог — именно `> 0`, а не 128."""
    s = _ramp(12, 16, 4, salt=8)
    s[:, :, 3] = 0
    s[4, 9, 3] = 1
    s[7, 2, 3] = 1
    return s


# имя случая -> функция(compose_module) -> ndarray. Один и тот же код гоняет и capture-скрипт на старом
# модуле (получение литералов), и тест на новом (сверка).
_CASES = {
    # --- rotate_expand: угол не кратен 90, отрицательный, 90 (float-хвост ceil), 0, прозрачные края ---
    "rotate_37_5": lambda m: m.rotate_expand(_sprite_rgba(20, 30, salt=1), 37.5),
    "rotate_neg_23": lambda m: m.rotate_expand(_sprite_rgba(20, 30, salt=1), -23.0),
    "rotate_90": lambda m: m.rotate_expand(_sprite_rgba(20, 30, salt=1), 90.0),
    "rotate_0": lambda m: m.rotate_expand(_sprite_rgba(20, 30, salt=1), 0.0),
    "rotate_square_45": lambda m: m.rotate_expand(_sprite_rgba(25, 25, salt=4), 45.0),
    # --- crop_to_alpha ---
    "crop_box_partial_alpha": lambda m: m.crop_to_alpha(_crop_input_box()),
    "crop_alpha_1_pixels": lambda m: m.crop_to_alpha(_crop_input_alpha1()),
    # --- fit_longest_side: вниз (INTER_AREA), вверх (INTER_LINEAR), 1 px клэмп, scale==1.0 ---
    "fit_down_area": lambda m: m.fit_longest_side(_sprite_rgba(30, 20, salt=3), 12),
    "fit_up_linear": lambda m: m.fit_longest_side(_sprite_rgba(9, 14, salt=3), 40),
    "fit_extreme_aspect": lambda m: m.fit_longest_side(_sprite_rgba(1, 100, salt=3), 10),
    "fit_same_scale_1": lambda m: m.fit_longest_side(_sprite_rgba(18, 11, salt=3), 18),
    # --- composite: середина, за правым/верхним краем, за левым/нижним, banker's rounding, целиком за кадром ---
    "composite_center": lambda m: m.composite(_bg(), _spr(), (32.0, 24.0)),
    "composite_over_right_top": lambda m: m.composite(_bg(), _spr(), (60.4, 3.2)),
    "composite_over_left_bottom": lambda m: m.composite(_bg(), _spr(), (-2.6, 45.5)),
    "composite_half_x_even": lambda m: m.composite(_bg(), _spr(), (24.5, 24.0)),  # 24.5-8=16.5 -> 16
    "composite_half_x_odd": lambda m: m.composite(_bg(), _spr(), (25.5, 24.0)),  # 25.5-8=17.5 -> 18
    "composite_fully_outside": lambda m: m.composite(_bg(), _spr(), (200.0, 24.0)),
    # --- cast_contact_shadow ---
    "shadow_basic": lambda m: m.cast_contact_shadow(_bg(), _spr(), (32.0, 24.0), 0.6, 5, (3, 2)),
    "shadow_blur_even_4": lambda m: m.cast_contact_shadow(_bg(), _spr(), (32.0, 24.0), 0.6, 4, (3, 2)),
    "shadow_no_blur": lambda m: m.cast_contact_shadow(_bg(), _spr(), (32.0, 24.0), 0.6, 0, (3, 2)),
    "shadow_over_border": lambda m: m.cast_contact_shadow(_bg(), _spr(), (62.0, 2.0), 0.8, 7, (-4, 5)),
    "shadow_opacity_1_neg_offset": lambda m: m.cast_contact_shadow(_bg(), _spr(), (20.0, 30.0), 1.0, 3, (-2, -3)),
    "shadow_fully_outside": lambda m: m.cast_contact_shadow(_bg(), _spr(), (300.0, 24.0), 0.6, 5, (3, 2)),
}

# Снято скриптом на коде ДО переезда (Services.dataset_gen.core.compose @ fdfb5c1e). Не пересчитывать
# из тестируемого кода: изменение значения = изменение поведения compose.
_EXPECTED_DIGESTS = {
    "composite_center": "dbf77572a5510c1968feaaf304110a8536a4cdfdb7d95d569f9debedffa690f9",
    "composite_fully_outside": "dc4ee013a786d3c007254866fbbc33fd508d64ebe3a533c5960738e1bd75de2e",
    "composite_half_x_even": "c564812e1d69bee7afc3a058a11df2843c6e96139723a62099b1f3773566d750",
    "composite_half_x_odd": "70a25bedef73a9f0698c9c7f4712cbee6587dfcd0a45a2e1f117f72245e8ce0e",
    "composite_over_left_bottom": "3199fb9c8ce90773f0733e1ff4d8174d697dc50fb12979147d96b4a4c1026922",
    "composite_over_right_top": "1d908b1da9ce6893ef204a1725cbff7e4344b9bbbb31513fa978764c913fe983",
    "crop_alpha_1_pixels": "1268b28912458fd3b3e6f651c94f5aef4cd2c1bc56d5ad2bbe3b668dd6580df0",
    "crop_box_partial_alpha": "8ee47018adcbb57a053cdb1ea894f5ce02037d3a6dddf1cac6ffbd1f9e38816d",
    "fit_down_area": "fbf424cfd749beeb9206973bd25ba8e5f2f25494cb4e47752b81032f45e5f230",
    "fit_extreme_aspect": "4733ac1a024b321f67d381ce836de927157744dc13030ba8feee3df1765a736c",
    "fit_same_scale_1": "305fa1594783daac3cfe6b7f5658c1dbaef4ecdf6431be1512e5d27815a0858e",
    "fit_up_linear": "e22c9a305deb62758272103fb1a0423e56760f04e7ef4d99e6dd0b23b7b3463e",
    "rotate_0": "1a22be3504027d30bd3d923643527cb6e0301cd9ebfe94edd0fcd15d55150c97",
    "rotate_37_5": "30f13b691afdbbf53b146c4b37e6fac919688b6e4d2a18022273f61bd093354b",
    "rotate_90": "273c54c008a170eaeeec9902229c5b282f622f3f9bad82d29d98139a7b2e7e3d",
    "rotate_neg_23": "ec6b13b1c201e1b77b17b792e26ea2e835172e8b0c2823bdf2b9216ecc4ee0fd",
    "rotate_square_45": "c5a3fbaa00ee59d37f7bcd597578a87c33c781ab9e04955d92541620c0547efe",
    "shadow_basic": "d83d9f2c7bc0959ee371ccdde2e11d2183967a0c05bf7e058edc80095f6974fc",
    "shadow_blur_even_4": "d83d9f2c7bc0959ee371ccdde2e11d2183967a0c05bf7e058edc80095f6974fc",
    "shadow_fully_outside": "dc4ee013a786d3c007254866fbbc33fd508d64ebe3a533c5960738e1bd75de2e",
    "shadow_no_blur": "3844c706094c47e3114426120abbc7088eedfa29f81a165b9f97abdbf01a4f46",
    "shadow_opacity_1_neg_offset": "68d755caed5530c53d82c9c99459e0249564a7f75bec4761d7ab034ba8c905cd",
    "shadow_over_border": "131609ed68ea85075895e2003a78238b4fa77b7d716e190106289ecfc08d7f87",
}


@pytest.mark.parametrize("case", sorted(_CASES))
def test_a5_behaviour_pin(case):
    """Результат `layer_render.compose` побайтно равен литералу, снятому на коде до переезда."""
    assert _digest(_CASES[case](_compose())) == _EXPECTED_DIGESTS[case]


def test_a5_every_case_has_a_literal():
    """Словарь литералов покрывает все случаи (нельзя тихо добавить случай без пина)."""
    assert set(_CASES) == set(_EXPECTED_DIGESTS)


# --- те же свойства, но руками посчитанные формы (диагностика: хэш говорит «изменилось», это - «где») ---


@pytest.mark.parametrize("angle,expected_hw", [(37.5, (35, 36)), (-23.0, (31, 36))])
def test_a5_rotate_expand_canvas_size_hand_computed(angle, expected_hw):
    """Холст 20x30 (h x w): ceil(h*|sin|+w*|cos|) x ceil(h*|cos|+w*|sin|), посчитано руками."""
    out = _compose().rotate_expand(_sprite_rgba(20, 30, salt=1), angle)
    assert out.shape == (*expected_hw, 4) and out.dtype == np.uint8


@pytest.mark.parametrize(
    "h,w,target,expected_hw",
    [(30, 20, 12, (12, 8)), (9, 14, 40, (26, 40)), (1, 100, 10, (1, 10)), (18, 11, 18, (18, 11))],
)
def test_a5_fit_longest_side_shape_hand_computed(h, w, target, expected_hw):
    out = _compose().fit_longest_side(_sprite_rgba(h, w), target)
    assert out.shape[:2] == expected_hw


def test_a5_crop_to_alpha_bbox_hand_computed():
    """Бокс альфы строки 5..21, столбцы 8..30 -> 17x23; дырка внутри бокса bbox не сжимает."""
    out = _compose().crop_to_alpha(_crop_input_box())
    assert out.shape == (17, 23, 4)
    assert out[0, :, 3].max() > 0 and out[-1, :, 3].max() > 0
    assert out[:, 0, 3].max() > 0 and out[:, -1, 3].max() > 0


def test_a5_crop_to_alpha_threshold_is_strictly_above_zero():
    """Два пикселя с alpha=1 в (4,9) и (7,2): bbox строки 4..7, столбцы 2..9 -> 4x8."""
    out = _compose().crop_to_alpha(_crop_input_alpha1())
    assert out.shape == (4, 8, 4)


def test_a5_crop_to_alpha_fully_transparent_raises():
    s = _ramp(6, 6, 4, salt=1)
    s[:, :, 3] = 0
    with pytest.raises(ValueError):
        _compose().crop_to_alpha(s)


# --- постусловия composite/cast_contact_shadow: фон не мутируется, результат - новый объект ---


@pytest.mark.parametrize("center", [(32.0, 24.0), (60.4, 3.2), (200.0, 24.0)], ids=["inside", "border", "outside"])
def test_a5_composite_returns_copy_and_leaves_background_intact(center):
    bg = _bg()
    snapshot = bg.copy()
    out = _compose().composite(bg, _spr(), center)
    assert out is not bg and not np.shares_memory(out, bg)
    assert np.array_equal(bg, snapshot)


@pytest.mark.parametrize("center", [(32.0, 24.0), (62.0, 2.0), (300.0, 24.0)], ids=["inside", "border", "outside"])
def test_a5_shadow_returns_copy_leaves_background_and_only_darkens(center):
    bg = _bg()
    snapshot = bg.copy()
    out = _compose().cast_contact_shadow(bg, _spr(), center, 0.6, 5, (3, 2))
    assert out is not bg and not np.shares_memory(out, bg)
    assert np.array_equal(bg, snapshot)
    assert out.shape == bg.shape and (out <= bg).all()


def test_a5_shadow_fully_outside_is_exact_background():
    """Тень целиком за кадром - в точности фон (ветка раннего возврата)."""
    out = _compose().cast_contact_shadow(_bg(), _spr(), (300.0, 24.0), 0.6, 5, (3, 2))
    assert np.array_equal(out, _bg())


def test_a5_composite_outside_zone_pixels_equal_background():
    """Пост-условие: вне зоны спрайта пиксели равны фону (спрайт 20x16 в центре (32,24) -> x 24..39, y 14..33)."""
    out = _compose().composite(_bg(), _spr(), (32.0, 24.0))
    mask = np.ones(out.shape[:2], dtype=bool)
    mask[14:34, 24:40] = False
    assert np.array_equal(out[mask], _bg()[mask])
    assert not np.array_equal(out[14:34, 24:40], _bg()[14:34, 24:40])
