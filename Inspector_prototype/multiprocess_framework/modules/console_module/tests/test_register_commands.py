"""
Тесты для RegisterCommandHandler.

pytest -q Inspector_prototype/multiprocess_framework/modules/console_module/tests/
"""
from unittest.mock import MagicMock

import pytest

from ..commands.register_commands import RegisterCommandHandler


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_handler(registers_manager=None, router_manager=None):
    return RegisterCommandHandler(
        registers_manager=registers_manager,
        router_manager=router_manager,
    )


def _msg(args):
    """Сформировать минимальный message dict для handle()."""
    return {"command": "reg", "args": args, "source": "console"}


def _make_registers_manager(register_names, registers=None):
    """Создать mock registers_manager с заданными именами и регистрами."""
    mgr = MagicMock()
    mgr.register_names.return_value = register_names
    if registers is not None:
        mgr.get_register.side_effect = lambda name: registers.get(name)
    return mgr


# ---------------------------------------------------------------------------
# reg list
# ---------------------------------------------------------------------------

class TestRegList:
    def test_reg_list_with_registers(self):
        """Вывод содержит имена двух регистров."""
        reg_alpha = MagicMock()
        reg_alpha.model_fields = {"speed": None, "enabled": None}
        reg_beta = MagicMock()
        reg_beta.model_fields = {"count": None}

        mgr = _make_registers_manager(
            ["alpha", "beta"],
            {"alpha": reg_alpha, "beta": reg_beta},
        )
        handler = _make_handler(registers_manager=mgr)

        result = handler.handle(_msg(["list"]))

        assert "alpha" in result
        assert "beta" in result
        assert "Registers:" in result

    def test_reg_list_empty(self):
        """Пустой список регистров."""
        mgr = _make_registers_manager([], {})
        handler = _make_handler(registers_manager=mgr)

        result = handler.handle(_msg(["list"]))

        assert "No registers" in result

    def test_reg_list_no_manager(self):
        """registers_manager=None — graceful fallback."""
        handler = _make_handler(registers_manager=None)

        result = handler.handle(_msg(["list"]))

        assert "not available" in result.lower()

    def test_reg_list_shows_field_count(self):
        """Вывод содержит количество полей регистра."""
        reg = MagicMock()
        reg.model_fields = {"a": None, "b": None, "c": None}

        mgr = _make_registers_manager(["myreg"], {"myreg": reg})
        handler = _make_handler(registers_manager=mgr)

        result = handler.handle(_msg(["list"]))

        assert "3 fields" in result


# ---------------------------------------------------------------------------
# reg get
# ---------------------------------------------------------------------------

class TestRegGet:
    def test_reg_get_shows_fields(self):
        """Вывод содержит имена полей и значения регистра."""
        reg = MagicMock()
        reg.model_dump.return_value = {"speed": 42, "enabled": True}

        mgr = _make_registers_manager(["conveyor"], {"conveyor": reg})
        handler = _make_handler(registers_manager=mgr)

        result = handler.handle(_msg(["get", "conveyor"]))

        assert "speed" in result
        assert "enabled" in result
        assert "conveyor" in result

    def test_reg_get_unknown_register(self):
        """Несуществующий регистр — сообщение об ошибке."""
        mgr = _make_registers_manager(["real_reg"])
        mgr.get_register.return_value = None
        handler = _make_handler(registers_manager=mgr)

        result = handler.handle(_msg(["get", "ghost"]))

        assert "not found" in result.lower()

    def test_reg_get_no_args(self):
        """reg get без имени — показывает usage."""
        mgr = _make_registers_manager([])
        handler = _make_handler(registers_manager=mgr)

        result = handler.handle(_msg(["get"]))

        assert "Usage" in result

    def test_reg_get_no_manager(self):
        """registers_manager=None — graceful fallback."""
        handler = _make_handler(registers_manager=None)

        result = handler.handle(_msg(["get", "any"]))

        assert "not available" in result.lower()


# ---------------------------------------------------------------------------
# reg set
# ---------------------------------------------------------------------------

