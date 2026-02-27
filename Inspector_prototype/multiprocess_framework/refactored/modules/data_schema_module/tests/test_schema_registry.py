"""
Unit тесты для SchemaManager.

Тестирует регистрацию схем, создание экземпляров и валидацию.

Структура тестов:
- Тестовые модели: Определение моделей для тестирования
- Фикстуры: Подготовка окружения перед каждым тестом
- Тесты регистрации: Проверка регистрации и управления схемами
- Тесты создания экземпляров: Проверка создания объектов с дефолтами
- Тесты валидации: Проверка валидации данных по схемам
- Тесты потокобезопасности: Проверка работы в многопоточной среде
"""

import threading
from typing import Any, Dict

import pytest
from pydantic import BaseModel, Field

from ..registry.schema_registry import SchemaManager, register_schema


# ============================================================================
# Тестовые модели
# ============================================================================

class SampleModel(BaseModel):
    """Тестовая модель конфигурации."""

    name: str = "default"
    count: int = 1
    nested: Dict[str, Any] = Field(default_factory=lambda: {"level": 1})


# ============================================================================
# Фикстуры
# ============================================================================

@pytest.fixture(autouse=True)
def reset_schema_registry():
    """Сбрасываем одиночку перед каждым тестом, чтобы не загрязнять состояние."""
    registry = SchemaManager.get_instance()
    registry.clear()
    yield registry
    registry.clear()


# ============================================================================
# Тесты SchemaManager
# ============================================================================

def test_schema_registry_basic_flow(reset_schema_registry: SchemaManager):
    """
    Тест базового функционала SchemaManager.
    
    Проверяет основной workflow работы с реестром схем:
    1. Регистрация схемы
    2. Проверка наличия схемы
    3. Получение схемы
    4. Создание экземпляра с дефолтными значениями
    5. Создание экземпляра с данными
    6. Удаление схемы
    
    Это базовый тест, который должен проходить всегда.
    """
    registry = reset_schema_registry

    # Шаг 1: Регистрация схемы
    # register() возвращает True при успешной регистрации
    assert registry.register("Sample", SampleModel)
    assert "Sample" in registry.list_schemas()
    assert registry.has_schema("Sample")
    assert registry.get_schema("Sample") is SampleModel

    # Создание экземпляра с полными данными
    full = registry.create_instance("Sample", {"name": "custom", "count": 5})
    assert full.name == "custom"
    assert full.count == 5

    # Создание экземпляра с частичными данными (дефолты подставляются)
    partial = registry.create_instance("Sample", {"name": "only-name"})
    assert partial.name == "only-name"
    assert partial.count == 1  # дефолт подставлен

    # Получение дефолтных значений
    defaults = registry.get_defaults("Sample")
    assert defaults == SampleModel().model_dump()

    # Валидация валидных данных
    ok, instance, err = registry.validate("Sample", {"name": "x", "count": 2})
    assert ok and err is None and instance.count == 2

    # Валидация невалидных данных
    bad, instance, err = registry.validate("Sample", {"name": "x", "count": "oops"})
    assert not bad and instance is None and "count" in str(err)

    # Удаление схемы
    assert registry.unregister("Sample")
    assert not registry.has_schema("Sample")


def test_schema_registry_thread_safety():
    """
    Тест потокобезопасности SchemaManager.
    
    Проверяет, что SchemaManager корректно работает в многопоточной среде:
    1. Несколько потоков одновременно регистрируют схемы
    2. Все схемы успешно регистрируются без потерь
    3. Нет конфликтов при параллельной регистрации
    
    Это критично для многопроцессных приложений, где разные потоки
    могут регистрировать схемы одновременно.
    """
    registry = SchemaManager.get_instance()
    registry.clear()

    def register_schemas(thread_id: int):
        """
        Регистрирует схемы с уникальными именами для каждого потока.
        
        Каждый поток регистрирует 10 схем с уникальными именами,
        чтобы проверить отсутствие конфликтов при параллельной регистрации.
        """
        for i in range(10):
            class TempModel(BaseModel):
                value: int = i

            # Уникальное имя схемы для каждого потока
            # Формат: Temp{thread_id}_{i} гарантирует уникальность
            schema_name = f"Temp{thread_id}_{i}"
            registry.register(schema_name, TempModel)

    # Создаем 5 потоков, каждый регистрирует 10 схем
    threads = [threading.Thread(target=register_schemas, args=(tid,)) for tid in range(5)]
    
    # Запускаем все потоки параллельно
    for t in threads:
        t.start()
    
    # Ждем завершения всех потоков
    for t in threads:
        t.join()

    # Проверяем, что все схемы зарегистрированы
    # Ожидаем 50 схем: 10 схем * 5 потоков
    schemas = registry.list_schemas()
    assert len(schemas) == 50, f"Ожидалось 50 схем, получено {len(schemas)}"
    
    # Проверяем, что все схемы уникальны (нет дубликатов)
    assert len(set(schemas)) == 50, "Обнаружены дубликаты схем"

    registry.clear()


def test_register_schema_decorator(reset_schema_registry: SchemaManager):
    """
    Декоратор @register_schema при импорте регистрирует класс в SchemaManager.
    Проверяем: класс с декоратором появляется в реестре под заданным именем.
    """
    registry = reset_schema_registry

    @register_schema("DecoratedConfig", auto_register=True)
    class DecoratedConfig(BaseModel):
        level: str = "INFO"

    assert registry.has_schema("DecoratedConfig")
    assert registry.get_schema("DecoratedConfig") is DecoratedConfig
    inst = registry.create_instance("DecoratedConfig", {})
    assert inst.level == "INFO"


def test_validate_recipe(reset_schema_registry: SchemaManager):
    """
    validate_recipe проверяет снимок рецепта: словарь {имя_регистра: data}.
    Успех — все ключи проходят валидацию по зарегистрированным схемам; при ошибке — (False, сообщение).
    """
    registry = reset_schema_registry
    registry.register("Sample", SampleModel)

    # Валидный снимок
    ok, err = registry.validate_recipe({"Sample": {"name": "r1", "count": 1}})
    assert ok is True and err is None

    # Невалидные данные по одному из регистров
    ok2, err2 = registry.validate_recipe({"Sample": {"name": "r2", "count": "not_int"}})
    assert ok2 is False and err2 is not None and "Sample" in err2

    # Не словарь — ошибка
    ok3, err3 = registry.validate_recipe("not_a_dict")
    assert ok3 is False and "словарем" in err3

