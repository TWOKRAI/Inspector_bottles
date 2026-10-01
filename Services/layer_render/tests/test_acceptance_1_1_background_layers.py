# -*- coding: utf-8 -*-
"""Слепые acceptance-тесты Task 1.1 `layer-render` (пакет `Services/layer_render`, ядро стека фона).

Источник контракта: `plans/layer-render/phase-1.md`, Task 1.1 (DESIGN + Acceptance) и рамка
`plans/layer-render/plan.md`. Написаны ДО реализации: пакета `Services/layer_render` в этом дереве нет
по конструкции (worktree на коммите «только план»).

ЗАПРЕЩЁННЫЕ ПУТИ (не читались): `.claude/worktrees/layer-render`, любые другие ветки/worktree, реализация
Task 1.1 и тесты автора. Прочитано как готовая зависимость: `scene_compositor.py`, `plugin.py` сцены,
существующие тесты 3.6 (паттерны фикстур).

Сигнатуры, взятые из плана буквально: `Services.layer_render.interfaces.SolidFill(color_rgb)`,
`ScrollingTile(image)` (frozen dataclass), `Services.layer_render.background.background_layers_from_config(
items, load_image)`. Сигнатура `render_background` в плане не задана — напрямую НЕ тестируется (её эффект
виден через компоновщик, см. `Services/line_sim/tests/test_acceptance_1_1_background_layers_compositor.py`).

Импорты нового пакета — внутри хелперов, а не в шапке: пока пакета нет, КАЖДЫЙ тест падает сам
(ModuleNotFoundError), а не одной ошибкой сбора на весь файл.
"""

from __future__ import annotations

import ast
import dataclasses
import importlib
import re
from pathlib import Path

import numpy as np
import pytest

# Services/layer_render/tests/<файл> -> parents[1] == Services/layer_render
_PKG_DIR = Path(__file__).resolve().parents[1]


def _interfaces():
    return importlib.import_module("Services.layer_render.interfaces")


def _from_config_fn():
    return importlib.import_module("Services.layer_render.background").background_layers_from_config


# --------------------------------------------------------------------------------------
# Типы слоёв: frozen dataclass
# --------------------------------------------------------------------------------------


def test_solid_fill_is_frozen_dataclass_keeping_color_rgb():
    iface = _interfaces()
    layer = iface.SolidFill(color_rgb=(10, 20, 30))
    assert dataclasses.is_dataclass(layer)
    assert tuple(layer.color_rgb) == (10, 20, 30)
    with pytest.raises(dataclasses.FrozenInstanceError):
        layer.color_rgb = (1, 2, 3)  # type: ignore[misc]


def test_scrolling_tile_is_frozen_dataclass_keeping_image():
    iface = _interfaces()
    image = np.zeros((3, 5, 4), dtype=np.uint8)
    image[1, 2] = (9, 8, 7, 6)
    layer = iface.ScrollingTile(image=image)
    assert dataclasses.is_dataclass(layer)
    assert layer.image.shape == (3, 5, 4)
    assert tuple(int(v) for v in layer.image[1, 2]) == (9, 8, 7, 6)
    with pytest.raises(dataclasses.FrozenInstanceError):
        layer.image = image  # type: ignore[misc]


# --------------------------------------------------------------------------------------
# background_layers_from_config: разбор схемы YAML (принимаемые формы)
# --------------------------------------------------------------------------------------


def test_from_config_returns_layers_bottom_to_top_in_config_order():
    """solid -> SolidFill с RGB как в конфиге (не BGR), tile -> ScrollingTile с картинкой из load_image."""
    iface = _interfaces()
    from_config = _from_config_fn()
    tile = np.zeros((4, 6, 3), dtype=np.uint8)
    tile[0, 0] = (7, 8, 9)

    layers = list(
        from_config([{"solid": [10, 20, 30]}, {"tile": "some/tile.png"}, {"solid": [1, 2, 3]}], lambda p: tile)
    )

    assert len(layers) == 3
    assert isinstance(layers[0], iface.SolidFill)
    assert tuple(layers[0].color_rgb) == (10, 20, 30)
    assert isinstance(layers[1], iface.ScrollingTile)
    assert layers[1].image.shape == (4, 6, 3)
    assert tuple(int(v) for v in layers[1].image[0, 0]) == (7, 8, 9)
    assert isinstance(layers[2], iface.SolidFill)
    assert tuple(layers[2].color_rgb) == (1, 2, 3)


