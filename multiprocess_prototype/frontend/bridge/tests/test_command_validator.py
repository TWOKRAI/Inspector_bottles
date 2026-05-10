"""Тесты CommandValidator — валидация IPC-команд.

Pure Python, без Qt. Тестируем:
- validate_field_command: happy path, несуществующий плагин, невалидное поле, невалидное значение
- validate_action_command: happy path, несуществующая команда
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from multiprocess_prototype.frontend.bridge.command_validator import (
    CommandValidator,
    ValidationResult,
)


# --- Mock-объекты ---


@dataclass
class MockPluginCommands:
    plugin_name: str
    process_name: str
    commands: dict[str, str] = field(default_factory=dict)
    has_commands: bool = True


@dataclass
class MockResolvedCommand:
    process_name: str
    command_name: str
    plugin_name: str


@dataclass
class MockFieldInfo:
    name: str


class MockCatalog:
    """Мок CommandCatalog — реализует ICommandCatalog Protocol."""

    def __init__(self, plugins: dict[str, MockPluginCommands]) -> None:
        self._plugins = plugins

    def get_plugin(self, plugin_name: str) -> MockPluginCommands | None:
        return self._plugins.get(plugin_name)

    def resolve_action_command(
        self, plugin_name: str, command_name: str
    ) -> MockResolvedCommand | None:
        pc = self._plugins.get(plugin_name)
        if pc is None or command_name not in pc.commands:
            return None
        return MockResolvedCommand(
            process_name=pc.process_name,
            command_name=command_name,
            plugin_name=plugin_name,
        )


class MockRegistersManager:
    """Мок RegistersManager — реализует IRegistersManager Protocol."""

    def __init__(
        self,
        fields: dict[str, list[str]],
        valid_values: dict[str, dict[str, set]] | None = None,
    ) -> None:
        self._fields = fields  # plugin_name → [field_name, ...]
        self._valid = valid_values or {}  # plugin_name → {field: {valid_vals}}

    def get_fields(self, plugin_name: str) -> list[MockFieldInfo]:
        return [MockFieldInfo(name=n) for n in self._fields.get(plugin_name, [])]

    def validate(
        self, plugin_name: str, field_name: str, value: Any
    ) -> tuple[bool, str | None]:
        valid_set = self._valid.get(plugin_name, {}).get(field_name)
        if valid_set is not None and value not in valid_set:
            return False, f"значение {value} не в допустимом диапазоне"
        return True, None


# --- Fixtures ---


@pytest.fixture
def catalog() -> MockCatalog:
    return MockCatalog({
        "color_mask": MockPluginCommands(
            plugin_name="color_mask",
            process_name="processor_0",
            commands={"set_hsv_range": "set_hsv_range"},
        ),
        "capture": MockPluginCommands(
            plugin_name="capture",
            process_name="camera_0",
            commands={"start_capture": "cmd_start", "stop_capture": "cmd_stop"},
        ),
        "grayscale": MockPluginCommands(
            plugin_name="grayscale",
            process_name="processor_0",
            commands={},
            has_commands=False,
        ),
    })


@pytest.fixture
def rm() -> MockRegistersManager:
    return MockRegistersManager(
        fields={
            "color_mask": ["h_min", "h_max", "s_min"],
        },
        valid_values={
            "color_mask": {"h_min": {0, 10, 50, 100, 180}},
        },
    )


@pytest.fixture
def validator(catalog: MockCatalog, rm: MockRegistersManager) -> CommandValidator:
    return CommandValidator(catalog, rm)


# --- Тесты validate_field_command ---


class TestValidateFieldCommand:

    def test_valid_field(self, validator: CommandValidator) -> None:
        """Happy path: плагин есть, поле есть, значение валидно."""
        result = validator.validate_field_command("color_mask", "h_min", 50)
        assert result.ok is True
        assert result.error is None

    def test_nonexistent_plugin(self, validator: CommandValidator) -> None:
        """Плагин не найден в каталоге."""
        result = validator.validate_field_command("nonexistent", "field", 1)
        assert result.ok is False
        assert "не найден" in result.error

    def test_nonexistent_field(self, validator: CommandValidator) -> None:
        """Поле не существует у плагина."""
        result = validator.validate_field_command("color_mask", "unknown_field", 1)
        assert result.ok is False
        assert "не найдено" in result.error

    def test_invalid_value(self, validator: CommandValidator) -> None:
        """Значение не проходит валидацию."""
        result = validator.validate_field_command("color_mask", "h_min", 999)
        assert result.ok is False
        assert "Невалидное" in result.error

    def test_plugin_without_registers(self, validator: CommandValidator) -> None:
        """Плагин есть в каталоге, но нет полей в RegistersManager."""
        result = validator.validate_field_command("capture", "some_field", 1)
        assert result.ok is False
        assert "не найдено" in result.error

    def test_field_without_validation_constraints(self, validator: CommandValidator) -> None:
        """Поле есть, ограничений на значение нет → ok."""
        result = validator.validate_field_command("color_mask", "h_max", 999)
        assert result.ok is True


# --- Тесты validate_action_command ---


class TestValidateActionCommand:

    def test_valid_action(self, validator: CommandValidator) -> None:
        """Команда существует у плагина."""
        result = validator.validate_action_command("capture", "start_capture")
        assert result.ok is True

    def test_nonexistent_action(self, validator: CommandValidator) -> None:
        """Команда не существует."""
        result = validator.validate_action_command("capture", "nonexistent_cmd")
        assert result.ok is False
        assert "не найдена" in result.error

    def test_nonexistent_plugin_action(self, validator: CommandValidator) -> None:
        """Плагин не найден."""
        result = validator.validate_action_command("nonexistent", "start")
        assert result.ok is False
        assert "не найден" in result.error


# --- Тесты ValidationResult ---


class TestValidationResult:

    def test_success_factory(self) -> None:
        r = ValidationResult.success()
        assert r.ok is True
        assert r.error is None

    def test_fail_factory(self) -> None:
        r = ValidationResult.fail("что-то пошло не так")
        assert r.ok is False
        assert r.error == "что-то пошло не так"