class TestRegSet:
    def test_reg_set_changes_field(self):
        """Метод set_field_value вызван с правильными аргументами."""
        reg = MagicMock()
        reg.speed = 10  # текущее значение для определения типа

        mgr = _make_registers_manager(["conveyor"], {"conveyor": reg})
        mgr.set_field_value.return_value = (True, None)
        handler = _make_handler(registers_manager=mgr)

        result = handler.handle(_msg(["set", "conveyor.speed", "99"]))

        mgr.set_field_value.assert_called_once_with("conveyor", "speed", 99)
        assert "OK" in result

    def test_reg_set_invalid_format(self):
        """Цель без точки — сообщение об ошибке."""
        mgr = _make_registers_manager([])
        handler = _make_handler(registers_manager=mgr)

        result = handler.handle(_msg(["set", "conveyor_speed", "99"]))

        assert "Invalid target" in result or "Expected format" in result

    def test_reg_set_invalid_value(self):
        """set_field_value возвращает ошибку — graceful error."""
        reg = MagicMock()
        reg.speed = 10

        mgr = _make_registers_manager(["conveyor"], {"conveyor": reg})
        mgr.set_field_value.return_value = (False, "value out of range")
        handler = _make_handler(registers_manager=mgr)

        result = handler.handle(_msg(["set", "conveyor.speed", "9999"]))

        assert "Failed" in result or "error" in result.lower()
        assert "value out of range" in result

    def test_reg_set_unknown_field(self):
        """Поле не существует в регистре — сообщение об ошибке."""
        reg = MagicMock(spec=[])  # без атрибутов
        mgr = _make_registers_manager(["conveyor"], {"conveyor": reg})
        handler = _make_handler(registers_manager=mgr)

        result = handler.handle(_msg(["set", "conveyor.ghost_field", "1"]))

        assert "not found" in result.lower()

    def test_reg_set_no_manager(self):
        """registers_manager=None — graceful fallback."""
        handler = _make_handler(registers_manager=None)

        result = handler.handle(_msg(["set", "conveyor.speed", "5"]))

        assert "not available" in result.lower()


# ---------------------------------------------------------------------------
# reg info
# ---------------------------------------------------------------------------

class TestRegInfo:
    def test_reg_info_shows_metadata(self):
        """Вывод содержит имя поля и его метаданные."""
        reg = MagicMock()
        reg.model_fields = {"speed": None}

        mgr = _make_registers_manager(["conveyor"], {"conveyor": reg})
        mgr.get_field_metadata.return_value = {
            "description": "Conveyor belt speed",
            "unit": "rpm",
        }
        handler = _make_handler(registers_manager=mgr)

        result = handler.handle(_msg(["info", "conveyor"]))

        assert "conveyor" in result
        assert "speed" in result
        assert "description" in result or "rpm" in result

    def test_reg_info_unknown_register(self):
        """Несуществующий регистр — сообщение об ошибке."""
        mgr = _make_registers_manager(["real_reg"])
        mgr.get_register.return_value = None
        handler = _make_handler(registers_manager=mgr)

        result = handler.handle(_msg(["info", "ghost"]))

        assert "not found" in result.lower()

    def test_reg_info_no_manager(self):
        """registers_manager=None — graceful fallback."""
        handler = _make_handler(registers_manager=None)

        result = handler.handle(_msg(["info", "any"]))

        assert "not available" in result.lower()


# ---------------------------------------------------------------------------
# help и неизвестные подкоманды
# ---------------------------------------------------------------------------

class TestHelpAndUnknown:
    def test_reg_no_args_shows_help(self):
        """Вызов без аргументов возвращает справку."""
        handler = _make_handler()

        result = handler.handle(_msg([]))

        assert "reg list" in result
        assert "reg get" in result

    def test_reg_help_subcommand(self):
        """reg help — явный вызов справки."""
        handler = _make_handler()

        result = handler.handle(_msg(["help"]))

        assert "reg list" in result
        assert "reg set" in result
        assert "reg info" in result

    def test_reg_unknown_subcommand(self):
        """Неизвестная подкоманда — сообщение + help."""
        handler = _make_handler()

        result = handler.handle(_msg(["xyzzy"]))

        assert "Unknown subcommand" in result
        assert "xyzzy" in result
        # Также показывается справка
        assert "reg list" in result


# ---------------------------------------------------------------------------
# Позднее связывание
# ---------------------------------------------------------------------------

class TestLateBinding:
    def test_set_registers_manager_after_init(self):
        """set_registers_manager позволяет подключить менеджер после создания."""
        handler = _make_handler(registers_manager=None)

        mgr = _make_registers_manager([], {})
        handler.set_registers_manager(mgr)

        result = handler.handle(_msg(["list"]))

        assert "No registers" in result  # менеджер подключён, но пуст

    def test_set_router_manager_after_init(self):
        """set_router_manager сохраняет объект в _router."""
        handler = _make_handler()
        router = MagicMock()

        handler.set_router_manager(router)

        assert handler._router is router


# ---------------------------------------------------------------------------
# _cast_value
# ---------------------------------------------------------------------------

class TestCastValue:
    def test_cast_bool_true(self):
        assert RegisterCommandHandler._cast_value("true", False) is True
        assert RegisterCommandHandler._cast_value("1", False) is True
        assert RegisterCommandHandler._cast_value("yes", False) is True

    def test_cast_bool_false(self):
        assert RegisterCommandHandler._cast_value("false", True) is False
        assert RegisterCommandHandler._cast_value("0", True) is False

    def test_cast_int(self):
        assert RegisterCommandHandler._cast_value("42", 0) == 42

    def test_cast_float(self):
        assert RegisterCommandHandler._cast_value("3.14", 0.0) == pytest.approx(3.14)

    def test_cast_str_passthrough(self):
        assert RegisterCommandHandler._cast_value("hello", "world") == "hello"

    def test_cast_int_from_float_string(self):
        """'3.0' должно приводиться к 3 когда тип int."""
        assert RegisterCommandHandler._cast_value("3.0", 0) == 3