def test_from_config_passes_the_tile_value_from_config_to_load_image():
    from_config = _from_config_fn()
    seen: list = []

    def load_image(path):
        seen.append(path)
        return np.zeros((2, 2, 3), dtype=np.uint8)

    from_config([{"tile": "data/line_sim/belt_tile.png"}], load_image)
    assert seen == ["data/line_sim/belt_tile.png"]


@pytest.mark.parametrize("color", [[0, 0, 0], [255, 255, 255], [0, 255, 0]], ids=["black", "white", "mixed"])
def test_from_config_accepts_color_boundaries_0_and_255(color):
    from_config = _from_config_fn()
    layers = list(from_config([{"solid": color}], lambda p: None))
    assert len(layers) == 1
    assert tuple(layers[0].color_rgb) == tuple(color)


# --------------------------------------------------------------------------------------
# background_layers_from_config: ValueError на каждую форму кривой схемы, с индексом элемента
# --------------------------------------------------------------------------------------

# Индекс плохого элемента — 4; в валидных соседях и в плохих значениях цифры «4» нет, поэтому
# «4» в тексте ошибки может прийти только из индекса (иначе проверка индекса была бы пустой).
_OK_PREFIX = [{"solid": [0, 0, 0]}, {"tile": "a.png"}, {"solid": [11, 17, 19]}, {"tile": "b.png"}]

# (плохой элемент, маркеры значения, которые обязаны попасть в текст)
_BAD_ITEMS = [
    pytest.param({}, [], id="empty_dict"),
    pytest.param({"solid": [0, 0, 0], "tile": "c.png"}, ["solid", "tile"], id="two_keys"),
    pytest.param({"zq_fill": [0, 0, 0]}, ["zq_fill"], id="unknown_key"),
    pytest.param({"solid": [11, 17]}, ["11", "17"], id="color_len_2"),
    pytest.param({"solid": [11, 17, 19, 26]}, ["26"], id="color_len_4"),
    pytest.param({"solid": [0, 0, 999]}, ["999"], id="color_above_255"),
    pytest.param({"solid": [0, 0, -7]}, ["-7"], id="color_negative"),
    pytest.param({"solid": [0.5, 0, 7]}, ["0.5"], id="color_float"),
    pytest.param({"solid": ["qq", 0, 7]}, ["qq"], id="color_str"),
    pytest.param("solid", ["solid"], id="item_not_a_dict"),
]


@pytest.mark.parametrize(("bad", "markers"), _BAD_ITEMS)
def test_from_config_bad_item_raises_valueerror_naming_index_and_value(bad, markers):
    from_config = _from_config_fn()
    items = [*_OK_PREFIX, bad]
    with pytest.raises(ValueError) as info:
        from_config(items, lambda p: np.zeros((2, 2, 3), dtype=np.uint8))
    text = str(info.value)
    assert "4" in text, f"текст ошибки не называет индекс элемента 4: {text!r}"
    for marker in markers:
        assert marker in text, f"текст ошибки не называет значение ({marker!r}): {text!r}"


def test_from_config_empty_list_raises_valueerror():
    from_config = _from_config_fn()
    with pytest.raises(ValueError):
        from_config([], lambda p: None)


@pytest.mark.parametrize("bad_color", [[0, 0, 256], [0, 0, -1]], ids=["256", "minus_1"])
def test_from_config_color_just_outside_range_raises(bad_color):
    """Граница с обеих сторон: 255/0 принимаются (тест выше), 256/-1 — нет."""
    from_config = _from_config_fn()
    with pytest.raises(ValueError):
        from_config([{"solid": bad_color}], lambda p: None)


