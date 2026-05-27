# -*- coding: utf-8 -*-
"""
Тесты lazy-регистрации domain-entity в SchemaRegistry (Task C.0).

Проверяет:
- Импорт `multiprocess_prototype.domain` НЕ регистрирует ничего в default registry.
- `register_domain_schemas()` регистрирует все 8 entities (7 + RecipeMeta).
- `register_domain_schemas(registry=custom)` регистрирует только в custom registry,
  default registry остаётся пустым.
"""

from __future__ import annotations

import pytest

# Имена всех 8 domain-entity (7 + вспомогательный RecipeMeta), которые регистрируются
_DOMAIN_ENTITY_NAMES = frozenset(
    {
        "PluginInstance",
        "Wire",
        "DisplayInstance",
        "Process",
        "RecipeMeta",
        "Recipe",
        "Topology",
        "Project",
    }
)


# ==============================================================================
# Фикстура: изолированный default registry
# ==============================================================================


@pytest.fixture()
def clean_default_registry():
    """Возвращает default SchemaRegistry с очищенным состоянием.

    После теста состояние не восстанавливается намеренно — тесты ниже
    используют изолированные registry или явно очищают default.
    Использует SchemaRegistry.clear() для изоляции тестов между собой.
    """
    from multiprocess_framework.modules.data_schema_module import get_default_registry

    registry = get_default_registry()
    # Запоминаем исходные схемы, чтобы восстановить после теста
    original_schemas = dict(registry._schemas)
    registry.clear()
    yield registry
    # Восстанавливаем — убираем domain-схемы, добавленные в тесте,
    # возвращаем те, что были до теста
    registry.clear()
    for name, cls in original_schemas.items():
        try:
            registry.register(name, cls)
        except Exception:
            pass  # nosec B110 — дублирующая регистрация не критична


# ==============================================================================
# Test 1: импорт не регистрирует ничего
# ==============================================================================


class TestImportDoesNotRegister:
    """Импорт пакета domain НЕ должен регистрировать entity в default registry."""

    def test_import_does_not_register_anything(self, clean_default_registry) -> None:
        """from multiprocess_prototype import domain → 0 регистраций в default registry.

        После наших изменений (Task C.0) импорт пакета больше не вызывает
        register_domain_schemas() автоматически.
        """
        # Импортируем (или используем уже импортированный) пакет domain
        import multiprocess_prototype.domain  # noqa: F401

        registered = clean_default_registry.list_schemas()
        # Ни одной из 8 domain-entity не должно быть в registry
        domain_registered = _DOMAIN_ENTITY_NAMES & set(registered)
        assert domain_registered == frozenset(), (
            f"Импорт domain зарегистрировал схемы: {domain_registered}. "
            "Регистрация должна быть явной через register_domain_schemas()."
        )


# ==============================================================================
# Test 2: register_domain_schemas() регистрирует все 8
# ==============================================================================


class TestRegisterDomainSchemas:
    """register_domain_schemas() регистрирует все 8 domain-entity (7 + RecipeMeta)."""

    def test_register_domain_schemas_registers_all_seven(self, clean_default_registry) -> None:
        """Вызов register_domain_schemas() → все 8 entities в default registry."""
        from multiprocess_prototype.domain import register_domain_schemas

        register_domain_schemas()  # регистрирует в default registry

        registered = set(clean_default_registry.list_schemas())
        missing = _DOMAIN_ENTITY_NAMES - registered
        assert missing == frozenset(), f"register_domain_schemas() не зарегистрировала: {missing}"

    def test_register_domain_schemas_accepts_custom_registry(self) -> None:
        """register_domain_schemas(registry=custom) → регистрирует только в custom.

        Default registry при этом остаётся нетронутым.
        """
        from multiprocess_framework.modules.data_schema_module import (
            SchemaRegistry,
            get_default_registry,
        )
        from multiprocess_prototype.domain import register_domain_schemas

        custom_registry = SchemaRegistry()
        default_registry = get_default_registry()

        # Запоминаем состояние default до вызова
        default_before = set(default_registry.list_schemas())

        register_domain_schemas(registry=custom_registry)

        # custom получил все 7
        custom_registered = set(custom_registry.list_schemas())
        missing = _DOMAIN_ENTITY_NAMES - custom_registered
        assert missing == frozenset(), f"custom registry не содержит: {missing}"

        # default не изменился
        default_after = set(default_registry.list_schemas())
        newly_added = default_after - default_before
        domain_newly_added = _DOMAIN_ENTITY_NAMES & newly_added
        assert domain_newly_added == frozenset(), f"default registry был загрязнён domain-схемами: {domain_newly_added}"
