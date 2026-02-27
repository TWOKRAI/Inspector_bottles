# -*- coding: utf-8 -*-
"""
Минимальная проверка использования фреймворка: Registers — потребитель data_schema_module.

Полные тесты discovery, register_package_schemas, преобразования имён — в модуле фреймворка:
  multiprocess_framework/refactored/modules/data_schema_module/tests/test_register_discovery.py

Запуск: из корня Inspector_prototype — pytest App/Registers/tests/ -v
"""
import pytest

from App.Registers import RegistersManager


def test_registers_manager_works_as_usage_of_framework():
    """RegistersManager создаётся с пакетами по умолчанию и возвращает метаданные полей."""
    rm = RegistersManager()
    assert rm.register_names()
    assert "draw" in rm.register_names()
    meta = rm.get_field_metadata("draw", "dp")
    assert isinstance(meta, dict)
    assert meta.get("min") == 0.1
