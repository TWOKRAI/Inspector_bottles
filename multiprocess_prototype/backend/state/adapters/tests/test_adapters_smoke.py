"""test_adapters_smoke.py — Smoke-тесты адаптеров StateStore в prototype.

Проверяют:
1. Импорты без ошибок.
2. isinstance для StateAdapterBase (для CameraStateAdapter, RegistersStateAdapter, RecipeStateAdapter).
3. Конструирование без аргументов (где применимо).
4. Нет logging.getLogger в файлах адаптеров.

Breaking change Task 5.5: RecipeAdapter (slot-based wrapper) удалён.
Тест test_recipe_adapter_not_state_adapter_base помечен skip — legacy API удалён.
RecipeStateAdapter теперь полноценный StateAdapterBase-наследник.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from multiprocess_framework.modules.state_store_module.adapters import StateAdapterBase
from multiprocess_prototype.backend.state.adapters import (
    CameraStateAdapter,
    RecipeStateAdapter,
    RegistersStateAdapter,
)


# ---------------------------------------------------------------------------
# Тест 1: импорты из пакета — всё доступно
# ---------------------------------------------------------------------------


def test_imports_available():
    """Все адаптеры импортируются из пакета без ошибок."""
    assert CameraStateAdapter is not None
    assert RegistersStateAdapter is not None
    assert RecipeStateAdapter is not None


# ---------------------------------------------------------------------------
# Тест 2: isinstance-проверки
# ---------------------------------------------------------------------------


def test_camera_adapter_is_state_adapter_base():
    """CameraStateAdapter наследует StateAdapterBase."""
    adapter = CameraStateAdapter()
    assert isinstance(adapter, StateAdapterBase), "CameraStateAdapter должен наследовать StateAdapterBase"


def test_registers_adapter_is_state_adapter_base():
    """RegistersStateAdapter наследует StateAdapterBase."""
    mock_rm = MagicMock()
    adapter = RegistersStateAdapter(registers_manager=mock_rm, path_mapping={})
    assert isinstance(adapter, StateAdapterBase), "RegistersStateAdapter должен наследовать StateAdapterBase"


def test_recipe_state_adapter_is_state_adapter_base():
    """RecipeStateAdapter наследует StateAdapterBase (Task 5.5 — breaking change)."""
    mock_rm = MagicMock()
    adapter = RecipeStateAdapter(recipe_manager=mock_rm)
    assert isinstance(adapter, StateAdapterBase), "RecipeStateAdapter должен наследовать StateAdapterBase"
    assert issubclass(RecipeStateAdapter, StateAdapterBase)


@pytest.mark.skip(reason="legacy RecipeAdapter API removed in Task 5.5 — заменён на RecipeStateAdapter")
def test_recipe_adapter_not_state_adapter_base():
    """RecipeAdapter НЕ наследует StateAdapterBase. — УДАЛЁН в Task 5.5."""
    pass


# ---------------------------------------------------------------------------
# Тест 3: конструирование без обязательных зависимостей (smoke)
# ---------------------------------------------------------------------------


def test_camera_adapter_construct_no_args():
    """CameraStateAdapter создаётся без аргументов."""
    adapter = CameraStateAdapter()
    assert adapter._num_cameras == 0
    assert adapter._proxy is None
    assert not adapter.is_bound
    assert not adapter.is_connected


def test_registers_adapter_construct_minimal():
    """RegistersStateAdapter создаётся с минимальными аргументами."""
    mock_rm = MagicMock()
    adapter = RegistersStateAdapter(registers_manager=mock_rm, path_mapping={})
    assert adapter._proxy is None
    assert not adapter.is_bound
    assert not adapter.is_connected


def test_recipe_state_adapter_construct_minimal():
    """RecipeStateAdapter создаётся с минимальными аргументами (только manager)."""
    mock_rm = MagicMock()
    adapter = RecipeStateAdapter(recipe_manager=mock_rm)
    assert adapter._proxy is None
    assert not adapter.is_bound
    assert not adapter.is_connected
    assert adapter._sub_ids == []


def test_camera_adapter_bind_unbind():
    """CameraStateAdapter корректно привязывается и отвязывается от proxy."""
    mock_proxy = MagicMock()
    adapter = CameraStateAdapter()

    adapter.bind(mock_proxy)
    assert adapter.is_bound
    assert adapter._proxy is mock_proxy

    adapter.unbind()
    assert not adapter.is_bound
    assert adapter._proxy is None


def test_registers_adapter_path_mapping():
    """RegistersStateAdapter строит обратный маппинг корректно."""
    mock_rm = MagicMock()
    mapping = {("camera", "fps"): "cameras.0.config.fps"}
    adapter = RegistersStateAdapter(registers_manager=mock_rm, path_mapping=mapping)

    assert ("camera", "fps") in adapter._path_mapping
    assert "cameras.0.config.fps" in adapter._reverse_mapping
    assert adapter._reverse_mapping["cameras.0.config.fps"] == ("camera", "fps")


# ---------------------------------------------------------------------------
# §11.6 comm-system: sync_domain_to_state читает через get_register + getattr
# ---------------------------------------------------------------------------


def test_sync_domain_to_state_reads_via_get_register():
    """sync_domain_to_state читает значения полей через get_register + getattr
    и пишет их в proxy. Раньше звался несуществующий RegistersManager.get_field
    → AttributeError молча гасился в except, синхронизация не происходила."""
    mock_rm = MagicMock()
    mock_rm.get_register.return_value = SimpleNamespace(fps=30)

    mapping = {("camera", "fps"): "cameras.0.config.fps"}
    adapter = RegistersStateAdapter(registers_manager=mock_rm, path_mapping=mapping)
    mock_proxy = MagicMock()
    adapter.bind(mock_proxy)

    adapter.sync_domain_to_state()

    mock_rm.get_register.assert_called_once_with("camera")
    mock_proxy.set.assert_called_once_with("cameras.0.config.fps", 30)


def test_sync_domain_to_state_missing_register_skips():
    """Нет регистра → пропуск без падения и без записи в proxy (§11.6)."""
    mock_rm = MagicMock()
    mock_rm.get_register.return_value = None

    mapping = {("camera", "fps"): "cameras.0.config.fps"}
    adapter = RegistersStateAdapter(registers_manager=mock_rm, path_mapping=mapping)
    mock_proxy = MagicMock()
    adapter.bind(mock_proxy)

    adapter.sync_domain_to_state()

    mock_proxy.set.assert_not_called()


# ---------------------------------------------------------------------------
# Тест 4: нет logging.getLogger в файлах адаптеров
# ---------------------------------------------------------------------------


def _check_no_getlogger(file_path: Path) -> list[str]:
    """Вернуть список строк с logging.getLogger (если найдены)."""
    source = file_path.read_text(encoding="utf-8")
    violations = [line.strip() for line in source.splitlines() if "logging.getLogger" in line]
    return violations


def test_no_getlogger_in_adapters():
    """Ни один файл адаптера не должен содержать logging.getLogger."""
    adapters_dir = Path(__file__).parent.parent
    adapter_files = [
        adapters_dir / "recipe_adapter.py",
        adapters_dir / "registers_adapter.py",
        adapters_dir / "camera_state_adapter.py",
    ]
    violations: dict[str, list[str]] = {}
    for f in adapter_files:
        found = _check_no_getlogger(f)
        if found:
            violations[f.name] = found

    assert not violations, f"Найден logging.getLogger в адаптерах: {violations}"
