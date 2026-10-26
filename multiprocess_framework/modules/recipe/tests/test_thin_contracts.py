# -*- coding: utf-8 -*-
"""Тонкие контракты над дельта-движком и единый ``compute_rev`` (C-30, Task 1.1b).

Контракт — ``plans/2026-10-26_recipe-save-noise/design.md`` §2.1 и §9.1:

  - ``update_yaml_preserving`` / ``update_blueprint_metadata_preserving`` пишут через
    дельта-движок: комментарии внутри заменяемого ключа живы, равная часть не трогается,
    пустая дельта не пишет файл;
  - ``compute_rev`` — одна функция в ``format.py``; ``service.compute_rev`` — тот же объект.

Правила файла: ожидаемые байты — литералы; эффект проверяется по байтам и ``st_mtime_ns``
файла, не по вызовам API. Файлы пишутся ``write_bytes`` (на Windows ``write_text`` дал бы CRLF).
"""

from __future__ import annotations

import os
from pathlib import Path

from multiprocess_framework.modules.recipe.manager import RecipeManager
from multiprocess_framework.modules.recipe.recipe_engine import RecipeEngine
from multiprocess_framework.modules.recipe.yaml_io import (
    update_blueprint_metadata_preserving,
    update_yaml_preserving,
)
from multiprocess_framework.modules.state_store_module.core.tree_store import TreeStore

# Метка времени, заведомо не равная «сейчас»: перезапись файла её изменит.
_OLD_MTIME_NS = 1_700_000_000_000_000_000


def _write(path: Path, text: str) -> tuple[bytes, int]:
    """Записать UTF-8 байты (LF), выставить старый mtime; вернуть (байты, mtime_ns) с диска."""
    path.write_bytes(text.encode("utf-8"))
    os.utime(path, ns=(_OLD_MTIME_NS, _OLD_MTIME_NS))
    return path.read_bytes(), path.stat().st_mtime_ns


def test_update_yaml_preserving_keeps_comments_inside_replaced_key(tmp_path: Path) -> None:
    """Ключ ``blueprint`` заменяется новым значением, но комментарии ВНУТРИ него живы:
    прежняя запись ``data[key] = value`` стирала их вместе со старым поддеревом."""
    path = tmp_path / "recipe.yaml"
    _write(
        path,
        "# заголовок\n"
        "name: demo\n"
        "blueprint:\n"
        "  # --- Камера ---\n"
        "  processes:\n"
        "    - process_name: camera_0\n"
        "  # --- Провода ---\n"
        "  wires:\n"
        "    - source: a\n"
        "      target: b\n",
    )

    update_yaml_preserving(
        path,
        {
            "blueprint": {
                "processes": [{"process_name": "camera_0"}],
                "wires": [{"source": "a", "target": "b"}, {"source": "c", "target": "d"}],
            }
        },
    )

    assert path.read_bytes() == (
        "# заголовок\n"
        "name: demo\n"
        "blueprint:\n"
        "  # --- Камера ---\n"
        "  processes:\n"
        "    - process_name: camera_0\n"
        "  # --- Провода ---\n"
        "  wires:\n"
        "    - source: a\n"
        "      target: b\n"
        "    - source: c\n"
        "      target: d\n"
    ).encode("utf-8")


def test_update_yaml_preserving_noop_does_not_write(tmp_path: Path) -> None:
    """Значение ключа равно записанному — дельта пуста: байты и ``st_mtime_ns`` прежние
    (прежняя запись переписывала файл при каждом вызове)."""
    path = tmp_path / "recipe.yaml"
    before_bytes, before_mtime = _write(path, "# заголовок\nname:   demo\nversion: 3\n")

    update_yaml_preserving(path, {"name": "demo", "version": 3})

    assert path.read_bytes() == before_bytes
    assert path.stat().st_mtime_ns == before_mtime


def test_update_blueprint_metadata_preserving_keeps_comments_via_engine(tmp_path: Path) -> None:
    """``gui_positions`` заменяется новым значением, но комментарий между его записями жив;
    неизменная позиция ``a.x`` и flow-стиль списка ``b.y`` не тронуты."""
    path = tmp_path / "recipe.yaml"
    _write(
        path,
        "name: demo\n"
        "blueprint:\n"
        "  processes: []\n"
        "  metadata:\n"
        "    gui_positions:\n"
        "      a.x: [1.0, 2.0]\n"
        "      # позиция второго узла\n"
        "      b.y: [3.0, 4.0]\n"
        "    locked_nodes: []\n",
    )

    update_blueprint_metadata_preserving(path, {"gui_positions": {"a.x": [1.0, 2.0], "b.y": [5.0, 6.0]}})

    assert path.read_bytes() == (
        "name: demo\n"
        "blueprint:\n"
        "  processes: []\n"
        "  metadata:\n"
        "    gui_positions:\n"
        "      a.x: [1.0, 2.0]\n"
        "      # позиция второго узла\n"
        "      b.y: [5.0, 6.0]\n"
        "    locked_nodes: []\n"
    ).encode("utf-8")


def test_update_blueprint_metadata_preserving_noop_without_file(tmp_path: Path) -> None:
    """Файла нет — ничего не создаётся и исключения нет (прежний no-op сохранён)."""
    path = tmp_path / "ghost.yaml"

    update_blueprint_metadata_preserving(path, {"gui_positions": {"x": [1.0, 2.0]}, "locked_nodes": []})

    assert not path.exists()
    assert list(tmp_path.iterdir()) == []


