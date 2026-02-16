# -*- coding: utf-8 -*-
"""
Класс для работы с данными сортов/рецептов.
Хранилище — YAML (удобно читать и править вручную).
"""
import os
import yaml


class SortData:
    """
    Хранение и загрузка рецептов в YAML.
    Структура файла:
      current_recipe: 2
      parameter_info: {}   # описание параметров (на будущее)
      recipes:
        default_value: { hl: 0, sl: 50, ... }
        real_value: { ... }
        "0": { ... }
        ...
    """

    def __init__(self, yaml_path=None):
        if yaml_path is None:
            # Путь: Inspector_prototype/Data/Recipes/value_settings.yaml
            base = os.path.dirname(__file__)
            base = os.path.normpath(os.path.join(base, "..", "..", ".."))
            data_dir = os.path.join(base, "Data", "Recipes")
            os.makedirs(data_dir, exist_ok=True)
            yaml_path = os.path.join(data_dir, "value_settings.yaml")
        self.yaml_path = os.path.abspath(yaml_path)
        self._data = {"current_recipe": 0, "parameter_info": {}, "recipes": {}}
        self.load()

    def load(self):
        """Загрузить данные из YAML. Если файла нет — оставить пустые рецепты."""
        if not os.path.isfile(self.yaml_path):
            return
        try:
            with open(self.yaml_path, "r", encoding="utf-8") as f:
                loaded = yaml.safe_load(f)
            if loaded:
                self._data["current_recipe"] = loaded.get("current_recipe", 0)
                self._data["parameter_info"] = loaded.get("parameter_info", {}) or {}
                self._data["recipes"] = loaded.get("recipes", {})
                if self._data["recipes"] is None:
                    self._data["recipes"] = {}
        except Exception as e:
            print(f"Ошибка загрузки YAML сортов: {e}")

    def save(self):
        """Сохранить данные в YAML."""
        try:
            os.makedirs(os.path.dirname(self.yaml_path) or ".", exist_ok=True)
            with open(self.yaml_path, "w", encoding="utf-8") as f:
                yaml.dump(self._data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
        except Exception as e:
            print(f"Ошибка сохранения YAML сортов: {e}")

    def has_data(self):
        """Есть ли хотя бы один рецепт."""
        return bool(self._data.get("recipes"))

    def get_recipe(self, recipe_id):
        """
        recipe_id: int (0..21) или str ('default_value', 'real_value').
        Возвращает словарь { parameter_name: value }. value может быть bool, list, число, строка.
        """
        key = recipe_id if isinstance(recipe_id, str) else str(recipe_id)
        raw = self._data["recipes"].get(key, {}) or {}
        return dict(raw)

    def set_recipe(self, recipe_id, params_dict):
        """Записать рецепт. params_dict — { parameter_name: value }."""
        key = recipe_id if isinstance(recipe_id, str) else str(recipe_id)
        if key not in self._data["recipes"]:
            self._data["recipes"][key] = {}
        self._data["recipes"][key] = {k: v for k, v in params_dict.items()}
        self.save()

    def get_current_recipe_number(self):
        return self._data.get("current_recipe", 0)

    def set_current_recipe_number(self, number):
        self._data["current_recipe"] = number
        self.save()

    def get_parameter_names(self):
        """Список имён параметров (из первого доступного рецепта)."""
        for key in ("default_value", "real_value") + tuple(str(i) for i in range(22)):
            r = self._data["recipes"].get(key, {})
            if r:
                return sorted(r.keys())
        return []

    def get_parameter_info(self, param_name):
        """Описание параметра (для столбца «Информация»)."""
        return self._data.get("parameter_info", {}).get(param_name, "")

    def set_parameter_info(self, param_name, info_text):
        """Сохранить описание параметра."""
        if "parameter_info" not in self._data:
            self._data["parameter_info"] = {}
        self._data["parameter_info"][str(param_name)] = str(info_text)
        self.save()

    def set_recipe_param(self, recipe_id, param_name, value):
        """Обновить один параметр в рецепте. value может быть bool, list, число, строка."""
        key = recipe_id if isinstance(recipe_id, str) else str(recipe_id)
        if key not in self._data["recipes"]:
            self._data["recipes"][key] = {}
        self._data["recipes"][key][str(param_name)] = value
        self.save()

    def init_from_params(self, params_dict):
        """
        Инициализировать хранилище из одного словаря параметров:
        создать default_value, real_value и рецепты 0..21.
        """
        if not params_dict:
            return
        self._data["recipes"]["default_value"] = dict(params_dict)
        self._data["recipes"]["real_value"] = dict(params_dict)
        for i in range(22):
            self._data["recipes"][str(i)] = dict(params_dict)
        self.save()
