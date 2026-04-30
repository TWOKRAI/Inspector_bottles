# -*- coding: utf-8 -*-
"""
WorkerSchemaAdapter — извлекает настройки потока из SchemaBase-конфигов.

Роль в архитектуре:
    Worker*Config (SchemaBase)  →  WorkerSchemaAdapter  →  ThreadConfig dict

Адаптер позволяет Worker*Config.build() передавать поля потока через
Dict at Boundary без прямой зависимости от ThreadConfig.
"""

from typing import Any, Dict, Optional, Set, Type


_THREAD_FIELDS: Set[str] = {
    "priority",
    "restart_on_failure",
    "max_restarts",
    "dependencies",
    "worker_type",
    "execution_mode",
}


class WorkerSchemaAdapter:
    """Адаптер: SchemaBase -> ThreadConfig dict.

    Извлекает поля, относящиеся к ThreadConfig, из класса или экземпляра схемы.
    Результат передаётся как ``wc["thread"]`` в конфиг воркера и затем
    десериализуется через ``ThreadConfig.from_dict()``.
    """

    def adapt(self, schema_class: Type, **options) -> Dict[str, Any]:
        """Извлечь поля ThreadConfig из класса схемы (значения по умолчанию).

        Args:
            schema_class: Класс, унаследованный от SchemaBase.
            **options:    Переопределения полей.

        Returns:
            dict с ключами из _THREAD_FIELDS (только присутствующие в схеме).
        """
        result: Dict[str, Any] = {}
        for field in _THREAD_FIELDS:
            if hasattr(schema_class, field):
                result[field] = getattr(schema_class, field)
        result.update(options)
        return result

    def adapt_instance(self, schema_instance: Any, **options) -> Dict[str, Any]:
        """Извлечь поля ThreadConfig из экземпляра схемы.

        Args:
            schema_instance: Экземпляр SchemaBase.
            **options:       Переопределения полей.

        Returns:
            dict с ключами из _THREAD_FIELDS (только присутствующие в экземпляре).
        """
        result: Dict[str, Any] = {}
        for field in _THREAD_FIELDS:
            value = getattr(schema_instance, field, None)
            if value is not None:
                result[field] = value
        result.update(options)
        return result

    def get_thread_fields(self) -> Set[str]:
        """Вернуть набор полей, которые адаптер считает настройками потока."""
        return set(_THREAD_FIELDS)

    def build_thread_dict(
        self,
        priority: str = "NORMAL",
        execution_mode: str = "loop",
        restart_on_failure: bool = False,
        max_restarts: int = 3,
        worker_type: str = "application",
        dependencies: Optional[list] = None,
    ) -> Dict[str, Any]:
        """Вспомогательный метод: собрать thread dict из явных аргументов.

        Удобен для использования в Worker*Config.build():
            adapter = WorkerSchemaAdapter()
            thread_dict = adapter.build_thread_dict(priority=self.priority, ...)
        """
        return {
            "priority": priority,
            "execution_mode": execution_mode,
            "restart_on_failure": restart_on_failure,
            "max_restarts": max_restarts,
            "worker_type": worker_type,
            "dependencies": dependencies or [],
        }
