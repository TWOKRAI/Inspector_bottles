"""Тесты RegisterMap — декларативная карта регистров устройства.

Проверяется на стабе RegisterTransport (без устройства и сети): кодирование
scale/signed/DW для обоих word order, чтение блоков с полями, сборка ops для
transaction с сохранением порядка (инвариант «маркер последним»).
"""

from __future__ import annotations

import pytest

from Services.modbus.core.register_map import Field, Reg, RegBlock, RegDW, RegisterMap
from Services.modbus.interfaces import RegisterTransport


class StubTransport:
    """Стаб RegisterTransport: регистры в dict + журнал транзакций."""

    def __init__(self, holding: dict[int, int] | None = None) -> None:
        self.holding: dict[int, int] = dict(holding or {})
        self.transactions: list[list[tuple]] = []

    @property
    def is_connected(self) -> bool:
        return True

    def read_registers(self, address: int, count: int = 1) -> list[int]:
        return [self.holding.get(address + i, 0) for i in range(count)]

    def transaction(self, ops: list[tuple]) -> bool:
        self.transactions.append(list(ops))
        for kind, addr, value in ops:
            if kind == "w":
                self.holding[addr] = int(value)
            else:
                for i, v in enumerate(value):
                    self.holding[addr + i] = int(v)
        return True


@pytest.fixture
def transport() -> StubTransport:
    return StubTransport()


def test_stub_satisfies_protocol(transport: StubTransport) -> None:
    assert isinstance(transport, RegisterTransport)


# --- Reg: одиночный регистр ---


def test_reg_read_raw(transport: StubTransport) -> None:
    rmap = RegisterMap({"flag": Reg(0x1100)})
    transport.holding[0x1100] = 1
    assert rmap.read(transport, "flag") == 1


def test_reg_read_scaled_signed(transport: StubTransport) -> None:
    """Координата -200.3 мм при scale=10 хранится как s16 → u16."""
    rmap = RegisterMap({"x_mm": Reg(0x1101, scale=10, signed=True)})
    transport.holding[0x1101] = (-2003) & 0xFFFF
    assert rmap.read(transport, "x_mm") == pytest.approx(-200.3)


def test_reg_write_ops_scaled_signed() -> None:
    rmap = RegisterMap({"x_mm": Reg(0x1101, scale=10, signed=True)})
    assert rmap.write_ops({"x_mm": -200.3}) == [("w", 0x1101, (-2003) & 0xFFFF)]


# --- RegDW: 32 бита ---


@pytest.mark.parametrize(
    ("word_order", "regs"),
    [("big", [0x0012, 0xD687]), ("little", [0xD687, 0x0012])],
)
def test_regdw_roundtrip_word_orders(transport: StubTransport, word_order: str, regs: list[int]) -> None:
    """Энкодер 1234567 = 0x0012D687 — оба порядка слов."""
    rmap = RegisterMap({"encoder": RegDW(0x1112)}, word_order=word_order)  # type: ignore[arg-type]
    transport.holding[0x1112], transport.holding[0x1113] = regs
    assert rmap.read(transport, "encoder") == 1234567
    assert rmap.write_ops({"encoder": 1234567}) == [("wm", 0x1112, regs)]


def test_regdw_negative_signed(transport: StubTransport) -> None:
    rmap = RegisterMap({"ecap": RegDW(0x1104, signed=True)}, word_order="little")
    ops = rmap.write_ops({"ecap": -5})
    transport.transaction(ops)
    assert rmap.read(transport, "ecap") == -5


# --- RegBlock: блок с полями ---


def test_block_with_fields_reads_dict(transport: StubTransport) -> None:
    """Зеркало ПЧ: running raw, частота ×100, ток ×10."""
    rmap = RegisterMap(
        {
            "vfd_status": RegBlock(
                0x1210,
                fields=(
                    Field("running"),
                    Field("out_freq_hz", scale=100),
                    Field("current_a", scale=10),
                ),
            )
        }
    )
    transport.holding.update({0x1210: 1, 0x1211: 5000, 0x1212: 150})
    assert rmap.read(transport, "vfd_status") == {
        "running": 1,
        "out_freq_hz": 50.0,
        "current_a": 15.0,
    }


def test_block_without_fields_reads_raw_list(transport: StubTransport) -> None:
    rmap = RegisterMap({"echo": RegBlock(0x1120, count=3)})
    transport.holding.update({0x1120: 7, 0x1121: 8, 0x1122: 9})
    assert rmap.read(transport, "echo") == [7, 8, 9]


def test_block_count_derived_from_fields() -> None:
    block = RegBlock(0x1300, fields=(Field("a"), Field("b")))
    assert block.count == 2


def test_block_requires_count_or_fields() -> None:
    with pytest.raises(ValueError, match="count или fields"):
        RegBlock(0x1000)


def test_block_write_ops_from_dict_and_list() -> None:
    rmap = RegisterMap({"cfg": RegBlock(0x1301, fields=(Field("speed"), Field("home_x", scale=10, signed=True)))})
    assert rmap.write_ops({"cfg": {"speed": 50, "home_x": -1.5}}) == [("wm", 0x1301, [50, (-15) & 0xFFFF])]
    assert rmap.write_ops({"cfg": [50, -1.5]}) == [("wm", 0x1301, [50, (-15) & 0xFFFF])]


def test_block_write_missing_field_raises() -> None:
    rmap = RegisterMap({"cfg": RegBlock(0x1301, fields=(Field("speed"), Field("home_x")))})
    with pytest.raises(ValueError, match="не заданы поля"):
        rmap.write_ops({"cfg": {"speed": 50}})


# --- порядок ops и интеграция с transaction ---


def test_write_ops_preserves_order_marker_last(transport: StubTransport) -> None:
    """Инвариант mailbox: порядок ключей values = порядок ops, маркер последним."""
    rmap = RegisterMap(
        {
            "freq": Reg(0x1202, scale=100),
            "dir": Reg(0x1201),
            "run": Reg(0x1200),
            "flag": Reg(0x1204),
        }
    )
    ops = rmap.write_ops({"freq": 50.0, "dir": 0, "run": 1, "flag": 1})
    assert [op[1] for op in ops] == [0x1202, 0x1201, 0x1200, 0x1204]
    transport.transaction(ops)
    assert transport.holding[0x1202] == 5000
    assert transport.holding[0x1204] == 1


def test_unknown_name_raises_with_hint() -> None:
    rmap = RegisterMap({"flag": Reg(0x1100)})
    with pytest.raises(KeyError, match="отсутствует в карте"):
        rmap.read(StubTransport(), "flagg")


def test_invalid_word_order_rejected() -> None:
    with pytest.raises(ValueError, match="word_order"):
        RegisterMap({}, word_order="middle")  # type: ignore[arg-type]
