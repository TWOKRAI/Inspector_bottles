# -*- coding: utf-8 -*-
"""
Централизованный менеджер параметров виджетов.
Хранилище рецептов — SortData (YAML). Excel только через виджет (экспорт отдельным классом).
"""
from App.Widget.Sort_widjet.sort_data import SortData


class ParamsManager:
    """
    Менеджер параметров: собирает параметры из виджетов,
    сохраняет/загружает рецепты через SortData (YAML).
    """

    def __init__(self, widgets_dict, sort_data=None):
        """
        widgets_dict: {widget_name: widget_instance}
        sort_data: SortData — хранилище рецептов (YAML). Если None — создаётся новый экземпляр.
        """
        self.widgets = widgets_dict
        self.sort_data = sort_data if sort_data is not None else SortData()
        self._ensure_data()

    def _ensure_data(self):
        """Если в SortData ещё нет рецептов — инициализировать из текущих параметров виджетов."""
        if not self.sort_data.has_data():
            all_params = self.get_all_params()
            self.sort_data.init_from_params(all_params)

    def get_all_params(self):
        """Собирает все параметры из всех виджетов."""
        all_params = {}
        for widget_name, widget in self.widgets.items():
            if hasattr(widget, "get_params"):
                try:
                    widget_params = widget.get_params()
                    all_params.update(widget_params)
                except Exception as e:
                    print(f"Ошибка получения параметров из {widget_name}: {e}")
        return {k: all_params[k] for k in sorted(all_params)}

    def save_to_excel(self, value_column="default_value"):
        """Сохраняет текущие значения виджетов в рецепт (в YAML). Имя метода оставлено для совместимости."""
        try:
            all_params = self.get_all_params()
            self.sort_data.set_recipe(value_column, all_params)
            print(f"Сохранён рецепт {value_column}")
        except Exception as e:
            print(f"Ошибка сохранения рецепта {value_column}: {e}")
            import traceback
            traceback.print_exc()

    def read_from_excel(self, value_column="default_value"):
        """Читает рецепт из хранилища (YAML). Имя метода оставлено для совместимости."""
        return self.sort_data.get_recipe(value_column)

    def apply_recipe(self, recipe_number):
        """Применяет рецепт (сорт) ко всем виджетам."""
        params_dict = self.read_from_excel(str(recipe_number))
        if not params_dict:
            params_dict = self.read_from_excel("default_value")
            if params_dict:
                self.save_to_excel(str(recipe_number))

        for widget_name, widget in self.widgets.items():
            if hasattr(widget, "apply_params"):
                try:
                    widget.apply_params(params_dict)
                except Exception as e:
                    print(f"Ошибка применения параметров к {widget_name}: {e}")

    def save_recipe(self, recipe_number):
        """Сохраняет текущие значения виджетов в рецепт."""
        self.save_to_excel(str(recipe_number))

    def set_default_recipe(self, recipe_number):
        """Загружает дефолтный рецепт в виджеты."""
        self.apply_recipe("default_value")
