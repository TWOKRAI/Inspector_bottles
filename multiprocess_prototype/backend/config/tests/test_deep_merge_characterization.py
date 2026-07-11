"""
Характеризационные тесты для ``schemas._deep_merge`` (C5 / дубль D3).

Пиннят наблюдаемый ``==``-контракт ДО консолидации в канонический
``deep_merge`` (data_schema_module). Проверяется поведение, которое обязано
сохраниться после превращения ``_deep_merge`` в тонкий делегат:

- приоритет override над base;
- рекурсивный merge вложенных dict;
- None из override перезаписывает значение;
- списки заменяются целиком;
- dict заменяет скаляр и наоборот;
- пустой override возвращает эквивалент base;
- аргументы (base) не мутируются на верхнем уровне.

СОЗНАТЕЛЬНО НЕ проверяется изоляция вложенных объектов: текущая реализация
делает ``dict(base)`` (shallow) и разделяет вложенные ссылки — это поглощаемое
консолидацией различие (канон делает deepcopy).
"""

from multiprocess_prototype.backend.config.schemas import _deep_merge


def test_override_wins_over_base():
    result = _deep_merge({"a": 1, "b": 2}, {"b": 20, "c": 3})
    assert result == {"a": 1, "b": 20, "c": 3}


def test_deep_nested_merge():
    base = {"db": {"host": "localhost", "port": 5432}}
    override = {"db": {"port": 3306}, "debug": True}
    result = _deep_merge(base, override)
    assert result == {"db": {"host": "localhost", "port": 3306}, "debug": True}


def test_none_override_replaces():
    result = _deep_merge({"a": 1}, {"a": None})
    assert result == {"a": None}


def test_list_replaced_not_merged():
    result = _deep_merge({"tags": ["a", "b"]}, {"tags": ["c"]})
    assert result == {"tags": ["c"]}


def test_dict_replaces_scalar():
    result = _deep_merge({"a": "string"}, {"a": {"nested": True}})
    assert result == {"a": {"nested": True}}


def test_scalar_replaces_dict():
    result = _deep_merge({"a": {"nested": True}}, {"a": "string"})
    assert result == {"a": "string"}


def test_empty_override_returns_base_equivalent():
    base = {"a": 1, "b": {"c": 2}}
    result = _deep_merge(base, {})
    assert result == base


def test_base_not_mutated_top_level():
    base = {"a": 1}
    _deep_merge(base, {"b": 2})
    assert base == {"a": 1}
