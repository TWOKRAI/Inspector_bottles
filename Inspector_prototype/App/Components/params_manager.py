import pandas as pd
from PyQt5.QtWidgets import QMessageBox


class ParamsManager:
    """
    Централизованный менеджер для работы с параметрами всех виджетов.
    Собирает параметры из виджетов, сохраняет/загружает рецепты в Excel.
    """
    
    def __init__(self, widgets_dict, filename='value_settings.xlsx'):
        """
        widgets_dict: {widget_name: widget_instance} - словарь всех виджетов
        """
        self.widgets = widgets_dict
        self.filename = filename
        self.df = None
        self.create_dataframe()
    
    def get_all_params(self):
        """Собирает все параметры из всех виджетов"""
        all_params = {}
        for widget_name, widget in self.widgets.items():
            if hasattr(widget, 'get_params'):
                try:
                    widget_params = widget.get_params()
                    all_params.update(widget_params)
                except Exception as e:
                    print(f"Ошибка получения параметров из {widget_name}: {e}")
        return {k: all_params[k] for k in sorted(all_params)}
    
    def create_dataframe(self):
        """Создает или загружает DataFrame из Excel"""
        if not self.load_dataframe_from_excel():
            all_params = self.get_all_params()
            self.df = pd.DataFrame({
                'Parameter': list(all_params.keys())
            })
            self.save_to_excel('default_value')
            self.save_to_excel('real_value')
            for number in range(22):
                self.save_to_excel(number)
    
    def load_dataframe_from_excel(self):
        """Загружает DataFrame из Excel файла"""
        try:
            temp_df = pd.read_excel(self.filename)
            if 'Parameter' not in temp_df.columns:
                return False
            self.df = temp_df
            return True
        except FileNotFoundError:
            return False
        except Exception as e:
            print(f'Ошибка чтения файла: {e}')
            return False
    
    def save_to_excel(self, value_column='default_value'):
        """Сохраняет текущие значения в указанную колонку (сорт)"""
        try:
            all_params = self.get_all_params()
            str_values = [str(v) for v in all_params.values()]
            
            # Если DataFrame еще не создан, создаем его
            if self.df is None:
                self.df = pd.DataFrame({
                    'Parameter': list(all_params.keys())
                })
            
            # Добавляем новые параметры, если они появились
            existing_params = set(self.df['Parameter'].tolist())
            new_params = set(all_params.keys())
            if new_params - existing_params:
                # Добавляем новые строки для новых параметров
                new_rows = pd.DataFrame({
                    'Parameter': list(new_params - existing_params)
                })
                self.df = pd.concat([self.df, new_rows], ignore_index=True)
                self.df = self.df.sort_values('Parameter').reset_index(drop=True)
            
            # Обновляем значения
            self.df[str(value_column)] = [str(all_params.get(p, '')) for p in self.df['Parameter']]
            self.df.to_excel(self.filename, index=False)
            print(f'Сохранен столбец {value_column}')
        except Exception as e:
            print(f'Ошибка сохранения столбца {value_column}: {e}')
            import traceback
            traceback.print_exc()
    
    def read_from_excel(self, value_column='default_value'):
        """Читает значения из указанной колонки"""
        try:
            if self.df is None or value_column not in self.df.columns:
                return {}
            params_dict = dict(zip(self.df['Parameter'], self.df[value_column]))
            return params_dict
        except Exception as e:
            print(f'Ошибка чтения столбца {value_column}: {e}')
            return {}
    
    def apply_recipe(self, recipe_number):
        """Применяет рецепт (сорт) ко всем виджетам"""
        params_dict = self.read_from_excel(str(recipe_number))
        if not params_dict:
            params_dict = self.read_from_excel('default_value')
            if params_dict:
                self.save_to_excel(str(recipe_number))
        
        for widget_name, widget in self.widgets.items():
            if hasattr(widget, 'apply_params'):
                try:
                    widget.apply_params(params_dict)
                except Exception as e:
                    print(f"Ошибка применения параметров к {widget_name}: {e}")
    
    def save_recipe(self, recipe_number):
        """Сохраняет текущие значения в рецепт"""
        if recipe_number != 0:
            self.save_to_excel(str(recipe_number))
    
    def set_default_recipe(self, recipe_number):
        """Устанавливает рецепт как дефолтный"""
        self.apply_recipe('default_value')
