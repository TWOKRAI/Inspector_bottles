# -*- coding: utf-8 -*-
"""
ProcessSchemaAdapter — преобразование SchemaBase в конфиг для запуска процесса.

Назначение:
    Адаптер преобразует SchemaBase (или HasBuild) в пару (name, config_dict),
    которую SystemLauncher принимает через add_process(). Это реализует
    принцип Dict at Boundary: через границу процесса передаётся только dict,
    а не Pydantic-объект.

Паттерн: Dependency Inversion
    ProcessSchemaAdapter реализует ISchemaAdapter (из data_schema_module.interfaces).
    data_schema_module ничего не знает о process_manager_module — зависимость
    однонаправленная.

Расширяемость:
    - Переопределить _get_schema_name() для кастомного именования процессов.
    - Добавить фильтрацию полей через опцию include_fields / exclude_fields.
    - Добавить поддержку вложенных конфигов через опцию flatten=True.
    - Добавить валидацию обязательных полей через опцию validate=True.

Использование:
    from process_manager_module.adapters.schema_adapter import ProcessSchemaAdapter
    from my_module.config import ProcessConfig, WorkerConfig

    adapter = ProcessSchemaAdapter()

    # Вариант 1: через экземпляры
    process_name, process_dict = adapter.adapt_instance(ProcessConfig())
    worker_name, worker_dict = adapter.adapt_instance(WorkerConfig())
    launcher.add_process(process_name, {**process_dict, "workers": [(worker_name, worker_dict)]})

    # Вариант 2: через helper build_process_with_workers (из data_schema_module)
    from data_schema_module import build_process_with_workers
    launcher.add_process(*build_process_with_workers(ProcessConfig(), WorkerConfig()))
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple, Type


class ProcessSchemaAdapter:
    """
    Адаптер для преобразования SchemaBase в конфиг запуска процесса.

    Реализует протокол ISchemaAdapter из data_schema_module.interfaces.

    Особенность: adapt() и adapt_instance() возвращают Tuple[str, Dict],
    а не просто Dict — это соответствует интерфейсу SystemLauncher.add_process().

    Результат adapt_instance():
        ("ProcessConfig", {"timeout": 5.0, "workers": 4, ...})
    """

    def adapt(self, schema_class: Type, **options) -> Dict[str, Any]:
        """
        Преобразовать класс схемы в config_dict (с дефолтными значениями).

        Args:
            schema_class: Класс схемы (наследник SchemaBase).
            **options:
                include_fields (list): Включить только указанные поля.
                exclude_fields (list): Исключить указанные поля.
                flatten (bool): Сплющить вложенные dict-поля.

        Returns:
            Dict с дефолтными значениями полей схемы.
        """
        try:
            instance = schema_class()
        except Exception:
            return {}

        return self._extract_dict(instance, **options)

    def adapt_instance(self, schema_instance: Any, **options) -> Tuple[str, Dict[str, Any]]:
        """
        Преобразовать экземпляр схемы в (name, config_dict) для SystemLauncher.

        Args:
            schema_instance: Экземпляр SchemaBase или HasBuild.
            **options:
                include_fields (list): Включить только указанные поля.
                exclude_fields (list): Исключить указанные поля.

        Returns:
            Tuple[str, Dict] — (process_name, config_dict).
        """
        # HasBuild: делегировать в data_schema_module.config_to_dict (один источник правды)
        if hasattr(schema_instance, "build") and callable(schema_instance.build):
            try:
                from data_schema_module import config_to_dict
                return config_to_dict(schema_instance)
            except Exception:
                pass

        name = self._get_schema_name(type(schema_instance))
        config_dict = self._extract_dict(schema_instance, **options)
        return name, config_dict

    def adapt_many(
        self,
        *schema_instances: Any,
        **options,
    ) -> List[Tuple[str, Dict[str, Any]]]:
        """
        Преобразовать несколько экземпляров схем в список (name, config_dict).

        Удобно для передачи нескольких воркеров:
            workers = adapter.adapt_many(Worker1Config(), Worker2Config())
        """
        return [self.adapt_instance(inst, **options) for inst in schema_instances]

    def build_process_entry(
        self,
        process_config: Any,
        *worker_configs: Any,
        **options,
    ) -> Tuple[str, Dict[str, Any]]:
        """
        Построить полную запись процесса с воркерами для SystemLauncher.

        Формат результата соответствует ожиданиям SystemLauncher.add_process():
            (process_name, {
                ...process_fields...,
                "workers": [
                    (worker_name, worker_dict),
                    ...
                ]
            })

        Args:
            process_config: Экземпляр конфига процесса (SchemaBase или HasBuild).
            *worker_configs: Экземпляры конфигов воркеров.
            **options: Передаются в adapt_instance().

        Returns:
            Tuple[str, Dict] для передачи в SystemLauncher.add_process().
        """
        process_name, process_dict = self.adapt_instance(process_config, **options)

        if worker_configs:
            workers = [
                self.adapt_instance(wc, **options)
                for wc in worker_configs
            ]
            process_dict = dict(process_dict)
            process_dict["workers"] = workers

        return process_name, process_dict

    # -------------------------------------------------------------------------
    # Внутренние методы (переопределяемые в подклассах)
    # -------------------------------------------------------------------------

    def _extract_dict(self, instance: Any, **options) -> Dict[str, Any]:
        """Извлечь dict из экземпляра схемы с учётом фильтров."""
        if hasattr(instance, "model_dump"):
            data = instance.model_dump()
        elif hasattr(instance, "__dict__"):
            data = {k: v for k, v in instance.__dict__.items() if not k.startswith("_")}
        else:
            return {}

        include = options.get("include_fields")
        exclude = options.get("exclude_fields", [])

        if include is not None:
            data = {k: v for k, v in data.items() if k in include}
        if exclude:
            data = {k: v for k, v in data.items() if k not in exclude}

        if options.get("flatten"):
            data = self._flatten_dict(data)

        return data

    def _get_schema_name(self, schema_class: Type) -> str:
        """
        Получить имя схемы для использования как ключа процесса.

        Порядок:
        1. Атрибут класса __schema_name__ (явное именование).
        2. Имя класса без суффиксов Config/Schema/Registers.
        3. Имя класса как есть.
        """
        if hasattr(schema_class, "__schema_name__"):
            return schema_class.__schema_name__

        name = schema_class.__name__
        for suffix in ("Config", "Schema", "Registers", "Register"):
            if name.endswith(suffix) and len(name) > len(suffix):
                return name[: -len(suffix)]

        return name

    def _flatten_dict(self, data: Dict[str, Any], prefix: str = "") -> Dict[str, Any]:
        """Сплющить вложенные словари: {"a": {"b": 1}} -> {"a_b": 1}."""
        result: Dict[str, Any] = {}
        for key, value in data.items():
            full_key = f"{prefix}{key}" if not prefix else f"{prefix}_{key}"
            if isinstance(value, dict):
                result.update(self._flatten_dict(value, full_key))
            else:
                result[full_key] = value
        return result
