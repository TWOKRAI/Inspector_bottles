"""Авторские проверки формы delta_v2.yaml, которых нет в независимом наборе.

Опасности, которые закрывают: раскладка аргументов опкода расходится с argc (sim, клиент и прошивка
читают её из YAML — ошибка размножится в три стороны); DW-аргумент не на чётном слоте; параметр
тихо выходит за слово W без пометки; ПК открыт на запись зеркала в обход PARAM_SET.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

_DOC = yaml.safe_load(
    (Path(__file__).resolve().parents[1] / "protocols" / "delta_v2.yaml").read_text(encoding="utf-8")
)
_ARG_TYPES = {"s16", "u16", "raw", "dw_lo", "dw_hi"}


@pytest.mark.parametrize("op", sorted(_DOC["opcodes"]))
def test_opcode_args_match_argc_and_dw_on_even_slot(op: str) -> None:
    row = _DOC["opcodes"][op]
    args = row["args"]
    assert len(args) == row["argc"]
    assert row["result"] in {"instant", "rvals", "done_seq"}
    types = [a["type"] for a in args]
    assert set(types) <= _ARG_TYPES
    for i, t in enumerate(types):
        if t == "dw_lo":
            assert i % 2 == 0 and types[i + 1] == "dw_hi", f"{op}: DW не на чётном слоте ARG{i}"


def test_params_outside_word_range_are_flagged() -> None:
    # Выход за ±32767 допустим только с видимой пометкой «⚠» — вопрос владельцу, а не молчаливый выбор
    for name, row in _DOC["params"].items():
        if not (-32767 <= row["min"] and row["max"] <= 32767):
            assert "⚠" in row["info"], name


def test_every_param_group_has_a_label() -> None:
    assert {row["group"] for row in _DOC["params"].values()} <= set(_DOC["groups"])


def test_mirror_is_read_only_for_pc() -> None:
    for name in ("pmir", "pmir_magic", "pmir_crc", "pmir_dict"):
        assert _DOC["registers"][name]["access"] == "r", name