# --------------------------------------------------------------------------------------
# Слой: layer_render не импортирует line_sim / dataset_gen / ml_train (AST)
# --------------------------------------------------------------------------------------

_FORBIDDEN_SERVICES = ("line_sim", "dataset_gen", "ml_train")
# Выше слоя по правилу слоёв проекта (CLAUDE.md, п. 9): Services не знает про Plugins/prototype.
_FORBIDDEN_ABOVE = ("Plugins", "multiprocess_prototype")


def _forbidden_imports(source: str, services: tuple[str, ...], tops: tuple[str, ...] = ()) -> list[str]:
    """Имена запрещённых модулей, импортируемых исходником `source` (разбор AST, не подстрока)."""
    hits: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            names = [base] + [f"{base}.{alias.name}" for alias in node.names]
        else:
            continue
        for name in names:
            parts = name.split(".")
            if parts[0] == "Services" and len(parts) > 1 and parts[1] in services:
                hits.append(name)
            elif parts[0] in tops:
                hits.append(name)
    return hits


def test_ast_detector_catches_all_import_forms():
    """Контроль самого детектора (зелёный и сегодня): без него «0 нарушений» — пустое утверждение."""
    for source in (
        "import Services.line_sim",
        "from Services.line_sim.core import x",
        "from Services import dataset_gen",
        "import Services.ml_train.core as m",
        "from Plugins.sim import scene_source",
    ):
        assert _forbidden_imports(source, _FORBIDDEN_SERVICES, _FORBIDDEN_ABOVE), source
    # Упоминание в строке/докстринге — не импорт.
    assert not _forbidden_imports(
        '"""from Services.line_sim import x"""\nx = "import Services.dataset_gen"', _FORBIDDEN_SERVICES
    )


def _package_sources() -> list[Path]:
    return sorted(p for p in _PKG_DIR.rglob("*.py") if "tests" not in p.relative_to(_PKG_DIR).parts)


def test_package_source_files_exist_for_the_import_check_to_mean_something():
    names = {p.name for p in _package_sources()}
    assert {"__init__.py", "interfaces.py", "background.py"} <= names, sorted(names)


def test_layer_render_does_not_import_line_sim_dataset_gen_ml_train():
    sources = _package_sources()
    assert sources, "в Services/layer_render нет исходников — проверять нечего"
    bad = {
        p.name: hits
        for p in sources
        if (hits := _forbidden_imports(p.read_text(encoding="utf-8"), _FORBIDDEN_SERVICES))
    }
    assert not bad, bad


def test_layer_render_does_not_import_plugins_or_prototype():
    sources = _package_sources()
    assert sources, "в Services/layer_render нет исходников — проверять нечего"
    bad = {
        p.name: hits
        for p in sources
        if (hits := _forbidden_imports(p.read_text(encoding="utf-8"), (), _FORBIDDEN_ABOVE))
    }
    assert not bad, bad


# --------------------------------------------------------------------------------------
# Рамка плана: в коде механизма нет ничего продуктового
# --------------------------------------------------------------------------------------


def test_frame_rule_grep_zero_matches_in_package_python_sources():
    """plan.md «Рамка плана»: `grep -inE "letter|букв|disk|диск"` по файлам механизма — 0 совпадений
    (README с примерами проверяется вручную лидом; здесь — только *.py)."""
    sources = _package_sources()
    assert sources, "в Services/layer_render нет исходников — проверять нечего"
    pattern = re.compile(r"letter|букв|disk|диск", re.IGNORECASE)
    hits = {p.name: [ln for ln in p.read_text(encoding="utf-8").splitlines() if pattern.search(ln)] for p in sources}
    hits = {name: lines for name, lines in hits.items() if lines}
    assert not hits, hits
