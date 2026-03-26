# multiprocess_prototype/managers/recipe_yaml_stores.py
"""
Два схожих YAML-хранилища: снимки регистров и app-пресеты (отдельные файлы).

Общие операции чтения/записи — в базовом классе; полезная нагрузка различается.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

import yaml

RECIPE_FILE_VERSION = 1


def default_settings_recipes_path(data_path: str) -> str:
    """Путь к settings_recipes.yaml рядом с recipes.yaml."""
    return os.path.join(os.path.dirname(os.path.abspath(data_path)), "settings_recipes.yaml")


def pick_app_recipes_section(loaded: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Секция app: ключ `app_recipes` или legacy `settings_recipes`."""
    ar = loaded.get("app_recipes")
    if isinstance(ar, dict):
        return dict(ar)
    sr = loaded.get("settings_recipes")
    if isinstance(sr, dict):
        return dict(sr)
    return None


class YamlSlotFileStore:
    """Чтение/запись одного YAML-файла со словарём верхнего уровня."""

    def __init__(self, path: str) -> None:
        self.path = os.path.abspath(path)

    def read_dict(self) -> Optional[Dict[str, Any]]:
        if not os.path.isfile(self.path):
            return None
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                raw = yaml.safe_load(f)
        except OSError:
            return None
        if not isinstance(raw, dict):
            return None
        return raw

    def write_dict(self, data: Dict[str, Any]) -> None:
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            yaml.dump(
                data,
                f,
                allow_unicode=True,
                default_flow_style=False,
                sort_keys=False,
            )


class RegisterRecipesYamlStore(YamlSlotFileStore):
    """
    Файл рецептов регистров: version, current_register_recipe, register_recipes.
    Без app_recipes (они в AppRecipesYamlStore).
    """

    def save(
        self,
        *,
        version: int,
        current_register_recipe: int,
        register_recipes: Dict[str, Any],
    ) -> None:
        self.write_dict(
            {
                "version": version,
                "current_register_recipe": int(current_register_recipe),
                "register_recipes": register_recipes,
            }
        )


class AppRecipesYamlStore(YamlSlotFileStore):
    """
    Файл пресетов UI: version, current_app_recipe, app_recipes.
    При записи всегда ключ app_recipes.
    """

    def save(
        self,
        *,
        version: int,
        current_app_recipe: int,
        app_recipes: Dict[str, Any],
    ) -> None:
        self.write_dict(
            {
                "version": version,
                "current_app_recipe": int(current_app_recipe),
                "app_recipes": app_recipes,
            }
        )
