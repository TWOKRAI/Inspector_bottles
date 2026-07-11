"""Тесты validate_items_against_ports / validate_chain (plugins/port.py).

Покрытие (Ф4.3, C-4):
- validate_items_against_ports: обязательный порт отсутствует в item -> PortValidationError
  с именем плагина/порта/direction в тексте; optional-порт пропускается; пустой items — не ошибка.
- validate_chain: несовместимая линейная цепочка -> детальная ошибка (ранее 0 покрывающих тестов).
"""

from __future__ import annotations

import pytest

from multiprocess_framework.modules.process_module.plugins.port import (
    Port,
    PortValidationError,
    validate_chain,
    validate_items_against_ports,
)


# ---------------------------------------------------------------------------
#  validate_items_against_ports
# ---------------------------------------------------------------------------


def test_missing_required_output_field_raises():
    ports = [Port(name="mask", dtype="image/gray", shape="(H, W, 1)")]
    items = [{"frame": 1}]  # нет поля "mask"

    with pytest.raises(PortValidationError) as exc_info:
        validate_items_against_ports("color_mask", "output", ports, items)

    msg = str(exc_info.value)
    assert "color_mask" in msg
    assert "mask" in msg
    assert "output" in msg


def test_present_required_field_ok():
    ports = [Port(name="mask", dtype="image/gray")]
    items = [{"mask": object()}]
    validate_items_against_ports("color_mask", "output", ports, items)  # не бросает


def test_optional_port_missing_field_ok():
    ports = [Port(name="stats", dtype="dict", optional=True)]
    items = [{"frame": 1}]  # нет "stats", но порт optional
    validate_items_against_ports("stats_collector", "output", ports, items)  # не бросает


def test_empty_items_not_an_error():
    ports = [Port(name="mask", dtype="image/gray")]
    validate_items_against_ports("detector", "output", ports, [])  # не бросает


def test_second_item_missing_field_raises():
    ports = [Port(name="frame", dtype="image/bgr")]
    items = [{"frame": 1}, {"other": 2}]

    with pytest.raises(PortValidationError) as exc_info:
        validate_items_against_ports("passthrough", "input", ports, items)
    assert "item[1]" in str(exc_info.value)


# ---------------------------------------------------------------------------
#  validate_chain (C-4: ранее 0 прод-вызовов)
# ---------------------------------------------------------------------------


def test_validate_chain_incompatible_dtype_reports_error():
    chain = [
        ("source", [], [Port(name="frame", dtype="image/gray", shape="(H, W, 1)")]),
        (
            "needs_bgr",
            [Port(name="frame", dtype="image/bgr", shape="(H, W, 3)")],
            [],
        ),
    ]
    errors = validate_chain(chain)
    assert len(errors) == 1
    assert "source" in errors[0] and "needs_bgr" in errors[0]


def test_validate_chain_compatible_chain_no_errors():
    chain = [
        ("source", [], [Port(name="frame", dtype="image/bgr", shape="(H, W, 3)")]),
        (
            "consumer",
            [Port(name="frame", dtype="image/bgr", shape="(H, W, 3)")],
            [],
        ),
    ]
    assert validate_chain(chain) == []


def test_validate_chain_optional_input_never_errors():
    chain = [
        ("source", [], [Port(name="frame", dtype="image/bgr")]),
        (
            "consumer",
            [Port(name="mask", dtype="image/gray", optional=True)],
            [],
        ),
    ]
    assert validate_chain(chain) == []
