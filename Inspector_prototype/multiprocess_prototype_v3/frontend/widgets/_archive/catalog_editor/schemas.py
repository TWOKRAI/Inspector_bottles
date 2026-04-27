"""UI конфигурация Catalog Editor."""
from pydantic import BaseModel


class CatalogEditorUiConfig(BaseModel):
    title: str = "Каталог операций"
    col_name: str = "Имя"
    col_type_key: str = "Ключ"
    col_module_path: str = "Путь к модулю"
    col_params_schema: str = "Схема параметров"
    col_on_error: str = "При ошибке"
    col_description: str = "Описание"
    btn_add: str = "Добавить"
    btn_remove: str = "Удалить"
    btn_save: str = "Сохранить"
