"""
Unit-тесты для registers_io.

Сценарии:
- Экспорт/импорт в dict, JSON, YAML (round-trip).
- Плоский словарь (to_flat_dict / from_flat_dict) для рецептов.
- Используется заглушка FakeRegisters с model_dump_all/model_validate_all.
"""

from typing import Any, Dict

import pytest

from ..serialization.io import (
    registers_to_dict,
    registers_from_dict,
    registers_to_json,
    registers_from_json,
    registers_to_yaml,
    registers_from_yaml,
    registers_to_flat_dict,
    registers_from_flat_dict,
)


class FakeRegisters:
    """Минимальный объект с model_dump_all и model_validate_all."""

    def __init__(self) -> None:
        self.data: Dict[str, Dict[str, Any]] = {"a": {"x": 1}, "b": {"y": 2}}

    def model_dump_all(self) -> Dict[str, Any]:
        return self.data

    def model_validate_all(self, data: Dict[str, Any]) -> None:
        self.data = dict(data)


def _factory() -> FakeRegisters:
    return FakeRegisters()


def test_registers_to_dict():
    """Экспорт: model_dump_all() у объекта-регистров возвращает вложенный dict."""
    r = FakeRegisters()
    d = registers_to_dict(r)
    assert d == {"a": {"x": 1}, "b": {"y": 2}}


def test_registers_from_dict():
    """Импорт: фабрика создаёт экземпляр, model_validate_all(data) заполняет регистры."""
    data = {"a": {"x": 10}, "b": {"y": 20}}
    r = registers_from_dict(data, _factory)
    assert r.model_dump_all() == data


def test_registers_to_json_and_from_json():
    """Round-trip: объект → JSON строка → объект; данные совпадают."""
    r = FakeRegisters()
    js = registers_to_json(r, indent=0)
    assert '"a"' in js and '"x": 1' in js
    r2 = registers_from_json(js, _factory)
    assert r2.model_dump_all() == r.model_dump_all()


def test_registers_to_yaml_and_from_yaml():
    """Round-trip: объект → YAML строка → объект (требует pyyaml)."""
    pytest.importorskip("yaml")
    r = FakeRegisters()
    yaml_str = registers_to_yaml(r)
    assert "a:" in yaml_str or "x:" in yaml_str
    r2 = registers_from_yaml(yaml_str, _factory)
    assert r2.model_dump_all() == r.model_dump_all()


def test_registers_to_flat_dict():
    """Плоский словарь: ключи вида register.field; опциональный prefix."""
    r = FakeRegisters()
    flat = registers_to_flat_dict(r)
    assert flat["a.x"] == 1
    assert flat["b.y"] == 2
    flat_prefixed = registers_to_flat_dict(r, prefix="p")
    assert flat_prefixed["p.a.x"] == 1


def test_registers_from_flat_dict():
    """Восстановление вложенной структуры из плоских ключей register.field."""
    flat = {"a.x": 1, "a.z": 3, "b.y": 2}
    r = registers_from_flat_dict(flat, _factory)
    assert r.model_dump_all() == {"a": {"x": 1, "z": 3}, "b": {"y": 2}}
