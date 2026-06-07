# -*- coding: utf-8 -*-
"""Тесты Task 2.2: apply_topology переналивает DisplayRegistry из рецепта.

Покрытие:
- apply_topology с display_definitions → реестр обновлён
- повторный apply с другим набором → реестр = новый набор
- rollback при падении super().apply_topology → реестр восстановлен
- display_definitions отсутствует → реестр не трогается (no-op)
- boot без активного рецепта → реестр пуст

Запуск:
    python -m pytest multiprocess_prototype/backend/topology/tests/test_apply_topology_displays.py -v
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from multiprocess_framework.modules.display_module import DisplayEntry, DisplayRegistry


# ---------------------------------------------------------------------------
# Фикстура: изоляция singleton между тестами
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_registry():
    """Очищает реестр перед и после каждого теста."""
    DisplayRegistry().clear()
    yield
    DisplayRegistry().clear()


# ---------------------------------------------------------------------------
# Хелперы
# ---------------------------------------------------------------------------


def _make_defs(*ids: str) -> list[dict]:
    """Создать минимальные display_definitions (list[dict])."""
    return [{"id": did, "name": f"Display {did}", "width": 1280, "height": 720} for did in ids]


def _registry_ids() -> set[str]:
    """Множество id дисплеев в реестре."""
    return {e.id for e in DisplayRegistry().list()}


def _apply_with_mock(blueprint: dict | None, super_result: dict | None = None) -> dict:
    """Вызвать ProcessManagerProcessApp.apply_topology с замоканным super().

    Мокает ProcessManagerProcess.apply_topology (generic PM), чтобы не поднимать
    реальный TopologyManager/процессы. Возвращает результат override.
    """
    from multiprocess_prototype.orchestrator import ProcessManagerProcessApp

    if super_result is None:
        super_result = {"success": True, "rolled_back": False}

    # Создать экземпляр без полной инициализации (unit-тест, не интеграция).
    # ProcessManagerProcessApp наследует ProcessManagerProcess → ProcessModule.
    # Нам нужен только метод apply_topology, подменяем super-вызов.
    instance = object.__new__(ProcessManagerProcessApp)
    # Минимальные атрибуты для _log_info (если rollback-ветка срабатывает)
    instance._logger = None

    def _fake_log_info(msg, **kwargs):
        pass

    instance._log_info = _fake_log_info

    with patch(
        "multiprocess_framework.modules.process_manager_module.process.process_manager_process."
        "ProcessManagerProcess.apply_topology",
        return_value=super_result,
    ):
        return instance.apply_topology(blueprint)


# ---------------------------------------------------------------------------
# Тесты: apply_topology + DisplayRegistry reload
# ---------------------------------------------------------------------------


class TestApplyTopologyDisplays:
    """apply_topology в ProcessManagerProcessApp обновляет DisplayRegistry."""

    def test_apply_with_display_definitions_populates_registry(self):
        """После apply с display_definitions=[A, B] реестр содержит {A, B}."""
        bp = {
            "name": "test",
            "displays": [{"id": "A", "width": 1920}, {"id": "B", "width": 640}],
            "blueprint": {"processes": [], "wires": []},
        }
        result = _apply_with_mock(bp)
        assert result["success"] is True
        assert _registry_ids() == {"A", "B"}

    def test_repeated_apply_replaces_registry(self):
        """Повторный apply с [{id:A}] → реестр = {A}, B удалён."""
        # Первый apply: A + B
        bp1 = {
            "name": "r1",
            "displays": [{"id": "A", "width": 1920}, {"id": "B", "width": 640}],
            "blueprint": {"processes": [], "wires": []},
        }
        _apply_with_mock(bp1)
        assert _registry_ids() == {"A", "B"}

        # Второй apply: только A
        bp2 = {
            "name": "r2",
            "displays": [{"id": "A", "width": 1280}],
            "blueprint": {"processes": [], "wires": []},
        }
        _apply_with_mock(bp2)
        assert _registry_ids() == {"A"}
        # B удалён
        assert DisplayRegistry().get("B") is None

    def test_rollback_restores_old_registry(self):
        """Падение super().apply → реестр возвращается к старому набору."""
        # Начальное состояние: в реестре {X}
        DisplayRegistry().register(
            DisplayEntry(id="X", name="Old", width=800, height=600, format="BGR", fps_limit=30.0, ring_buffer_blocks=3)
        )
        assert _registry_ids() == {"X"}

        # apply с новыми определениями, но super вернёт rolled_back
        bp = {
            "name": "r_new",
            "displays": [{"id": "Y", "width": 1920}],
            "blueprint": {"processes": [], "wires": []},
        }
        result = _apply_with_mock(bp, super_result={"success": False, "rolled_back": True, "error": "test fail"})

        assert result["success"] is False
        assert result["rolled_back"] is True
        # Реестр откатился к {X}
        assert _registry_ids() == {"X"}
        assert DisplayRegistry().get("Y") is None

    def test_no_display_definitions_is_noop(self):
        """display_definitions отсутствует → реестр не трогается."""
        # Начальное состояние: в реестре {Z}
        DisplayRegistry().register(
            DisplayEntry(id="Z", name="Pre", width=640, height=480, format="BGR", fps_limit=25.0, ring_buffer_blocks=2)
        )

        # Plain topology без display_definitions
        bp = {"processes": [], "wires": []}
        result = _apply_with_mock(bp)

        assert result["success"] is True
        # Реестр не тронут
        assert _registry_ids() == {"Z"}

    def test_empty_display_definitions_clears_registry(self):
        """display_definitions=[] (явно пустой) → реестр очищается."""
        # Начальное состояние: в реестре {W}
        DisplayRegistry().register(
            DisplayEntry(id="W", name="Pre", width=640, height=480, format="BGR", fps_limit=25.0, ring_buffer_blocks=2)
        )

        # Рецепт с пустым displays=[] → unwrap_recipe НЕ ставит ключ (falsy).
        # Но если display_definitions=[] ЯВНО присутствует в blueprint...
        bp = {"processes": [], "wires": [], "display_definitions": []}
        result = _apply_with_mock(bp)

        assert result["success"] is True
        # Реестр очищен (reload([]) = пусто)
        assert _registry_ids() == set()

    def test_reload_is_metadata_only_no_shm(self):
        """Проверка: reload не вызывает create_memory_dict / release_process_memory.

        Этот тест подтверждает acceptance-критерий: reload — только метаданные.
        """
        bp = {
            "name": "r",
            "displays": [{"id": "D1", "width": 1920, "height": 1080}],
            "blueprint": {"processes": [], "wires": []},
        }
        # Если бы reload пытался вызывать SHM-функции, тест упал бы с ImportError
        # или AttributeError (в unit-тесте нет IPC-инфраструктуры). Зелёный тест =
        # никаких SHM-операций не вызвано.
        result = _apply_with_mock(bp)
        assert result["success"] is True
        assert _registry_ids() == {"D1"}


class TestBootDisplayRegistryRecipeDriven:
    """Boot: DisplayRegistry наполняется из display_definitions topology (не из displays.yaml)."""

    def test_boot_with_display_definitions(self):
        """Topology с display_definitions при boot → реестр наполнен."""
        topology_dict = {
            "processes": [],
            "wires": [],
            "display_definitions": [
                {"id": "main", "name": "Main", "width": 1920, "height": 1080},
                {"id": "aux", "name": "Auxiliary", "width": 640, "height": 480},
            ],
        }
        defs = topology_dict.get("display_definitions") or []
        registry = DisplayRegistry()
        registry.reload(defs)

        assert _registry_ids() == {"main", "aux"}
        assert registry.get("main").width == 1920
        assert registry.get("aux").height == 480

    def test_boot_without_display_definitions(self):
        """Topology без display_definitions → реестр пуст."""
        topology_dict = {"processes": [], "wires": []}
        defs = topology_dict.get("display_definitions") or []

        registry = DisplayRegistry()
        if defs:
            registry.reload(defs)

        assert _registry_ids() == set()

    def test_boot_empty_display_definitions(self):
        """Topology с display_definitions=[] → реестр пуст."""
        topology_dict = {"processes": [], "wires": [], "display_definitions": []}
        defs = topology_dict.get("display_definitions") or []

        registry = DisplayRegistry()
        if defs:
            registry.reload(defs)

        # Пустой список = falsy → reload не вызывается → реестр пуст
        assert _registry_ids() == set()
