"""Recipe I/O — чтение/запись рецептов в YAML.

Рецепт = snapshot topology + plugin configs.
Хранение: data/recipes/recipe_0.yaml ... recipe_7.yaml.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml


# Директория хранения рецептов
RECIPES_DIR = Path(__file__).resolve().parents[3] / "data" / "recipes"
# Это: multiprocess_prototype_2/data/recipes/


@dataclass
class RecipeInfo:
    """Метаданные рецепта (без полного содержимого)."""
    slot: int
    name: str
    description: str
    path: Path
    created: str  # ISO format
    modified: str  # ISO format


def scan_recipes(recipes_dir: Path | None = None) -> list[RecipeInfo]:
    """Сканировать директорию рецептов, вернуть список RecipeInfo для занятых слотов."""
    d = recipes_dir or RECIPES_DIR
    result = []

    for slot in range(8):
        path = d / f"recipe_{slot}.yaml"
        if path.exists():
            try:
                with open(path, encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
                result.append(RecipeInfo(
                    slot=slot,
                    name=data.get("name", f"Recipe {slot}"),
                    description=data.get("description", ""),
                    path=path,
                    created=data.get("created", ""),
                    modified=data.get("modified", ""),
                ))
            except Exception:
                pass  # Повреждённый файл — пропустить

    return result


def load_recipe(path: Path) -> dict[str, Any]:
    """Загрузить полное содержимое рецепта."""
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def save_recipe(
    path: Path,
    name: str,
    description: str,
    topology_snapshot: dict[str, Any],
) -> None:
    """Сохранить рецепт атомарно (tmp + replace)."""
    path.parent.mkdir(parents=True, exist_ok=True)

    now = datetime.now().isoformat(timespec="seconds")

    data = {
        "name": name,
        "description": description,
        "created": now,  # При перезаписи created обновляется (упрощение для MVP)
        "modified": now,
        "topology": topology_snapshot,
    }

    tmp_path = path.with_suffix(".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
    os.replace(tmp_path, path)


def delete_recipe(path: Path) -> bool:
    """Удалить файл рецепта. Возвращает True если был удалён."""
    try:
        path.unlink(missing_ok=True)
        return True
    except Exception:
        return False
