"""Контракт ``Port.join`` / ``Port.effective_join`` (plans/topology-port-join.md, Task C16.1, A1 + A3).

Слепые приёмочные тесты (написаны до реализации). Ожидаемые значения — литералы из плана.

Контракт (из плана, DESIGN 1):
- ``Port.join: bool | None`` — участвует ли подключённый вход в join; ``None`` = «как not optional».
- ``Port.effective_join`` = ``join``, если задан, иначе ``not optional``.
- ``model_dump()`` несёт ключ ``join``; ``model_validate`` его читает; dict без ``join`` даёт ``None``.

Порт строится ВНУТРИ тела теста: до реализации поля ``Port(join=...)`` молча отбрасывает
неизвестный kwarg, а ``effective_join`` нет — тест обязан упасть на утверждении, а не при сборе.
"""

from __future__ import annotations

import pytest

from multiprocess_framework.modules.process_module.plugins.port import Port


# ---------------------------------------------------------------------------
# A1. Таблица (optional, join) -> effective_join
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("optional", "join", "expected"),
    [
        (False, None, True),
        (True, None, False),
        (True, True, True),
        (False, False, False),
        (False, True, True),
        (True, False, False),
    ],
)
def test_effective_join_table(optional: bool, join: bool | None, expected: bool) -> None:
    """A1: effective_join для каждой из шести комбинаций (optional, join)."""
    port = Port(name="p", optional=optional, join=join)
    assert port.effective_join is expected


def test_join_defaults_to_none() -> None:
    """Умолчание ``join`` — ``None`` (решение владельца 2): нынешние плагины не меняются."""
    port = Port(name="p")
    assert port.join is None
    assert port.effective_join is True  # обязательный вход по умолчанию участвует в join


def test_join_none_on_optional_port_does_not_join() -> None:
    """Optional-вход без явного join (все нынешние плагины) в join не участвует."""
    port = Port(name="p", optional=True)
    assert port.join is None
    assert port.effective_join is False


# ---------------------------------------------------------------------------
# A3. Сериализация
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("value", [True, False, None])
def test_join_round_trips_through_model_dump(value: bool | None) -> None:
    """A3: ``Port.model_validate(Port(name="o", join=X).model_dump()).join == X``."""
    restored = Port.model_validate(Port(name="o", join=value).model_dump())
    assert restored.join is value


def test_model_dump_carries_join_key() -> None:
    """A3: ``model_dump()`` несёт ключ ``join`` (значение выставленного поля)."""
    dumped = Port(name="o", join=True).model_dump()
    assert "join" in dumped
    assert dumped["join"] is True


def test_model_validate_dict_without_join_gives_none() -> None:
    """A3: dict без ``join`` (старые снимки/каталоги) читается как ``None``."""
    assert Port.model_validate({"name": "o"}).join is None


def test_round_trip_keeps_effective_join_of_optional_join_true() -> None:
    """Наблюдаемый эффект round-trip: optional+join=True остаётся участником join после dump/validate."""
    restored = Port.model_validate(Port(name="overlay", optional=True, join=True).model_dump())
    assert restored.optional is True
    assert restored.effective_join is True
