"""UI конфигурация Chain Editor."""

from pydantic import BaseModel


class ChainEditorUiConfig(BaseModel):
    """Конфигурация UI для Chain Editor."""

    title: str = "Цепочка обработки"
    col_order: str = "#"
    col_operation: str = "Операция"
    col_params: str = "Параметры"
    col_enabled: str = "Вкл"
    col_process: str = "Процесс"
    col_worker: str = "Worker"
    btn_add: str = "Добавить"
    btn_remove: str = "Удалить"
    btn_up: str = "Вверх"
    btn_down: str = "Вниз"
