# -*- coding: utf-8 -*-
"""Тесты типотерпимой сверки verify-probe (живая находка 2026-07-22).

MCP-клиент коэрсил value без типа в схеме в строку («0.15»), приёмник применял
запись (регистр коэрсит обратно в float), а strict ``==`` в verify давал ЛОЖНЫЙ
провал — инструмент врал «не записалось» при реально применённой записи.
"""

from __future__ import annotations

from backend_ctl.registers import RegisterOps


class TestValuesMatch:
    def test_exact_equality(self) -> None:
        assert RegisterOps._values_match(0.15, 0.15) is True
        assert RegisterOps._values_match("abc", "abc") is True
        assert RegisterOps._values_match(1, 1.0) is True  # питоновское ==

    def test_string_number_coercion(self) -> None:
        """Ядро находки: «0.15» (строка от MCP-клиента) против 0.15 (readback)."""
        assert RegisterOps._values_match("0.15", 0.15) is True
        assert RegisterOps._values_match(0.15, "0.15") is True
        assert RegisterOps._values_match("7", 7) is True

    def test_string_bool_coercion(self) -> None:
        assert RegisterOps._values_match("true", True) is True
        assert RegisterOps._values_match("False", False) is True
        assert RegisterOps._values_match("true", False) is False

    def test_real_mismatches_stay_mismatches(self) -> None:
        """Терпимость не превращается в слепоту: реальные расхождения — провал."""
        assert RegisterOps._values_match("0.15", 0.2) is False
        assert RegisterOps._values_match("abc", 0.15) is False
        assert RegisterOps._values_match(None, 0.15) is False
        assert RegisterOps._values_match("1", True) is False  # строка-число ≠ буль
        assert RegisterOps._values_match({"a": 1}, '{"a": 1}') is False
