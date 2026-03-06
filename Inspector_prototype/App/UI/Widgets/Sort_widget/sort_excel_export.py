# -*- coding: utf-8 -*-
"""
Отдельный класс для экспорта/импорта рецептов в Excel.
YAML — основное хранилище, Excel — по кнопке «Форматировать в Excel».
"""
import json
import os
import pandas as pd


class SortExcelExporter:
    """Экспорт данных сортов в Excel и импорт из Excel в YAML-данные."""

    @staticmethod
    def export_to_excel(sort_data, excel_path=None):
        """
        Записать все рецепты из sort_data в Excel.
        Колонки: Parameter, default_value, real_value, 0, 1, ..., 21.
        """
        if excel_path is None:
            base = os.path.dirname(sort_data.yaml_path)
            excel_path = os.path.join(base, "value_settings.xlsx")

        recipes = sort_data._data.get("recipes", {})
        if not recipes:
            return False

        param_set = set()
        for rec in recipes.values():
            param_set.update(rec.keys())
        params = sorted(param_set)

        def _cell_value(v):
            if v is None:
                return ""
            if isinstance(v, bool):
                return "True" if v else "False"
            if isinstance(v, list):
                if v and isinstance(v[0], dict):
                    return json.dumps(v, ensure_ascii=False)
                return "; ".join(str(x) for x in v)
            return v

        columns = ["Parameter"] + list(recipes.keys())
        rows = []
        for p in params:
            row = [p]
            for col in columns[1:]:
                rec = recipes.get(col, {})
                row.append(_cell_value(rec.get(p, "")))
            rows.append(row)

        df = pd.DataFrame(rows, columns=columns)
        df.to_excel(excel_path, index=False)
        return True

    @staticmethod
    def import_from_excel(sort_data, excel_path=None):
        """
        Прочитать Excel и обновить sort_data (рецепты).
        Сохраняет sort_data в YAML после импорта.
        """
        if excel_path is None:
            base = os.path.dirname(sort_data.yaml_path)
            excel_path = os.path.join(base, "value_settings.xlsx")

        if not os.path.isfile(excel_path):
            return False

        try:
            df = pd.read_excel(excel_path)
            if "Parameter" not in df.columns:
                return False
        except Exception as e:
            print(f"Ошибка чтения Excel: {e}")
            return False

        params = df["Parameter"].astype(str).tolist()
        for col in df.columns:
            if col == "Parameter":
                continue
            values = df[col].tolist()
            # приводим к типам, подходящим для YAML (числа остаются числами)
            recipe = {}
            for p, v in zip(params, values):
                if pd.isna(v):
                    recipe[p] = ""
                elif isinstance(v, (int, float)):
                    recipe[p] = int(v) if isinstance(v, float) and v == int(v) else v
                else:
                    recipe[p] = str(v)
            sort_data._data["recipes"][str(col)] = recipe
        sort_data.save()
        return True
