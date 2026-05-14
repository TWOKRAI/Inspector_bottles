"""
Unit-тесты для утилит (core/helpers.py, core/reference.py).

Сценарии:
- helpers: get_nested_value, set_nested_value, merge_with_defaults, extract_fields (в т.ч. вложенные ключи).
- reference: DataReference, is_reference, resolve, convert_all_references в структуре данных.
"""

from typing import Any, Dict


from ..core.helpers import (
    get_nested_value,
    set_nested_value,
    merge_with_defaults,
    extract_fields,
)
from ..core.reference import (
    DataReference,
    convert_all_references,
    is_reference,
)


# ============================================================================
# Тесты Utils
# ============================================================================


def test_utils_nested_and_merge():
    """Вложенные ключи (dot notation), дефолты при отсутствии, merge_with_defaults, extract_fields с nested=True."""
    # Установка вложенных значений
    data: Dict[str, Any] = {}
    set_nested_value(data, "database.host", "localhost")
    set_nested_value(data, "database.port", 5432)
    assert data["database"]["host"] == "localhost"
    assert data["database"]["port"] == 5432

    # Получение вложенных значений
    assert get_nested_value(data, "database.port") == 5432
    assert get_nested_value(data, "database.missing", default=10) == 10

    # Объединение с дефолтами
    defaults = {"database": {"host": "127.0.0.1", "timeout": 30}}
    merged = merge_with_defaults(data, defaults)
    assert merged["database"]["host"] == "localhost"  # из data перезаписывает
    assert merged["database"]["timeout"] == 30  # из defaults

    # Извлечение полей
    extracted = extract_fields(
        {"name": "comp", "config": {"log_level": "INFO", "timeout": 5}},
        {"name", "config.log_level"},
        nested=True,
    )
    assert extracted == {"name": "comp", "config": {"log_level": "INFO"}}


def test_data_reference_and_conversion():
    """DataReference с resolver, to_dict, resolve; convert_all_references в dict и списках."""
    # Хранилище для резолвинга ссылок
    resolved_store: Dict[str, Any] = {"queue:1": "qobj", "evt:2": {"flag": True}}

    def resolver(ref_id: str) -> Any:
        return resolved_store.get(ref_id)

    # Создание и резолвинг ссылки
    ref = DataReference("queue:1", resolver=resolver)
    assert is_reference(ref)
    assert ref.to_dict() == {"_ref": True, "ref_id": "queue:1"}
    assert ref.resolve() == "qobj"

    # Конвертация всех ссылок в структуре данных
    ref_dict = {"_ref": True, "ref_id": "evt:2"}
    data = {"queue": ref, "evt": ref_dict, "plain": 5, "items": [ref_dict]}
    converted = convert_all_references(data, resolver=resolver)
    assert converted["queue"] == "qobj"
    assert converted["evt"] == {"flag": True}
    assert converted["plain"] == 5  # обычное значение не изменено
    assert converted["items"][0] == {"flag": True}  # ссылка в списке разрешена


def test_data_reference_from_dict():
    """Восстановление DataReference из dict с _ref/ref_id и резолвинг через resolver."""

    def resolver(ref_id: str) -> Any:
        return f"resolved_{ref_id}"

    ref_dict = {"_ref": True, "ref_id": "test:123"}
    ref = DataReference.from_dict(ref_dict, resolver=resolver)
    assert ref.ref_id == "test:123"
    assert ref.resolve() == "resolved_test:123"
