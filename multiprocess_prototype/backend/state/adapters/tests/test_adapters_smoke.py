"""test_adapters_smoke.py — Smoke-тесты адаптеров StateStore в prototype.

Проверяют:
1. Импорты без ошибок.
2. isinstance для StateAdapterBase (для CameraStateAdapter и RegistersStateAdapter).
3. RecipeAdapter НЕ наследует StateAdapterBase.
4. Конструирование без аргументов (где применимо).
5. Нет logging.getLogger в файлах адаптеров.

Комплексное тестирование с реальным StateProxy отложено до Phase 3 bootstrap.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock


from multiprocess_framework.modules.state_store_module.adapters import StateAdapterBase
from multiprocess_prototype.backend.state.adapters import (
    CameraStateAdapter,
    RecipeAdapter,
    RegistersStateAdapter,
)


# ---------------------------------------------------------------------------
# Тест 1: импорты из пакета — всё доступно
# ---------------------------------------------------------------------------


def test_imports_available():
    """Все три адаптера импортируются из пакета без ошибок."""
    assert CameraStateAdapter is not None
    assert RegistersStateAdapter is not None
    assert RecipeAdapter is not None


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


def test_recipe_adapter_not_state_adapter_base():
    """RecipeAdapter НЕ наследует StateAdapterBase."""
    assert not issubclass(RecipeAdapter, StateAdapterBase), (
        "RecipeAdapter не должен наследовать StateAdapterBase (это утилитный wrapper)"
    )


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
