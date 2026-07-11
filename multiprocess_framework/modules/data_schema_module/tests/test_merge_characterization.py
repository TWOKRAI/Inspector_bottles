"""
Характеризационные тесты для ``merge_with_defaults`` (C5 / дубль D3).

Пиннят наблюдаемый ``==``-контракт ДО консолидации в канонический
``deep_merge``. Проверяется поведение, которое обязано сохраниться после
превращения ``merge_with_defaults`` в тонкий делегат:

- приоритет data над defaults;
- рекурсивный merge вложенных dict (deep=True);
- shallow-обновление верхнего уровня (deep=False);
- None из data перезаписывает значение;
- списки заменяются целиком (не мержатся поэлементно);
- dict заменяет скаляр и наоборот;
- пустой data возвращает эквивалент defaults;
- верхнеуровневый defaults не мутируется.

СОЗНАТЕЛЬНО НЕ проверяется изоляция вложенных объектов (nested aliasing):
текущая реализация делает shallow-copy и разделяет вложенные ссылки с
источником — это и есть поглощаемое консолидацией различие (канон делает
deepcopy). См. ADR в data_schema_module/DECISIONS.md.
"""

from ..core.helpers import merge_with_defaults


def test_data_wins_over_defaults():
    result = merge_with_defaults({"a": 1, "b": 2}, {"b": 20, "c": 3})
    assert result == {"a": 1, "b": 2, "c": 3}


def test_deep_nested_merge():
    data = {"db": {"port": 3306}, "debug": True}
    defaults = {"db": {"host": "localhost", "port": 5432}}
    result = merge_with_defaults(data, defaults)
    assert result == {"db": {"host": "localhost", "port": 3306}, "debug": True}


def test_multi_level_nested_merge():
    data = {"a": {"b": {"d": 3, "e": 4}}}
    defaults = {"a": {"b": {"c": 1, "d": 2}}}
    result = merge_with_defaults(data, defaults)
    assert result == {"a": {"b": {"c": 1, "d": 3, "e": 4}}}


def test_shallow_mode_top_level_only():
    """deep=False: верхний уровень обновляется, вложенный dict заменяется целиком."""
    data = {"db": {"port": 3306}}
    defaults = {"db": {"host": "localhost", "port": 5432}, "x": 1}
    result = merge_with_defaults(data, defaults, deep=False)
    assert result == {"db": {"port": 3306}, "x": 1}


def test_none_from_data_overrides():
    result = merge_with_defaults({"a": None}, {"a": 1})
    assert result == {"a": None}


def test_none_default_replaced_by_dict():
    result = merge_with_defaults({"a": {"x": 1}}, {"a": None})
    assert result == {"a": {"x": 1}}


def test_list_replaced_not_merged():
    result = merge_with_defaults({"tags": ["c"]}, {"tags": ["a", "b"]})
    assert result == {"tags": ["c"]}


def test_dict_replaces_scalar():
    result = merge_with_defaults({"a": {"nested": True}}, {"a": "string"})
    assert result == {"a": {"nested": True}}


def test_scalar_replaces_dict():
    result = merge_with_defaults({"a": "string"}, {"a": {"nested": True}})
    assert result == {"a": "string"}


def test_empty_data_returns_defaults_equivalent():
    defaults = {"a": 1, "b": {"c": 2}}
    result = merge_with_defaults({}, defaults)
    assert result == defaults


def test_top_level_defaults_not_mutated():
    defaults = {"a": 1}
    merge_with_defaults({"b": 2}, defaults)
    assert defaults == {"a": 1}
