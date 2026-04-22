# multiprocess_prototype/managers/recipe_manager.py
"""
Хранение рецептов в YAML.

- register_recipes: снимки RegistersManager (model_dump_all), ADR-080 — файл recipes.yaml.
- app_recipes: снимки SchemaBase приложения — файл settings_recipes.yaml (рядом с recipes).

Всегда два файла; старый объединённый recipes.yaml при загрузке разносится при save.

Обратная совместимость: старые ключи recipes / current_recipe подхватываются при load.

Загрузка в регистры: перед ``model_validate_all`` нормализуется снимок processor
(legacy vision_pipeline); это не часть ``RegistersManager``.
"""

from __future__ import annotations

import os
from copy import deepcopy
from typing import Any, Dict, Optional, Union


from .recipe_yaml_stores import (
    AppRecipesYamlStore,
    RECIPE_FILE_VERSION,
    RegisterRecipesYamlStore,
    default_settings_recipes_path,
    pick_app_recipes_section,
)
from multiprocess_prototype_v2.registers.migration import normalize_processor_register_payload
from multiprocess_prototype_v2.registers.names import PROCESSOR_REGISTER

RecipeId = Union[int, str]

_DATA_VERSION = RECIPE_FILE_VERSION


def _migrate_register_recipe_snapshot(data: Dict[str, Any]) -> Dict[str, Any]:
    """Deep copy + нормализация вложенных полей processor."""
    raw = deepcopy(data)
    proc = raw.get(PROCESSOR_REGISTER)
    if not isinstance(proc, dict):
        return raw
    raw[PROCESSOR_REGISTER] = normalize_processor_register_payload(dict(proc))
    return raw

# Слот заводских значений регистров и UI-пресетов (кнопка «По умолчанию» в панелях рецептов).
DEFAULT_RECIPE_SLOT_ID: str = "0"


def _default_data_path() -> str:
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    return os.path.join(root, "data", "recipes.yaml")


class RecipeManager:
    """
    Фасад: два YAML-файла (регистры + app-пресеты), единый контракт для UI.

    Ключи слотов: строки "0".."21", "default_value", "real_value" и т.д.
    Слот **"0"** — заводской пресет (кнопка «По умолчанию»).
    """

    def __init__(
        self,
        data_path: Optional[str] = None,
        app_recipes_path: Optional[str] = None,
    ) -> None:
        self.data_path = os.path.abspath(data_path or _default_data_path())
        self.app_recipes_path = os.path.abspath(
            app_recipes_path if app_recipes_path is not None else default_settings_recipes_path(self.data_path)
        )
        self._register_store = RegisterRecipesYamlStore(self.data_path)
        self._app_store = AppRecipesYamlStore(self.app_recipes_path)
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
        picked = pick_app_recipes_section(loaded)
        self._data["app_recipes"] = picked if picked is not None else {}

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
        picked = pick_app_recipes_section(loaded)
        self._data["app_recipes"] = picked if picked is not None else {}

    def _apply_from_main_file(self, loaded: Dict[str, Any]) -> None:
        if isinstance(loaded.get("register_recipes"), dict) or isinstance(
            loaded.get("app_recipes"), dict
        ):
            self._apply_new_format(loaded)
        elif isinstance(loaded.get("recipes"), dict):
            self._apply_legacy_format(loaded)
        else:
            self._apply_new_format(loaded)

    def _merge_app_from_sidecar(self) -> None:
        """Снимок app из settings_recipes.yaml перекрывает встроенный app из старого объединённого файла."""
        raw = self._app_store.read_dict()
        if not raw:
            return
        picked = pick_app_recipes_section(raw)
        if picked is not None:
            self._data["app_recipes"] = picked
        if "current_app_recipe" in raw:
            try:
                self._data["current_app_recipe"] = int(raw["current_app_recipe"])
            except (TypeError, ValueError):
                pass

    def load(self) -> None:
        try:
            main = self._register_store.read_dict()
            if isinstance(main, dict):
                self._apply_from_main_file(main)
            self._merge_app_from_sidecar()
        except OSError:
            pass

    def save(self) -> None:
        try:
            ver = int(self._data.get("version", _DATA_VERSION))
            cr = int(self._data.get("current_register_recipe", 0))
            ca = int(self._data.get("current_app_recipe", 0))
            rr = self._data.get("register_recipes", {})
            ar = self._data.get("app_recipes", {})
            self._register_store.save(
                version=ver,
                current_register_recipe=cr,
                register_recipes=rr,
            )
            self._app_store.save(
                version=ver,
                current_app_recipe=ca,
                app_recipes=ar,
            )
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
            migrated = _migrate_register_recipe_snapshot(raw)
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
