# -*- coding: utf-8 -*-
"""Приёмочные тесты дельта-движка записи рецепта (C-30, Task 1.1a).

Контракт — ``plans/2026-10-26_recipe-save-noise/design.md`` §2:

  patch_yaml_preserving(path, before, after) -> bool
  apply_delta(target, before, after) -> dict
  class YamlPatchConflict(ValueError)

Тесты написаны слепо (до реализации), по критериям приёмки. Новый API берётся
атрибутом модуля ``yaml_io`` внутри тела теста: пока символа нет, тест красный
(AttributeError), а не файл целиком не собирается.

Правила файла: ожидаемые байты — литералы; EOL, ``st_mtime_ns`` и комментарии
проверяются по байтам файла, а не по вызовам API.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest
import yaml
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from multiprocess_framework.modules.recipe import yaml_io

# Метка времени, заведомо не равная «сейчас»: перезапись файла её изменит.
_OLD_MTIME_NS = 1_700_000_000_000_000_000


def _write(path: Path, data: bytes) -> tuple[bytes, int]:
    """Записать байты, выставить старый mtime; вернуть (байты, mtime_ns) как они лежат на диске."""
    path.write_bytes(data)
    os.utime(path, ns=(_OLD_MTIME_NS, _OLD_MTIME_NS))
    return path.read_bytes(), path.stat().st_mtime_ns


# ---------------------------------------------------------------------------
# Пустая дельта — записи нет
# ---------------------------------------------------------------------------

_EMPTY_DELTA_SRC = b"# header\nname: demo  # eol\nitems:\n  - a\n  - b\nmap:\n  x: 1\n  y: 2\n"

_EMPTY_DELTA_CASES = {
    "equal": (
        {"name": "demo", "items": ["a", "b"], "map": {"x": 1, "y": 2}},
        {"name": "demo", "items": ["a", "b"], "map": {"x": 1, "y": 2}},
    ),
    "key_order_only": (
        {"name": "demo", "items": ["a", "b"], "map": {"x": 1, "y": 2}},
        {"map": {"y": 2, "x": 1}, "items": ["a", "b"], "name": "demo"},
    ),
}


@pytest.mark.parametrize("case", list(_EMPTY_DELTA_CASES), ids=list(_EMPTY_DELTA_CASES))
def test_empty_delta_does_not_write(tmp_path: Path, case: str) -> None:
    """Семантически равное before/after: возврат False, байты и st_mtime_ns прежние."""
    before, after = _EMPTY_DELTA_CASES[case]
    path = tmp_path / "r.yaml"
    raw_before, mtime_before = _write(path, _EMPTY_DELTA_SRC)

    written = yaml_io.patch_yaml_preserving(path, before, after)

    assert written is False
    assert path.read_bytes() == raw_before
    assert path.stat().st_mtime_ns == mtime_before


# ---------------------------------------------------------------------------
# Изменение листа
# ---------------------------------------------------------------------------


def test_leaf_change_keeps_comments_and_flow_style(tmp_path: Path) -> None:
    """Меняется лист в блочной и во flow-карте; все комментарии и flow-вид на месте, True."""
    src = (
        b"# header comment\n"
        b"name: demo  # name comment\n"
        b"robot_params: {P_ZONE_MAX: 6000}\n"
        b"restart_policy: {enabled: true, max_retries: 3, window_sec: 60}\n"
        b"cfg:\n"
        b"  # about port\n"
        b"  port: 5021  # eol port\n"
        b"  host: 127.0.0.1\n"
    )
    expected = (
        b"# header comment\n"
        b"name: demo  # name comment\n"
        b"robot_params: {P_ZONE_MAX: 6000}\n"
        b"restart_policy: {enabled: true, max_retries: 5, window_sec: 60}\n"
        b"cfg:\n"
        b"  # about port\n"
        b"  port: 5022  # eol port\n"
        b"  host: 127.0.0.1\n"
    )
    before = {
        "name": "demo",
        "robot_params": {"P_ZONE_MAX": 6000},
        "restart_policy": {"enabled": True, "max_retries": 3, "window_sec": 60},
        "cfg": {"port": 5021, "host": "127.0.0.1"},
    }
    after = {
        "name": "demo",
        "robot_params": {"P_ZONE_MAX": 6000},
        "restart_policy": {"enabled": True, "max_retries": 5, "window_sec": 60},
        "cfg": {"port": 5022, "host": "127.0.0.1"},
    }
    path = tmp_path / "r.yaml"
    _write(path, src)

    written = yaml_io.patch_yaml_preserving(path, before, after)

    assert written is True
    assert path.read_bytes() == expected


# ---------------------------------------------------------------------------
# Списки: непрерывность удаления (F17)
# ---------------------------------------------------------------------------


def test_list_delete_noncontiguous_keeps_survivors(tmp_path: Path) -> None:
    """Две привязки ``phone`` из четырёх (индексы 0 и 2) удалены; выжившие на месте и в порядке."""
    src = (
        b"displays:\n"
        b"  - node_id: a.x.frame\n"
        b"    display_id: phone\n"
        b"  - node_id: b.x.frame\n"
        b"    display_id: main\n"
        b"  - node_id: c.x.frame\n"
        b"    display_id: phone\n"
        b"  - node_id: d.x.frame\n"
        b"    display_id: mask\n"
    )
    expected = (
        b"displays:\n  - node_id: b.x.frame\n    display_id: main\n  - node_id: d.x.frame\n    display_id: mask\n"
    )
    before = {
        "displays": [
            {"node_id": "a.x.frame", "display_id": "phone"},
            {"node_id": "b.x.frame", "display_id": "main"},
            {"node_id": "c.x.frame", "display_id": "phone"},
            {"node_id": "d.x.frame", "display_id": "mask"},
        ]
    }
    after = {
        "displays": [
            {"node_id": "b.x.frame", "display_id": "main"},
            {"node_id": "d.x.frame", "display_id": "mask"},
        ]
    }
    path = tmp_path / "r.yaml"
    _write(path, src)

    yaml_io.patch_yaml_preserving(path, before, after)

    assert path.read_bytes() == expected


# ---------------------------------------------------------------------------
# Удаление не уносит комментарий следующего соседа (ровно один раз, перед соседом)
# ---------------------------------------------------------------------------

# case -> (исходник, before, after, маркер-комментарий, строка следующего соседа,
#          строка, которая обязана остаться перед комментарием (или None), строка, которой не должно остаться)
_NEIGHBOUR_CASES = {
    "map_key": (
        "a: 1\nb: 2\n# about c\nc: 3\n",
        {"a": 1, "b": 2, "c": 3},
        {"a": 1, "c": 3},
        "# about c",
        "c: 3",
        "a: 1",
        "b: 2",
    ),
    "list_item": (
        "items:\n  - one\n  - two\n  # about three\n  - three\n",
        {"items": ["one", "two", "three"]},
        {"items": ["one", "three"]},
        "# about three",
        "- three",
        "- one",
        "- two",
    ),
    "nested_leaf": (
        "top:\n  z: 0\n  a:\n    x: 1\n    y: 2\n  # about b\n  b: 3\n",
        {"top": {"z": 0, "a": {"x": 1, "y": 2}, "b": 3}},
        {"top": {"z": 0, "b": 3}},
        "# about b",
        "b: 3",
        "z: 0",
        "y: 2",
    ),
    "list_item_0": (
        "items:\n  - one\n  # about two\n  - two\n",
        {"items": ["one", "two"]},
        {"items": ["two"]},
        "# about two",
        "- two",
        None,
        "- one",
    ),
}


@pytest.mark.parametrize("case", list(_NEIGHBOUR_CASES), ids=list(_NEIGHBOUR_CASES))
def test_delete_keeps_next_neighbour_comment_once(tmp_path: Path, case: str) -> None:
    """Комментарий следующего соседа удалённого есть ровно один раз, стоит перед соседом, пустых строк не добавлено."""
    src, before, after, marker, neighbour, prev_line, gone = _NEIGHBOUR_CASES[case]
    path = tmp_path / "r.yaml"
    _write(path, src.encode("utf-8"))

    yaml_io.patch_yaml_preserving(path, before, after)

    text = path.read_text(encoding="utf-8")
    assert text.count(marker) == 1
    assert gone not in text
    assert text.index(marker) < text.index(neighbour)
    if prev_line is not None:
        assert text.index(prev_line) < text.index(marker)
    assert "\n\n" not in text
    assert yaml.safe_load(text) == after


# ---------------------------------------------------------------------------
# Вид скаляра: bool / int / float различны
# ---------------------------------------------------------------------------

_KIND_PAIRS = [
    (1, True),
    (True, 1),
    (1, 1.0),
    (1.0, 1),
    (True, 1.0),
    (1.0, True),
    (0, False),
    (False, 0),
    (0, 0.0),
]


def test_bool_int_float_are_distinct() -> None:
    """Замена 1 <-> True <-> 1.0 — не пустая дельта: в результате значение именно нового вида."""
    wrong = []
    for old, new in _KIND_PAIRS:
        as_key = yaml_io.apply_delta({"k": old}, {"k": old}, {"k": new})
        in_list = yaml_io.apply_delta({"k": [old]}, {"k": [old]}, {"k": [new]})
        if type(as_key["k"]) is not type(new):
            wrong.append(("key", old, new, as_key["k"]))
        if type(in_list["k"][0]) is not type(new):
            wrong.append(("list", old, new, in_list["k"][0]))
    assert wrong == []


# ---------------------------------------------------------------------------
# EOL
# ---------------------------------------------------------------------------

# case -> (исходные байты, before, after, допустимые итоговые байты)
_EOL_CASES = {
    "crlf": (
        b"a: 1\r\nb: 2\r\nc: 3\r\n",
        {"a": 1, "b": 2, "c": 3},
        {"a": 1, "b": 5, "c": 3},
        (b"a: 1\r\nb: 5\r\nc: 3\r\n",),
    ),
    "lf": (
        b"a: 1\nb: 2\nc: 3\n",
        {"a": 1, "b": 2, "c": 3},
        {"a": 1, "b": 5, "c": 3},
        (b"a: 1\nb: 5\nc: 3\n",),
    ),
    # Смешанный EOL нормализуется к EOL первой строки (здесь CRLF, хотя LF в большинстве).
    "mixed_first_line_wins": (
        b"a: 1\r\nb: 2\nc: 3\n",
        {"a": 1, "b": 2, "c": 3},
        {"a": 1, "b": 5, "c": 3},
        (b"a: 1\r\nb: 5\r\nc: 3\r\n",),
    ),
    # Файл без единого терминатора -> EOL = LF. Конечный перевод строки дампа допустим, но только LF.
    "no_trailing_newline": (
        b"a: 1",
        {"a": 1},
        {"a": 2},
        (b"a: 2\n", b"a: 2"),
    ),
}


@pytest.mark.parametrize("case", list(_EOL_CASES), ids=list(_EOL_CASES))
def test_eol_preserved(tmp_path: Path, case: str) -> None:
    """Правка листа: EOL файла сохранён (CRLF, LF, у смешанного — первой строки, LF без терминатора)."""
    src, before, after, allowed = _EOL_CASES[case]
    path = tmp_path / "r.yaml"
    _write(path, src)

    yaml_io.patch_yaml_preserving(path, before, after)

    data = path.read_bytes()
    assert b"\r\r" not in data
    assert data in allowed


# ---------------------------------------------------------------------------
# Конфликт
# ---------------------------------------------------------------------------


def test_conflict_raises_and_file_intact(tmp_path: Path) -> None:
    """Цель держит скаляр там, где дельта ждёт mapping: YamlPatchConflict с путём, файл не тронут."""
    src = b"# keep\ncfg: 5\nother: 1\n"
    path = tmp_path / "r.yaml"
    raw_before, mtime_before = _write(path, src)

    with pytest.raises(yaml_io.YamlPatchConflict) as info:
        yaml_io.patch_yaml_preserving(path, {"cfg": {"k": 1}}, {"cfg": {"k": 2}})

    assert isinstance(info.value, ValueError)
    assert "cfg" in str(info.value)
    assert path.read_bytes() == raw_before
    assert path.stat().st_mtime_ns == mtime_before


# ---------------------------------------------------------------------------
# apply_delta не мутирует цель
# ---------------------------------------------------------------------------


def test_apply_delta_does_not_mutate_target() -> None:
    """apply_delta возвращает новый объект; переданный target остаётся ровно таким, каким был."""
    target = {
        "name": "demo",
        "cfg": {"port": 5021, "gone": True},
        "items": ["a", "b", "c"],
    }
    before = {"name": "demo", "cfg": {"port": 5021, "gone": True}, "items": ["a", "b", "c"]}
    after = {"name": "demo", "cfg": {"port": 5022, "added": 1}, "items": ["a", "x", "b", "c"]}

    result = yaml_io.apply_delta(target, before, after)

    assert target == {
        "name": "demo",
        "cfg": {"port": 5021, "gone": True},
        "items": ["a", "b", "c"],
    }
    assert result is not target
    assert result == after


# ---------------------------------------------------------------------------
# Якорь и алиас (форма dataset_circle_capture.yaml:319 / :396)
# ---------------------------------------------------------------------------

_ALIAS_SRC = (
    b"blueprint:\n"
    b"  metadata:\n"
    b"    gui_positions: &id001\n"
    b"      node_a:\n"
    b"        - 1.0\n"
    b"        - 2.0\n"
    b"      node_b:\n"
    b"        - 3.0\n"
    b"        - 4.0\n"
    b"gui_positions: *id001\n"
)


def _alias_doc(positions_in_blueprint: dict, positions_top: dict) -> dict:
    return {"blueprint": {"metadata": {"gui_positions": positions_in_blueprint}}, "gui_positions": positions_top}


_ALIAS_OLD = {"node_a": [1.0, 2.0], "node_b": [3.0, 4.0]}
_ALIAS_NEW = {"node_a": [9.0, 2.0], "node_b": [3.0, 4.0]}


@pytest.mark.parametrize("case", ["same_at_all_refs_in_place", "differs_conflict"])
def test_aliased_node_edit(tmp_path: Path, case: str) -> None:
    """Узел с якорем: одинаковая правка во всех местах ссылок — на месте (якорь жив); разная — YamlPatchConflict."""
    path = tmp_path / "r.yaml"
    raw_before, mtime_before = _write(path, _ALIAS_SRC)
    before = _alias_doc(_ALIAS_OLD, _ALIAS_OLD)

    if case == "same_at_all_refs_in_place":
        after = _alias_doc(_ALIAS_NEW, _ALIAS_NEW)
        yaml_io.patch_yaml_preserving(path, before, after)
        assert path.read_bytes() == (
            b"blueprint:\n"
            b"  metadata:\n"
            b"    gui_positions: &id001\n"
            b"      node_a:\n"
            b"        - 9.0\n"
            b"        - 2.0\n"
            b"      node_b:\n"
            b"        - 3.0\n"
            b"        - 4.0\n"
            b"gui_positions: *id001\n"
        )
    else:
        after = _alias_doc(_ALIAS_NEW, _ALIAS_OLD)
        with pytest.raises(yaml_io.YamlPatchConflict) as info:
            yaml_io.patch_yaml_preserving(path, before, after)
        assert "gui_positions" in str(info.value)
        assert path.read_bytes() == raw_before
        assert path.stat().st_mtime_ns == mtime_before


# ---------------------------------------------------------------------------
# Свойство: load(patch(file(before), before, after)) == after
# ---------------------------------------------------------------------------

# Домен — только валидный вход: ключи и строки начинаются с буквы ``k``/``s``, так что не могут
# совпасть с YAML-словами (yes/no/on/off/null/true) и не читаются как числа; числа — короткие
# двоичные дроби без показателя степени. Вид скаляра различается сравнением через json.
_KEY = st.from_regex(r"k[a-z]{0,4}", fullmatch=True)
_TEXT = st.from_regex(r"s[a-z0-9]{0,5}", fullmatch=True)
_SCALAR = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(-1000, 1000),
    st.integers(-4000, 4000).map(lambda n: n / 8),
    _TEXT,
)
_VALUE = st.recursive(
    _SCALAR,
    lambda children: st.one_of(
        st.lists(children, max_size=4),
        st.dictionaries(_KEY, children, max_size=4),
    ),
    max_leaves=12,
)
_DOC = st.dictionaries(_KEY, _VALUE, max_size=4)


@settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(before=_DOC, after=_DOC)
def test_property_patch_reaches_after(before: dict, after: dict) -> None:
    """Для любых вложенных before/after файл после патча читается как after (с различием bool/int/float)."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "r.yaml"
        path.write_text(yaml.safe_dump(before, sort_keys=False, allow_unicode=True), encoding="utf-8")

        yaml_io.patch_yaml_preserving(path, before, after)

        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert json.dumps(loaded, sort_keys=True) == json.dumps(after, sort_keys=True)


