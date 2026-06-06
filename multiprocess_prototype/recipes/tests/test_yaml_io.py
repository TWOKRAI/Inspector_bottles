# -*- coding: utf-8 -*-
"""Тесты yaml_io.update_yaml_preserving — запись YAML с сохранением комментариев.

Покрывает сценарии fix recipe-v3-engine-decouple:
  - persist #1: обновление scalar `pipeline:` в app.yaml без потери комментариев;
  - сохранение рецепта: обновление top-level `blueprint` с сохранением заголовка.
"""

from __future__ import annotations

import textwrap

import yaml

from multiprocess_prototype.recipes.yaml_io import update_yaml_preserving


def test_creates_new_file_from_updates(tmp_path):
    """Несуществующий файл создаётся из updates."""
    path = tmp_path / "new.yaml"
    update_yaml_preserving(path, {"name": "demo", "version": 3})

    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert data == {"name": "demo", "version": 3}


def test_preserves_header_comment_on_scalar_update(tmp_path):
    """persist #1: обновление pipeline: сохраняет комментарии и прочие ключи."""
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
