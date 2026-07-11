# -*- coding: utf-8 -*-
"""Тесты yaml_io.update_yaml_preserving — запись YAML с сохранением комментариев.

Home-тест generic-writer'а модуля `recipe` (C3, ADR-RCP-005). Покрывает:
  - persist scalar `pipeline:` в app.yaml без потери комментариев;
  - обновление top-level `blueprint` с сохранением заголовка;
  - точечный persist `blueprint.metadata.*` без порчи per-node комментариев.
"""

from __future__ import annotations

import textwrap

import yaml

from multiprocess_framework.modules.recipe.yaml_io import (
    update_blueprint_metadata_preserving,
    update_yaml_preserving,
)


def test_creates_new_file_from_updates(tmp_path):
    """Несуществующий файл создаётся из updates."""
    path = tmp_path / "new.yaml"
    update_yaml_preserving(path, {"name": "demo", "version": 3})

    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert data == {"name": "demo", "version": 3}


def test_preserves_header_comment_on_scalar_update(tmp_path):
    """persist: обновление pipeline: сохраняет комментарии и прочие ключи."""
    path = tmp_path / "app.yaml"
    path.write_text(
        textwrap.dedent(
            """\
            # Главный конфиг — комментарий-заголовок.
            system: backend/config/system.yaml
            # Активный pipeline (рецепт).
            pipeline: recipes/old.yaml
            recipes: recipes
            """
        ),
        encoding="utf-8",
    )

    update_yaml_preserving(path, {"pipeline": "recipes/color_inspect.yaml"})

    text = path.read_text(encoding="utf-8")
    assert "# Главный конфиг — комментарий-заголовок." in text
    assert "# Активный pipeline (рецепт)." in text
    assert "pipeline: recipes/color_inspect.yaml" in text
    assert "recipes: recipes" in text  # прочие ключи не тронуты
    assert "old.yaml" not in text  # старое значение заменено


def test_updates_only_named_keys(tmp_path):
    """Обновляются только переданные top-level ключи; остальные сохраняются."""
    path = tmp_path / "recipe.yaml"
    path.write_text(
        textwrap.dedent(
            """\
            # Рецепт-заголовок.
            name: demo
            version: 3
            description: "Описание"
            blueprint:
              processes: []
              wires: []
            active_services:
              - svc_a
            """
        ),
        encoding="utf-8",
    )

    update_yaml_preserving(
        path,
        {"blueprint": {"processes": [{"process_name": "p1"}], "wires": [], "displays": []}},
    )

    text = path.read_text(encoding="utf-8")
    assert "# Рецепт-заголовок." in text  # заголовок сохранён
    data = yaml.safe_load(text)
    assert data["name"] == "demo"  # не тронут
    assert data["version"] == 3
    assert data["active_services"] == ["svc_a"]  # не тронут
    assert data["blueprint"]["processes"][0]["process_name"] == "p1"  # обновлён


# ---------------------------------------------------------------------------
# update_blueprint_metadata_preserving — free-layout авто-персист
# ---------------------------------------------------------------------------


def _recipe_with_comments() -> str:
    return textwrap.dedent(
        """\
        # Рецепт-заголовок (free-layout).
        name: demo
        version: 3
        blueprint:
          name: demo
          # --- Камера ---
          processes:
            - process_name: camera_0
              plugins:
                - plugin_name: capture
          # --- Провода ---
          wires:
            - source: a
              target: b
        """
    )


def test_metadata_write_preserves_inner_comments(tmp_path):
    """free-layout: запись blueprint.metadata НЕ стирает комментарии внутри blueprint."""
    path = tmp_path / "recipe.yaml"
    path.write_text(_recipe_with_comments(), encoding="utf-8")

    update_blueprint_metadata_preserving(
        path,
        {"gui_positions": {"camera_0.capture": [10.0, 20.0]}, "locked_nodes": ["camera_0.capture"]},
    )

    text = path.read_text(encoding="utf-8")
    # Комментарии (заголовок + per-node ВНУТРИ blueprint) сохранены
    assert "# Рецепт-заголовок (free-layout)." in text
    assert "# --- Камера ---" in text
    assert "# --- Провода ---" in text
    data = yaml.safe_load(text)
    # processes/wires не тронуты
    assert data["blueprint"]["processes"][0]["process_name"] == "camera_0"
    assert data["blueprint"]["wires"][0] == {"source": "a", "target": "b"}
    # metadata записан
    assert data["blueprint"]["metadata"]["gui_positions"]["camera_0.capture"] == [10.0, 20.0]
    assert data["blueprint"]["metadata"]["locked_nodes"] == ["camera_0.capture"]


def test_metadata_write_replaces_gui_positions_wholesale(tmp_path):
    """Повторная запись заменяет gui_positions целиком (не копит устаревшие ноды)."""
    path = tmp_path / "recipe.yaml"
    path.write_text(_recipe_with_comments(), encoding="utf-8")

    update_blueprint_metadata_preserving(path, {"gui_positions": {"old.node": [1.0, 2.0]}, "locked_nodes": []})
    update_blueprint_metadata_preserving(path, {"gui_positions": {"new.node": [3.0, 4.0]}, "locked_nodes": []})

    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    gp = data["blueprint"]["metadata"]["gui_positions"]
    assert "old.node" not in gp  # устаревшая нода не осталась
    assert gp["new.node"] == [3.0, 4.0]


def test_metadata_write_noop_without_blueprint(tmp_path):
    """raw-topology без вложенного blueprint — no-op (layout писать некуда)."""
    path = tmp_path / "raw.yaml"
    path.write_text("processes: []\nwires: []\n", encoding="utf-8")

    update_blueprint_metadata_preserving(path, {"gui_positions": {"x": [1.0, 2.0]}, "locked_nodes": []})

    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert "metadata" not in data  # ничего не добавлено
    assert data == {"processes": [], "wires": []}


def test_metadata_write_noop_missing_file(tmp_path):
    """Несуществующий файл — no-op без исключения."""
    update_blueprint_metadata_preserving(tmp_path / "ghost.yaml", {"gui_positions": {}, "locked_nodes": []})
    assert not (tmp_path / "ghost.yaml").exists()