# ---------------------------------------------------------------------------
# Вне лимита REDS (красные до GREEN)
# ---------------------------------------------------------------------------


def test_add_key_appends_in_after_order(tmp_path: Path) -> None:
    """Ключи только в after дописываются в конец в порядке after."""
    path = tmp_path / "r.yaml"
    _write(path, b"a: 1\n")

    yaml_io.patch_yaml_preserving(path, {"a": 1}, {"a": 1, "z": 2, "b": 3})

    assert path.read_bytes() == b"a: 1\nz: 2\nb: 3\n"


def test_delta_into_absent_container_creates_it(tmp_path: Path) -> None:
    """Дельта в ``blueprint.metadata`` рецепта без metadata: промежуточные контейнеры создаются (F5 i)."""
    path = tmp_path / "r.yaml"
    _write(path, b"name: demo\nblueprint:\n  name: default\n")
    before = {"name": "demo", "blueprint": {"name": "default", "metadata": {"gui_positions": {"a": [1.0, 2.0]}}}}
    after = {"name": "demo", "blueprint": {"name": "default", "metadata": {"gui_positions": {"a": [3.0, 4.0]}}}}

    yaml_io.patch_yaml_preserving(path, before, after)

    assert yaml.safe_load(path.read_text(encoding="utf-8")) == {
        "name": "demo",
        "blueprint": {"name": "default", "metadata": {"gui_positions": {"a": [3.0, 4.0]}}},
    }


def test_delete_key(tmp_path: Path) -> None:
    """Ключ только в before удаляется из файла вместе с собственной строкой."""
    path = tmp_path / "r.yaml"
    _write(path, b"a: 1\nb: 2  # eol of b\nc: 3\n")

    yaml_io.patch_yaml_preserving(path, {"a": 1, "b": 2, "c": 3}, {"a": 1, "c": 3})

    assert path.read_bytes() == b"a: 1\nc: 3\n"


def test_create_file_when_absent(tmp_path: Path) -> None:
    """Файла нет: создаётся из after целиком, возврат True."""
    path = tmp_path / "new.yaml"
    after = {"name": "demo", "cfg": {"port": 5021, "tags": ["x", "y"]}}

    written = yaml_io.patch_yaml_preserving(path, {}, after)

    assert written is True
    assert yaml.safe_load(path.read_text(encoding="utf-8")) == after