def test_duplicate_keeps_comments_and_sets_name(tmp_path: Path) -> None:
    """``RecipeManager.duplicate`` на дефолтном писателе: копия побайтно как исходник,
    кроме значения ``name`` (комментарии заголовка, строки и внутри blueprint живы)."""
    recipes_dir = tmp_path / "recipes"
    recipes_dir.mkdir()
    _write(
        recipes_dir / "src.yaml",
        "# заголовок\nname: src  # имя рецепта\nversion: 3\nblueprint:\n  # --- Камера ---\n  processes: []\n",
    )
    manager = RecipeManager(engine=RecipeEngine(store=TreeStore({"cameras": {}}), recipes_dir=recipes_dir))

    assert manager.duplicate("src", "dst") is True

    assert (recipes_dir / "dst.yaml").read_bytes() == (
        "# заголовок\nname: dst  # имя рецепта\nversion: 3\nblueprint:\n  # --- Камера ---\n  processes: []\n"
    ).encode("utf-8")


def test_compute_rev_single_definition() -> None:
    """``compute_rev`` определён один раз (``format.py``); ``service.compute_rev`` — тот же объект."""
    from multiprocess_framework.modules.recipe import format as recipe_format
    from multiprocess_framework.modules.recipe import service

    assert recipe_format.compute_rev is service.compute_rev


def test_compute_rev_is_sha256_hex_of_bytes() -> None:
    """Значение ревизии не изменилось при переносе: sha256 hex от байтов (литерал для ``abc``)."""
    from multiprocess_framework.modules.recipe import format as recipe_format

    assert recipe_format.compute_rev(b"abc") == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"


def test_update_yaml_preserving_emptied_list_with_tail_comment(tmp_path: Path) -> None:
    """Ревью 1.1b: ``items`` опустел при хвостовом комментарии — файл читается PyYAML, комментарий один раз."""
    import yaml

    path = tmp_path / "r.yaml"
    _write(path, "a: 1\nitems:\n  - x: 1  # eol\n# c-after-items\nb: 2\n")

    update_yaml_preserving(path, {"items": []})

    text = path.read_text(encoding="utf-8")
    assert yaml.safe_load(text) == {"a": 1, "items": [], "b": 2}
    assert text.count("# c-after-items") == 1


def test_update_blueprint_metadata_emptied_locked_nodes_with_tail_comment(tmp_path: Path) -> None:
    """Ревью 1.1b: автосохранение раскладки ``locked_nodes: []`` при хвостовом комментарии — файл валиден."""
    import yaml

    path = tmp_path / "r.yaml"
    _write(
        path,
        "blueprint:\n  metadata:\n    gui_positions:\n      n1: [1, 2]\n    locked_nodes:\n      - n1\n"
        "# next section\nz: 1\n",
    )

    update_blueprint_metadata_preserving(path, {"locked_nodes": []})

    text = path.read_text(encoding="utf-8")
    assert yaml.safe_load(text) == {
        "blueprint": {"metadata": {"gui_positions": {"n1": [1, 2]}, "locked_nodes": []}},
        "z": 1,
    }
    assert text.count("# next section") == 1


def test_update_yaml_preserving_tuple_value_written_as_list(tmp_path: Path) -> None:
    """Ревью 1.1b, р2: значение-кортеж пишется списком (прежний писатель писал ``k: [1, 2]``), не ValueError."""
    import yaml

    path = tmp_path / "r.yaml"
    _write(path, "a: 1\n")

    update_yaml_preserving(path, {"k": (1, 2)})

    assert yaml.safe_load(path.read_text(encoding="utf-8")) == {"a": 1, "k": [1, 2]}


def test_update_blueprint_metadata_replaced_block_positions_stay_block(tmp_path: Path) -> None:
    """Ревью 1.1b, р2 (p31): ``gui_positions`` целиком сменил ключи — карта остаётся блочной,
    ``main:`` на своей строке (раньше опустевшая по дороге карта навсегда уходила во flow).
    Форма — ``phone_inspect.yaml``. ``locked_nodes: []`` пополняется блочным списком: ruamel 0.19
    читает пустой ``[]`` без flow-стиля (``None``), так же писал и прежний писатель."""
    path = tmp_path / "recipe.yaml"
    _write(
        path,
        "name: demo\n"
        "blueprint:\n"
        "  metadata:\n"
        "    gui_positions:\n"
        "      phone_cam.phone_camera:\n"
        "        - 16.0\n"
        "        - 40.0\n"
        "      phone_view:\n"
        "        - 0.0\n"
        "        - 0.0\n"
        "    locked_nodes: []\n"
        "\n"
        "displays:\n"
        "  - id: phone_view\n",
    )

    update_blueprint_metadata_preserving(path, {"gui_positions": {"main": [1, 2]}, "locked_nodes": ["a"]})

    assert path.read_bytes() == (
        "name: demo\n"
        "blueprint:\n"
        "  metadata:\n"
        "    gui_positions:\n"
        "      main:\n"
        "        - 1\n"
        "        - 2\n"
        "    locked_nodes:\n"
        "      - a\n"
        "\n"
        "displays:\n"
        "  - id: phone_view\n"
    ).encode("utf-8")


def test_update_yaml_preserving_tuple_equal_to_file_list_does_not_write(tmp_path: Path) -> None:
    """Кортеж, равный списку в файле, — пустая дельта: байты и ``st_mtime_ns`` прежние."""
    path = tmp_path / "r.yaml"
    before_bytes, before_mtime = _write(path, "k: [1, 2]  # позиция\n")

    update_yaml_preserving(path, {"k": (1, 2)})

    assert path.read_bytes() == before_bytes
    assert path.stat().st_mtime_ns == before_mtime
