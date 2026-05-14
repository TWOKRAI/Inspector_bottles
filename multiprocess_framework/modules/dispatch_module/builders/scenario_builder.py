"""
Класс для формирования и управления сценариями.

Предоставляет удобный интерфейс для создания, редактирования и управления сценариями
отдельно от логики диспетчеризации.
"""

from typing import Dict, Any, Callable, Optional, List


class ScenarioBuilder:
    """
    Построитель сценариев для диспетчера.

    Предоставляет удобный интерфейс для создания и управления сценариями.
    Работает с диспетчером для регистрации сценариев.

    Пример использования:
        builder = ScenarioBuilder(dispatcher)
        builder.create("image_processing", "Обработка изображений")
        builder.add_handler("image_processing", "preprocess", handler1, stage=1)
        builder.add_handler("image_processing", "process", handler2, stage=2)
        builder.reorder("image_processing", "process", stage=1)  # Изменить порядок
    """

    def __init__(self, dispatcher):
        """
        Инициализация построителя сценариев.

        Args:
            dispatcher: Экземпляр Dispatcher для работы со сценариями
        """
        self.dispatcher = dispatcher

    def create(self, name: str, description: str = "", metadata: Dict[str, Any] = None) -> bool:
        """
        Создать новый сценарий.

        Args:
            name: Уникальное имя сценария
            description: Описание сценария
            metadata: Дополнительные метаданные

        Returns:
            True если создан, False если уже существует
        """
        return self.dispatcher.create_scenario(name, description, metadata)

    def delete(self, name: str) -> bool:
        """
        Удалить сценарий.

        Args:
            name: Имя сценария

        Returns:
            True если удален, False если не найден
        """
        return self.dispatcher.delete_scenario(name)

    def add_handler(
        self,
        scenario_name: str,
        handler_key: str,
        handler: Callable,
        stage: int,
        expects_full_message: bool = False,
        metadata: Dict[str, Any] = None,
        tags: List[str] = None,
    ) -> bool:
        """
        Добавить обработчик в сценарий.

        Args:
            scenario_name: Имя сценария
            handler_key: Ключ обработчика
            handler: Функция-обработчик
            stage: Этап выполнения (порядок в цепочке)
            expects_full_message: Если True, обработчик получает всё сообщение
            metadata: Дополнительные метаданные
            tags: Список тегов

        Returns:
            True если добавлен, False в случае ошибки
        """
        return self.dispatcher.add_handler_to_scenario(
            scenario_name, handler_key, handler, stage, expects_full_message, metadata, tags
        )

    def remove_handler(self, scenario_name: str, handler_key: str) -> bool:
        """
        Удалить обработчик из сценария.

        Args:
            scenario_name: Имя сценария
            handler_key: Ключ обработчика

        Returns:
            True если удален, False если не найден
        """
        return self.dispatcher.remove_handler_from_scenario(scenario_name, handler_key)

    def reorder(self, scenario_name: str, handler_key: str, new_stage: int) -> bool:
        """
        Изменить порядок обработчика в сценарии.

        Args:
            scenario_name: Имя сценария
            handler_key: Ключ обработчика
            new_stage: Новый этап выполнения

        Returns:
            True если изменен, False в случае ошибки
        """
        return self.dispatcher.reorder_handler_in_scenario(scenario_name, handler_key, new_stage)

    def update_metadata(self, scenario_name: str, metadata: Dict[str, Any]) -> bool:
        """
        Обновить метаданные сценария.

        Args:
            scenario_name: Имя сценария
            metadata: Новые метаданные

        Returns:
            True если обновлен, False если не найден
        """
        return self.dispatcher.update_scenario_metadata(scenario_name, metadata)

    def update_description(self, scenario_name: str, description: str) -> bool:
        """
        Обновить описание сценария.

        Args:
            scenario_name: Имя сценария
            description: Новое описание

        Returns:
            True если обновлен, False если не найден
        """
        return self.dispatcher.update_scenario_description(scenario_name, description)

    def get_info(self, scenario_name: str) -> Optional[Dict[str, Any]]:
        """
        Получить информацию о сценарии.

        Args:
            scenario_name: Имя сценария

        Returns:
            Словарь с информацией о сценарии или None
        """
        return self.dispatcher.get_scenario_info(scenario_name)

    def list_all(self) -> List[Dict[str, Any]]:
        """
        Получить список всех сценариев.

        Returns:
            Список словарей с информацией о сценариях
        """
        return self.dispatcher.get_all_scenarios()

    def exists(self, scenario_name: str) -> bool:
        """
        Проверить существование сценария.

        Args:
            scenario_name: Имя сценария

        Returns:
            True если существует, False иначе
        """
        return scenario_name in self.dispatcher.scenarios
