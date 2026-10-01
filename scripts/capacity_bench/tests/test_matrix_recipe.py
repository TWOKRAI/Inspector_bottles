"""Слепые acceptance-тесты 4.8a: `matrix.cases` и `recipe.render_recipe`.

Источник истины — `plans/transport-single-policy/task-4.8.md`, пп. 3 и 4 публичного API.

Допущения (спека их не фиксирует):
* Имена полей камеры в рецепте — как в базе `inspection_full.yaml`:
  `resolution_width`, `resolution_height`, `source_target_fps`. Тест ищет их рекурсивно
  по разобранному YAML, не привязываясь к структуре списка процессов.
* Шва для пути базы в спеке нет. Наименее инвазивный способ испортить базу без правки
  рабочего дерева: скопировать пакет (без `tests/`) во временный каталог с раскладкой
  `<tmp>/scripts/capacity_bench`, испортить там `recipes/stand.yaml` и вызвать
  `render_recipe` в подпроцессе с `PYTHONPATH=<tmp>`. Допущение: `render_recipe` находит
  `recipes/stand.yaml` рядом со своим модулем (`Path(__file__).parent`) или от cwd.
  Тест проверяет `recipe.__file__` внутри подпроцесса — что импортирована именно копия.
"""

from __future__ import annotations

import importlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[3]
PKG_DIR = REPO / "scripts" / "capacity_bench"


def _matrix():
    return importlib.import_module("scripts.capacity_bench.matrix")


def _recipe():
    return importlib.import_module("scripts.capacity_bench.recipe")


def _find_values(node, key):
    """Все значения ключа `key` в произвольно вложенной структуре YAML."""
    found = []
    if isinstance(node, dict):
        for k, v in node.items():
            if k == key:
                found.append(v)
            found.extend(_find_values(v, key))
    elif isinstance(node, list):
        for item in node:
            found.extend(_find_values(item, key))
    return found


def _drop_keys(node, keys):
    if isinstance(node, dict):
        for k in list(node):
            if k in keys:
                del node[k]
            else:
                _drop_keys(node[k], keys)
    elif isinstance(node, list):
        for item in node:
            _drop_keys(item, keys)


# ---------------------------------------------------------------- matrix.cases


def test_cases_quick():
    assert _matrix().cases("quick") == [(480, 25, 30), (1080, 100, 30)]


def test_cases_full_order_height_then_fps():
    assert _matrix().cases("full") == [
        (480, 25, 30),
        (480, 60, 30),
        (480, 100, 30),
        (1080, 25, 30),
        (1080, 60, 30),
        (1080, 100, 30),
    ]


@pytest.mark.parametrize("name", ["nope", "", "medium"])
def test_cases_unknown_profile_raises_value_error(name):
    with pytest.raises(ValueError):
        _matrix().cases(name)


# -------------------------------------------------------------- render_recipe


@pytest.mark.parametrize(
    "height, fps, width",
    [(480, 25, 640), (1080, 100, 1920), (1080, 60, 1920), (480, 100, 640)],
)
def test_render_recipe_values_in_parsed_yaml(tmp_path, height, fps, width):
    path = _recipe().render_recipe(height, fps, tmp_path)
    assert path.is_file()
    assert tmp_path in path.resolve().parents or tmp_path == path.resolve().parent
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert _find_values(data, "resolution_width") == [width]
    assert _find_values(data, "resolution_height") == [height]
    assert _find_values(data, "source_target_fps") == [fps]


def test_render_recipe_unsupported_height_raises_value_error(tmp_path):
    with pytest.raises(ValueError):
        _recipe().render_recipe(720, 25, tmp_path)


_RENDER_IN_COPY = """
import sys, pathlib
import scripts.capacity_bench.recipe as recipe
print(recipe.__file__)
try:
    recipe.render_recipe(480, 25, pathlib.Path(sys.argv[1]))
except BaseException as exc:
    print(type(exc).__name__)
else:
    print("OK")
"""


def _render_in_copied_package(tmp_path: Path, corrupt: bool) -> tuple[str, str]:
    """(путь recipe.py внутри подпроцесса, «OK» либо имя исключения)."""
    # Якорь: пока пакета нет — падаем ModuleNotFoundError здесь, а не в подпроцессе.
    _recipe()
    root = tmp_path / "copy"
    (root / "scripts").mkdir(parents=True)
    (root / "scripts" / "__init__.py").write_text("", encoding="utf-8")
    shutil.copytree(
        PKG_DIR,
        root / "scripts" / "capacity_bench",
        ignore=shutil.ignore_patterns("tests", "__pycache__"),
    )
    if corrupt:
        base = root / "scripts" / "capacity_bench" / "recipes" / "stand.yaml"
        data = yaml.safe_load(base.read_text(encoding="utf-8"))
        _drop_keys(data, {"resolution_width", "resolution_height"})
        base.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    env = dict(os.environ, PYTHONPATH=str(root))
    proc = subprocess.run(
        [sys.executable, "-c", _RENDER_IN_COPY, str(out_dir)],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    module_file, verdict = proc.stdout.strip().splitlines()[-2:]
    return module_file, verdict


def test_render_recipe_intact_copy_renders_ok(tmp_path):
    """Контроль стенда: та же копия без порчи рендерится (иначе тест порчи ничего не доказывает)."""
    module_file, verdict = _render_in_copied_package(tmp_path, corrupt=False)
    assert Path(module_file).resolve().is_relative_to((tmp_path / "copy").resolve())
    assert verdict == "OK"


def test_render_recipe_bad_base_raises(tmp_path):
    """Испорченная база (нет полей разрешения) -> RuntimeError, а не тихий файл."""
    module_file, verdict = _render_in_copied_package(tmp_path, corrupt=True)
    assert Path(module_file).resolve().is_relative_to((tmp_path / "copy").resolve())
    assert verdict == "RuntimeError"
