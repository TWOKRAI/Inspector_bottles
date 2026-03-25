# multiprocess_prototype/managers/recipe_manager.py
"""
Хранение рецептов в YAML.

- register_recipes: снимки RegistersManager (model_dump_all), ADR-080.
- app_recipes: снимки набора SchemaBase приложения (имя схемы -> dict полей).

Обратная совместимость: старые ключи recipes / current_recipe подхватываются при load.
"""

from __future__ import annotations

import os
from copy import deepcopy
from typing import Any, Dict, Optional, Union

import yaml

from multiprocess_prototype.registers.snapshot_migrate import migrate_register_recipe_snapshot

RecipeId = Union[int, str]

_DATA_VERSION = 1


def _default_data_path() -> str:
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    return os.path.join(root, "data", "recipes.yaml")


class RecipeManager:
    """
    Загрузка/сохранение рецептов в YAML.

    Ключи слотов: строки "0".."21", "default_value", "real_value" и т.д.
    """

    def __init__(self, data_path: Optional[str] = None) -> None:
        self.data_path = os.path.abspath(data_path or _default_data_path())
        self._data: Dict[str, Any] = {
            "version": _DATA_VERSION,
            "current_register_recipe": 0,
            "current_app_recipe": 0,
            "register_recipes": {},
            "app_recipes": {},
        }
        self.load()

    def _apply_legacy_format(self, loaded: Dict[str, Any]) -> None:
        """Старый формат: current_recipe, recipes."""
        self._data["version"] = int(loaded.get("version", _DATA_VERSION))
        self._data["current_register_recipe"] = int(loaded.get("current_recipe", 0))
        self._data["current_app_recipe"] = int(loaded.get("current_app_recipe", 0))
        recipes = loaded.get("recipes")
        self._data["register_recipes"] = dict(recipes) if isinstance(recipes, dict) else {}
        ar = loaded.get("app_recipes")
        self._data["app_recipes"] = dict(ar) if isinstance(ar, dict) else {}

    def _apply_new_format(self, loaded: Dict[str, Any]) -> None:
        self._data["version"] = int(loaded.get("version", _DATA_VERSION))
        self._data["current_register_recipe"] = int(
            loaded.get("current_register_recipe", loaded.get("current_recipe", 0))
        )
        self._data["current_app_recipe"] = int(loaded.get("current_app_recipe", 0))
        rr = loaded.get("register_recipes")
        if isinstance(rr, dict):
            self._data["register_recipes"] = dict(rr)
        elif isinstance(loaded.get("recipes"), dict):
            self._data["register_recipes"] = dict(loaded["recipes"])
        else:
            self._data["register_recipes"] = {}
        ar = loaded.get("app_recipes")
        self._data["app_recipes"] = dict(ar) if isinstance(ar, dict) else {}

    def load(self) -> None:
        if not os.path.isfile(self.data_path):
            return
        try:
            with open(self.data_path, "r", encoding="utf-8") as f:
                loaded = yaml.safe_load(f)
            if not isinstance(loaded, dict):
                return
            if isinstance(loaded.get("register_recipes"), dict) or isinstance(
                loaded.get("app_recipes"), dict
            ):
                self._apply_new_format(loaded)
            elif isinstance(loaded.get("recipes"), dict):
                self._apply_legacy_format(loaded)
        except OSError:
            pass

    def save(self) -> None:
        try:
            os.makedirs(os.path.dirname(self.data_path) or ".", exist_ok=True)
            payload = {
                "version": self._data.get("version", _DATA_VERSION),
                "current_register_recipe": self._data.get("current_register_recipe", 0),
                "current_app_recipe": self._data.get("current_app_recipe", 0),
                "register_recipes": self._data.get("register_recipes", {}),
                "app_recipes": self._data.get("app_recipes", {}),
            }
            with open(self.data_path, "w", encoding="utf-8") as f:
                yaml.dump(payload, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
        except OSError:
            pass

    @staticmethod
    def _key(recipe_id: RecipeId) -> str:
        return str(recipe_id)

    def get_current_recipe_number(self) -> int:
        """Обратная совместимость: номер слота рецепта регистров."""
        return self.get_current_register_recipe_number()

    def set_current_recipe_number(self, number: int) -> None:
        self.set_current_register_recipe_number(number)

    def get_current_register_recipe_number(self) -> int:
        v = self._data.get("current_register_recipe", self._data.get("current_recipe", 0))
        try:
            return int(v)
        except (TypeError, ValueError):
            return 0

    def set_current_register_recipe_number(self, number: int) -> None:
        self._data["current_register_recipe"] = int(number)
        self.save()

    def get_current_app_recipe_number(self) -> int:
        v = self._data.get("current_app_recipe", 0)
        try:
            return int(v)
        except (TypeError, ValueError):
            return 0

    def set_current_app_recipe_number(self, number: int) -> None:
        self._data["current_app_recipe"] = int(number)
        self.save()

    def save_registers_to_recipe(self, registers_bridge: Any, recipe_id: RecipeId) -> bool:
        """Снимок model_dump_all() в слот register_recipes."""
        if not hasattr(registers_bridge, "model_dump_all"):
            return False
        snap = registers_bridge.model_dump_all()
        self._data.setdefault("register_recipes", {})[self._key(recipe_id)] = deepcopy(snap)
        self.save()
        return True

    def load_recipe_to_registers(self, registers_bridge: Any, recipe_id: RecipeId) -> bool:
        """Применить снимок слота через model_validate_all."""
        if not hasattr(registers_bridge, "model_validate_all"):
            return False
        raw = self._data.get("register_recipes", {}).get(self._key(recipe_id))
        if raw is None:
            return False
        try:
            migrated = migrate_register_recipe_snapshot(deepcopy(raw))
            registers_bridge.model_validate_all(migrated, strict=False)
        except Exception:
            return False
        return True

    def ensure_slot_from_registers(
        self,
        registers_bridge: Any,
        recipe_id: RecipeId,
    ) -> None:
        """Если слота нет — заполнить текущим снимком (инициализация файла)."""
        reg = self._data.setdefault("register_recipes", {})
        key = self._key(recipe_id)
        if key in reg and reg[key]:
            return
        if hasattr(registers_bridge, "model_dump_all"):
            reg[key] = deepcopy(registers_bridge.model_dump_all())
            self.save()

    def save_app_recipe_snapshot(self, recipe_id: RecipeId, snapshot: Dict[str, Any]) -> bool:
        """Сохранить снимок app-схем в слот app_recipes."""
        self._data.setdefault("app_recipes", {})[self._key(recipe_id)] = deepcopy(snapshot)
        self.save()
        return True

    def load_app_recipe_snapshot(self, recipe_id: RecipeId) -> Optional[Dict[str, Any]]:
        """Загрузить снимок app-схем из слота."""
        raw = self._data.get("app_recipes", {}).get(self._key(recipe_id))
        if raw is None or not isinstance(raw, dict):
            return None
        return deepcopy(raw)

    def ensure_app_slot_from_snapshot(
        self,
        recipe_id: RecipeId,
        default_snapshot: Dict[str, Any],
    ) -> None:
        """Если слота нет — записать default_snapshot."""
        app_r = self._data.setdefault("app_recipes", {})
        key = self._key(recipe_id)
        if key in app_r and app_r[key]:
            return
        app_r[key] = deepcopy(default_snapshot)
        self.save()
