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
import re
import tempfile
from pathlib import Path

import pytest
import yaml
from hypothesis import HealthCheck, assume, given, seed, settings
from hypothesis import strategies as st
from hypothesis.errors import UnsatisfiedAssumption

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
    """Две привязки ``phone`` из четырёх (индексы 0 и 2) удалены; выжившие — те же узлы (с комментариями), в порядке.

    Inline-комментарии у выживших отличают сохранение узла от поиндексной перезаписи соседом
    (инъекция I2 лида: префикс/суффикс вместо SequenceMatcher без комментариев давала те же байты).
    """
    src = (
        b"displays:\n"
        b"  - node_id: a.x.frame\n"
        b"    display_id: phone\n"
        b"  - node_id: b.x.frame\n"
        b"    display_id: main  # keep-b\n"
        b"  - node_id: c.x.frame\n"
        b"    display_id: phone\n"
        b"  - node_id: d.x.frame\n"
        b"    display_id: mask  # keep-d\n"
    )
    expected = (
        b"displays:\n"
        b"  - node_id: b.x.frame\n"
        b"    display_id: main  # keep-b\n"
        b"  - node_id: d.x.frame\n"
        b"    display_id: mask  # keep-d\n"
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


# ---------------------------------------------------------------------------
# Ревью 1.1a, раунд 1: опустевший контейнер, алиас под сдвигом списка, пустая строка
# ---------------------------------------------------------------------------

# case -> (исходник, before, after, комментарий, строка, перед которой он обязан стоять)
_EMPTIED_CASES = {
    "list_root": (
        "a: 1\nitems:\n  - x: 1  # eol\n# c-after-items\nb: 2\n",
        {"a": 1, "items": [{"x": 1}], "b": 2},
        {"a": 1, "items": [], "b": 2},
        "# c-after-items",
        "b: 2",
    ),
    "map_root": (
        "a: 1\nm:\n  k: 1\n# c-after-m\nb: 2\n",
        {"a": 1, "m": {"k": 1}, "b": 2},
        {"a": 1, "m": {}, "b": 2},
        "# c-after-m",
        "b: 2",
    ),
    "list_nested": (
        "top:\n  items:\n    - 1\n  # c-next\n  z: 2\n",
        {"top": {"items": [1], "z": 2}},
        {"top": {"items": [], "z": 2}},
        "# c-next",
        "z: 2",
    ),
    "map_nested": (
        "top:\n  m:\n    k: 1\n  # c-next\n  z: 2\n",
        {"top": {"m": {"k": 1}, "z": 2}},
        {"top": {"m": {}, "z": 2}},
        "# c-next",
        "z: 2",
    ),
    "map_first_key": (
        "m:\n  k: 1\n# lead-of-z\nz: 2\n",
        {"m": {"k": 1}, "z": 2},
        {"m": {}, "z": 2},
        "# lead-of-z",
        "z: 2",
    ),
    "list_with_header": (
        "a: 1\nitems:\n  # head\n  - x\nb: 2\n",
        {"a": 1, "items": ["x"], "b": 2},
        {"a": 1, "items": [], "b": 2},
        "# head",
        "b: 2",
    ),
}


@pytest.mark.parametrize("case", list(_EMPTIED_CASES), ids=list(_EMPTIED_CASES))
def test_emptied_container_keeps_tail_comment_valid(tmp_path: Path, case: str) -> None:
    """Убран единственный элемент при комментарии в хвосте: файл читается, комментарий ровно один раз."""
    src, before, after, marker, next_line = _EMPTIED_CASES[case]
    path = tmp_path / "r.yaml"
    _write(path, src.encode("utf-8"))

    yaml_io.patch_yaml_preserving(path, before, after)

    text = path.read_text(encoding="utf-8")
    assert yaml.safe_load(text) == after
    assert text.count(marker) == 1
    assert text.index(marker) < text.index(next_line)


_S_SRC = b"a: &id\n  v: 1\nb:\n  - n: first\n  - n: second\n    x: *id\n"
_S_BEFORE = {"a": {"v": 1}, "b": [{"n": "first"}, {"n": "second", "x": {"v": 1}}]}


def test_alias_after_list_shift_no_silent_corruption(tmp_path: Path) -> None:
    """S1: перед местом алиаса удалён элемент списка, якорь правится, у алиаса after прежний.

    Допустимо: YamlPatchConflict (файл цел) или запись, которая читается ровно как after."""
    path = tmp_path / "r.yaml"
    raw_before, mtime_before = _write(path, _S_SRC)
    after = {"a": {"v": 2}, "b": [{"n": "second", "x": {"v": 1}}]}

    try:
        yaml_io.patch_yaml_preserving(path, _S_BEFORE, after)
    except yaml_io.YamlPatchConflict:
        assert path.read_bytes() == raw_before
        assert path.stat().st_mtime_ns == mtime_before
    else:
        assert yaml.safe_load(path.read_text(encoding="utf-8")) == after


_S3_SRC = b"a: &id\n  v: 1\nb:\n  - n: first\n    x: {v: 7}\n  - n: second\n    x: *id\n"


def test_alias_legal_insert_before_ref_no_conflict(tmp_path: Path) -> None:
    """S3: вставка в начало списка и одинаковая правка во всех местах ссылок — не конфликт, якорь жив.

    По буквальному пути цели ``b[1].x`` в after лежит ``first.x`` = {v: 7} — это не место алиаса."""
    path = tmp_path / "r.yaml"
    _write(path, _S3_SRC)
    before = {"a": {"v": 1}, "b": [{"n": "first", "x": {"v": 7}}, {"n": "second", "x": {"v": 1}}]}
    after = {
        "a": {"v": 2},
        "b": [{"n": "zero"}, {"n": "first", "x": {"v": 7}}, {"n": "second", "x": {"v": 2}}],
    }

    yaml_io.patch_yaml_preserving(path, before, after)

    data = path.read_bytes()
    assert yaml.safe_load(data.decode("utf-8")) == after
    assert b"&id" in data
    assert b"*id" in data


def test_delete_last_item_keeps_blank_line_before_next_section(tmp_path: Path) -> None:
    """Удалён последний элемент; пустая строка перед следующей секцией остаётся ровно одна."""
    path = tmp_path / "r.yaml"
    _write(path, b"items:\n  - a\n  - b\n\nnext: 1\n")

    yaml_io.patch_yaml_preserving(path, {"items": ["a", "b"], "next": 1}, {"items": ["a"], "next": 1})

    assert path.read_bytes() == b"items:\n  - a\n\nnext: 1\n"


def _dump_commented(doc: dict, rnd) -> str:
    """Блочный YAML из doc со случайными комментариями: EOL, перед ключом/элементом, хвост вложенного блока."""
    out: list[str] = []
    counter = iter(range(10_000))

    def eol() -> str:
        return f"  # e{next(counter)}" if rnd.random() < 0.3 else ""

    def lead(indent: int) -> None:
        if rnd.random() < 0.3:
            # Комментарий на отступе блока (стиль рецептов). Колонка 0 внутри вложенного блока
            # ломает уже чистый round-trip ruamel 0.19 (без дельты) — это ловит страховка записи.
            out.append(" " * indent + f"# c{next(counter)}")

    def entry(head: str, value, indent: int) -> None:
        if isinstance(value, (dict, list)) and value:
            out.append(head + eol())
            block(value, indent + 2)
        else:
            flow = ("{}" if isinstance(value, dict) else "[]") if isinstance(value, (dict, list)) else json.dumps(value)
            # EOL-комментарий у пустого flow ``{}``/``[]`` — известный открытый случай (страховка
            # записи отказывает, файл цел), в генератор не входит.
            out.append(f"{head} {flow}" + ("" if isinstance(value, (dict, list)) else eol()))

    def block(value, indent: int) -> None:
        pairs = value.items() if isinstance(value, dict) else (("-", x) for x in value)
        for key, child in pairs:
            lead(indent)
            entry(" " * indent + (f"{key}:" if isinstance(value, dict) else "-"), child, indent)

    if doc:
        block(doc, 0)
    else:
        out.append("{}")
    return "\n".join(out) + "\n"


def _ruamel_roundtrip_clean(src: str, before: dict) -> bool:
    """Чистый round-trip ruamel (load -> dump без правок) читается PyYAML как before."""
    import io

    from multiprocess_framework.modules.recipe import _ruamel_doc

    rt = _ruamel_doc.make_yaml()
    buf = io.StringIO()
    rt.dump(_ruamel_doc.load_document(rt, src), buf)
    try:
        return json.dumps(yaml.safe_load(buf.getvalue()), sort_keys=True) == json.dumps(before, sort_keys=True)
    except yaml.YAMLError:
        return False


def _mutate(node, rnd):
    """Случайная правка plain-дерева: удаление ключа/элемента, опустошение контейнера, смена скаляра, вставка."""
    if isinstance(node, dict):
        res = {}
        for key, child in node.items():
            r = rnd.random()
            if r < 0.15:
                continue
            if r > 0.85 and isinstance(child, (dict, list)):
                res[key] = type(child)()
            else:
                res[key] = _mutate(child, rnd) if r < 0.6 else child
        if rnd.random() < 0.1:
            res["knew"] = 1
        return res
    if isinstance(node, list):
        res = [_mutate(x, rnd) if rnd.random() < 0.5 else x for x in node if rnd.random() >= 0.2]
        if rnd.random() < 0.1:
            res.insert(rnd.randint(0, len(res)), "sins")
        if rnd.random() < 0.1:
            res = []
        return res
    return node if rnd.random() < 0.8 else rnd.choice([7, "schg", True, None, 2.5])


_MARKER = re.compile(r"# [ce]\d+")


def _markers(text: str) -> list[str]:
    """Маркеры комментариев генератора (``# c<N>``/``# e<N>``) в порядке появления."""
    return _MARKER.findall(text)


def _patch_case(before: dict, rnd) -> str:
    """Один случай T1/T2: ``"written"`` — файл записан и верен; ``"refused"`` — отказ страховки, файл цел.

    Отказ допустим только как ``YamlWriteRefused`` при прежних байтах и ``st_mtime_ns`` (design.md §12.4);
    любое другое исключение уходит наружу — красный. ``assume`` — входной фильтр, не исход."""
    after = _mutate(before, rnd)
    src = _dump_commented(before, rnd)
    # Вход, который ruamel 0.19 портит уже чистым round-trip (без дельты), — дефект ruamel, а не движка.
    assume(_ruamel_roundtrip_clean(src, before))
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "r.yaml"
        raw_before, mtime_before = _write(path, src.encode("utf-8"))
        try:
            yaml_io.patch_yaml_preserving(path, before, after)
        except yaml_io.YamlWriteRefused as exc:
            if type(exc) is not yaml_io.YamlWriteRefused:
                raise  # подкласс отказа — не отказ страховки
            assert path.read_bytes() == raw_before
            assert path.stat().st_mtime_ns == mtime_before
            return "refused"
        out = path.read_text(encoding="utf-8")
    assert json.dumps(yaml.safe_load(out), sort_keys=True) == json.dumps(after, sort_keys=True)
    marks = _markers(out)
    assert len(marks) == len(set(marks)), f"маркер комментария дважды: {marks}"
    return "written"


@settings(max_examples=300, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(before=_DOC, rnd=st.randoms(use_true_random=False))
def test_property_patch_with_comments_reaches_after(before: dict, rnd) -> None:
    """Файл с комментариями: запись даёт after без дублей комментариев; отказ — только YamlWriteRefused, файл цел."""
    _patch_case(before, rnd)


@pytest.mark.parametrize("sd", range(10))
def test_property_refusal_budget(sd: int) -> None:
    """Храповик (design.md §12.5, не RED): 300 примеров под ``@seed(sd)`` — ни одного отказа страховки.

    Поток hypothesis зависит от процесса-хозяина: детерминированный RED — корпус
    ``test_known_glue_input_reaches_after``."""
    counts = {"written": 0, "refused": 0, "rejected": 0}

    @seed(sd)
    @settings(database=None, max_examples=300, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    @given(before=_DOC, rnd=st.randoms(use_true_random=False))
    def run(before: dict, rnd) -> None:
        try:
            counts[_patch_case(before, rnd)] += 1
        except UnsatisfiedAssumption:
            counts["rejected"] += 1
            raise

    run()
    assert counts["written"] + counts["refused"] == 300, counts
    assert counts["rejected"] <= 15, counts
    assert counts["refused"] == 0, counts


# ---------------------------------------------------------------------------
# Task 1.1i: склейка строк при переносе комментариев у блочного списка (design.md §12.6)
# ---------------------------------------------------------------------------

# id -> (src, before, after, маркеры выживших: каждый ровно по разу). B1–B6 — ревью 1.1f §B,
# B7–B9 — ``probes/glue_refused_examples.json``. Все девять на HEAD 1.1f — отказ страховки.
_GLUE_CASES = {
    "B1": (
        "# c0\nk: null  # e1\n# c2\nka:  # e3\n  # c4\n  - null  # e5\n  # c6\n  - null  # e7\n  # c8\n  -  # e9\n"
        "    # c10\n    k: null  # e11\n    # c12\n    ka: null  # e13\n    # c14\n    kb: null  # e15\n"
        "    # c16\n    kt: null  # e17\n",
        {"k": None, "ka": [None, None, {"k": None, "ka": None, "kb": None, "kt": None}]},
        {"ka": [{"kt": None, "knew": 1}], "knew": 1},
        ("# c0", "# c2", "# e3", "# c4", "# c6", "# c8"),
    ),
    "B2": (
        "# c0\nk: null  # e1\n# c2\nka:  # e3\n  # c4\n  -  # e5\n    # c6\n    k: null  # e7\n  # c8\n  - null  # e9\n"
        "  # c10\n  -  # e11\n    # c12\n    k: null  # e13\n    # c14\n    ka: null  # e15\n    # c16\n"
        "    kb: null  # e17\n    # c18\n    ki: null  # e19\n",
        {"k": None, "ka": [{"k": None}, None, {"k": None, "ka": None, "kb": None, "ki": None}]},
        {"ka": [{"knew": 1}, {"knew": 1}], "knew": 1},
        ("# c0", "# c2", "# e3", "# c4", "# e5", "# c6", "# c8", "# c10"),
    ),
    "B3": (
        "# c0\nk: []\n# c1\nka:  # e2\n  # c3\n  - []\n  # c4\n  -  # e5\n    # c6\n    k: null  # e7\n    # c8\n"
        "    ka: null  # e9\n  # c10\n  - null  # e11\n",
        {"k": [], "ka": [[], {"k": None, "ka": None}, None]},
        {"ka": [{"ka": None, "knew": 1}], "knew": 1},
        ("# c0", "# c1", "# e2", "# c3", "# c10"),
    ),
    "B4": (
        "# c0\nkgv:  # e1\n  - {}\n  - {}\n  -\n    - null  # e2\n    # c3\n    - null\n  -\n    kggr: null  # e4\n"
        "    kcats: null\n    # c5\n    k: {}\n    kliyk: null  # e6\n",
        {"kgv": [{}, {}, [None, None], {"kggr": None, "kcats": None, "k": {}, "kliyk": None}]},
        {"kgv": [{}, {}, {"kcats": None}, "sins"]},
        ("# c0", "# e1"),
    ),
    "B5": (
        "# c0\nk:  # e1\n  # c2\n  - {}\n  # c3\n  - {}\n  # c4\n  - null  # e5\n  # c6\n  -  # e7\n    # c8\n"
        "    k: []\n    # c9\n    ka: null  # e10\n    kaa: null\n    # c11\n    kaaa: null  # e12\n",
        {"k": [{}, {}, None, {"k": [], "ka": None, "kaa": None, "kaaa": None}]},
        {"k": [{}, {"knew": 1}, {"kaaa": None, "knew": 1}, "sins"], "knew": 1},
        ("# c0", "# e1", "# c2", "# c3", "# c4", "# c6", "# e7", "# c8"),
    ),
    "B6": (
        "# c0\nk:  # e1\n  # c2\n  - {}\n  # c3\n  - {}\n  # c4\n  - null  # e5\n  # c6\n  -  # e7\n    # c8\n"
        "    k: []\n    # c9\n    ka: null  # e10\n    kaa: null\n    # c11\n    kaaa: null  # e12\n",
        {"k": [{}, {}, None, {"k": [], "ka": None, "kaa": None, "kaaa": None}]},
        {"k": [{}, "sins", {"knew": 1}, {"knew": 1}], "knew": 1},
        ("# c0", "# e1", "# c2", "# c3", "# c4", "# c6", "# e7", "# c8", "# c11"),
    ),
    "B7": (
        '# c0\nkuruq:\n  # c1\n  - []\n  - []\n  -\n    k: null\n    kr: "s"\n    # c2\n    kwdqc:  # e3\n'
        "      # c4\n      kf: false  # e5\n# c6\nk:  # e7\n  - -22.625\n  - []\n# c8\nkt:  # e9\n"
        '  k: null  # e10\n  kahx: "sw0f"  # e11\n  kzv: false  # e12\n  kjgk: -19.5\nku: true  # e13\n',
        {
            "kuruq": [[], [], {"k": None, "kr": "s", "kwdqc": {"kf": False}}],
            "k": [-22.625, []],
            "kt": {"k": None, "kahx": "sw0f", "kzv": False, "kjgk": -19.5},
            "ku": True,
        },
        {"kuruq": [{"k": None, "kr": "s"}], "kt": {"k": None, "kahx": "sw0f", "kzv": False, "kjgk": -19.5}},
        # ``# c8`` не требуется: потеря при удалении ключа с пустым flow в конце — класс F16 (Task 1.3).
        ("# c0", "# c1", "# c6", "# e9", "# e10", "# e11", "# e12"),
    ),
    "B8": (
        "# c0\nkadk:\n  # c1\n  krokx: -38\nkvmco:  # e2\n  k:\n    # c3\n    - 122  # e4\n  # c5\n  krbq: 181\n"
        "  khlat: {}\n  kifc:\n    # c6\n    -  # e7\n      kq: 499.875  # e8\n# c9\nk:\n"
        '  khgrb: "srxgm"  # e10\n  # c11\n  k:\n    # c12\n    kuz: null\n  kde:\n    kukih: -9.375  # e13\n'
        "    # c14\n    kjf: false  # e15\n  # c16\n  kws: null  # e17\nkxena:  # e18\n  -\n    # c19\n"
        "    ko: 187\n    # c20\n    k: false  # e21\n  # c22\n  -\n    # c23\n    kxuxe: 111.0\n",
        {
            "kadk": {"krokx": -38},
            "kvmco": {"k": [122], "krbq": 181, "khlat": {}, "kifc": [{"kq": 499.875}]},
            "k": {"khgrb": "srxgm", "k": {"kuz": None}, "kde": {"kukih": -9.375, "kjf": False}, "kws": None},
            "kxena": [{"ko": 187, "k": False}, {"kxuxe": 111.0}],
        },
        {
            "k": {
                "khgrb": "srxgm",
                "k": {"kuz": None, "knew": 1},
                "kde": {"kukih": -9.375, "kjf": False},
                "kws": None,
                "knew": 1,
            },
            "kxena": [{"kxuxe": 111.0, "knew": 1}],
        },
        ("# c0", "# c9", "# e10", "# c11", "# c12", "# e13", "# c14", "# e15", "# c16", "# e17", "# e18", "# c22"),
    ),
    "B9": (
        "# c0\nkadk:\n  # c1\n  krokx: -38\nkvmco:  # e2\n  k:\n    # c3\n    - 122  # e4\n  # c5\n  krbq: {}\n"
        "  khlat: {}\n  kifc:\n    -  # e6\n      # c7\n      kq: 499.875\n# c8\nk:  # e9\n"
        '  khgrb: "srxgm"\n  # c10\n  k:  # e11\n    kuz: null  # e12\n  kde:\n    kukih: -9.375\n    # c13\n'
        "    kjf: false  # e14\n  # c15\n  kws: null  # e16\n# c17\nkxena:\n  # c18\n  -\n    ko: 187  # e19\n"
        "    k: false  # e20\n  # c21\n  -  # e22\n    kxuxe: 111.0  # e23\n",
        {
            "kadk": {"krokx": -38},
            "kvmco": {"k": [122], "krbq": {}, "khlat": {}, "kifc": [{"kq": 499.875}]},
            "k": {"khgrb": "srxgm", "k": {"kuz": None}, "kde": {"kukih": -9.375, "kjf": False}, "kws": None},
            "kxena": [{"ko": 187, "k": False}, {"kxuxe": 111.0}],
        },
        {
            "k": {
                "khgrb": "srxgm",
                "k": {"kuz": None, "knew": 1},
                "kde": {"kukih": -9.375, "kjf": False},
                "kws": None,
                "knew": 1,
            },
            "kxena": [{"kxuxe": 111.0, "knew": 1}],
        },
        (
            "# c0",
            "# c8",
            "# e9",
            "# c10",
            "# e11",
            "# e12",
            "# c13",
            "# e14",
            "# c15",
            "# e16",
            "# c17",
            "# c18",
            "# c21",
        ),
    ),
}


@pytest.mark.parametrize("case", list(_GLUE_CASES), ids=list(_GLUE_CASES))
def test_known_glue_input_reaches_after(tmp_path: Path, case: str) -> None:
    """Правка блочного списка у ``- {}``/комментариев: файл записан, PyYAML читает after, комментарии
    выживших узлов — каждый ровно один раз, ни один маркер не дважды (design.md §12.6)."""
    src, before, after, survivors = _GLUE_CASES[case]
    path = tmp_path / "r.yaml"
    _write(path, src.encode("utf-8"))

    yaml_io.patch_yaml_preserving(path, before, after)

    out = path.read_text(encoding="utf-8")
    assert yaml.safe_load(out) == after
    marks = _markers(out)
    assert len(marks) == len(set(marks)), f"маркер дважды: {marks}"
    for marker in survivors:
        assert marks.count(marker) == 1, f"{marker}: {marks.count(marker)} раз в\n{out}"


# id -> (src, before, after). C-61, seed 1 на 36ba0c22f: T1 упал в общем прогоне, пример не записан
# (`@example` в T1 не подходит — там `rnd`). Отказ на 36ba0c22f: «дамп не читается PyYAML» (``ka: knew: 1``).
_C61_CASES = {
    "ex1": (
        b"# c0\nk:  # e1\n  # c2\n  k:  # e3\n    # c4\n    - null  # e5\n    # c6\n    -  # e7\n      # c8\n"
        b"      k: null  # e9\n      # c10\n      ka: null  # e11\n    # c12\n    - null  # e13\n",
        {"k": {"k": [None, {"k": None, "ka": None}, None]}},
        {"k": {"k": [{"ka": None, "knew": 1}, "sins"], "knew": 1}, "knew": 1},
    ),
    "ex2": (
        b"kf:\n  kxnch:\n    # c0\n    - null  # e1\n    # c2\n    -\n      k: 28.0\n      # c3\n      kklrp: null\n"
        b"    - true\n",
        {"kf": {"kxnch": [None, {"k": 28.0, "kklrp": None}, True]}},
        {"kf": {"kxnch": [{"k": 28.0, "kklrp": "schg"}, "sins"]}},
    ),
}


@pytest.mark.parametrize("case", list(_C61_CASES), ids=list(_C61_CASES))
def test_c61_examples_reach_after(tmp_path: Path, case: str) -> None:
    """C-61, seed 1 на 36ba0c22f: примеры флейка T1 литералами — файл записан, PyYAML читает after,
    ни один маркер комментария не встречается дважды."""
    src, before, after = _C61_CASES[case]
    path = tmp_path / "r.yaml"
    _write(path, src)

    yaml_io.patch_yaml_preserving(path, before, after)

    out = path.read_text(encoding="utf-8")
    assert yaml.safe_load(out) == after
    marks = _markers(out)
    assert len(marks) == len(set(marks)), f"маркер дважды: {marks}"


# id -> (исходник: load -> dump без правок обязан дать его же, данные PyYAML)
_EMPTY_FLOW_MAP_CASES = {
    "key_eol": ("ka:  # e\n  - {}\n  - a: 1\n    b: 2\n", {"ka": [{}, {"a": 1, "b": 2}]}),
    "item_eol": ("ka:  # e\n  - {}  # x\n  - a: 1\n    b: 2\n", {"ka": [{}, {"a": 1, "b": 2}]}),
}


@pytest.mark.parametrize("case", list(_EMPTY_FLOW_MAP_CASES), ids=list(_EMPTY_FLOW_MAP_CASES))
def test_make_yaml_empty_flow_mapping_keeps_block_layout(case: str) -> None:
    """Дефект эмиттера ruamel 0.19.1 (без движка): EOL ключа + элемент ``- {}`` + блочная карта.

    ``no_newline``, взведённый комментарием ключа, у ``- []`` сбрасывает ``expect_node`` на старте списка
    в списке; у ``- {}`` сброса нет — вторая строка карты склеивалась с первой (``- a: 1 b: 2``).
    ``make_yaml`` подключает исправленный эмиттер: load -> dump без правок даёт исходник."""
    import io

    from multiprocess_framework.modules.recipe import _ruamel_doc

    src, data = _EMPTY_FLOW_MAP_CASES[case]
    rt = _ruamel_doc.make_yaml()
    buf = io.StringIO()
    rt.dump(_ruamel_doc.load_document(rt, src), buf)

    assert buf.getvalue() == src
    assert yaml.safe_load(buf.getvalue()) == data


# id -> (исходные байты, ожидаемые байты после правки ``kb: 1 -> 2``) — литералы
_FLOW_ITEM_EOL_CASES = {
    "map": (b"ka:\n  - {a: 1}  # q\n  - z\nkb: 1\n", b"ka:\n  - {a: 1}  # q\n  - z\nkb: 2\n"),
    "seq": (b"ka:\n  - [1, 2]  # q\n  - z\nkb: 1\n", b"ka:\n  - [1, 2]  # q\n  - z\nkb: 2\n"),
}


@pytest.mark.parametrize("case", list(_FLOW_ITEM_EOL_CASES), ids=list(_FLOW_ITEM_EOL_CASES))
def test_flow_item_eol_comment_untouched_by_unrelated_edit(tmp_path: Path, case: str) -> None:
    """EOL-комментарий непустого flow-элемента остаётся на его строке при правке другого ключа (ревью 1.1i р1, F1)."""
    raw, expected = _FLOW_ITEM_EOL_CASES[case]
    path = tmp_path / "r.yaml"
    _write(path, raw)
    before = yaml.safe_load(raw.decode("utf-8"))

    yaml_io.patch_yaml_preserving(path, before, {**before, "kb": 2})

    assert path.read_bytes() == expected


# ---------------------------------------------------------------------------
# Task 1.1i: отказ страховки записи — свой тип ``YamlWriteRefused`` (design.md §12.1)
# ---------------------------------------------------------------------------


def _dump_replaced(monkeypatch, dump) -> None:
    """Подменить ``dump`` у YAML(), который строит ``yaml_io._make_yaml``."""
    real_make = yaml_io._make_yaml

    def broken_make():
        rt = real_make()
        rt.dump = dump
        return rt

    monkeypatch.setattr(yaml_io, "_make_yaml", broken_make)


def _raise_ruamel_assert(data, stream) -> None:
    raise AssertionError("assert val == nc")


def _write_unreadable(data, stream) -> None:
    stream.write("a: b: c\n")


# id -> (исходные байты, before, after, подмена dump или None)
_SAFETY_NET_CASES = {
    "unreadable": (b"# keep\na: 1\n", {"a": 1}, {"a": 2}, _write_unreadable),
    "differs": (
        b"# keep\nmode: off_mode\nother: 1\n",
        {"mode": "off_mode", "other": 1},
        {"mode": "On", "other": 1},
        None,
    ),
    "ruamel_assert": (b"# keep\na: 1\n", {"a": 1}, {"a": 2}, _raise_ruamel_assert),
}


@pytest.mark.parametrize("case", list(_SAFETY_NET_CASES), ids=list(_SAFETY_NET_CASES))
def test_safety_net_refusal_is_yaml_write_refused(tmp_path: Path, monkeypatch, case: str) -> None:
    """Каждое место отказа страховки бросает ровно ``YamlWriteRefused`` (подкласс ``ValueError``), файл цел."""
    raw, before, after, dump = _SAFETY_NET_CASES[case]
    if dump is not None:
        _dump_replaced(monkeypatch, dump)
    path = tmp_path / "r.yaml"
    raw_before, mtime_before = _write(path, raw)

    with pytest.raises(Exception) as info:
        yaml_io.patch_yaml_preserving(path, before, after)

    exc = info.value
    assert type(exc) is yaml_io.YamlWriteRefused
    assert isinstance(exc, ValueError)
    assert not isinstance(exc, yaml_io.YamlPatchConflict)
    assert path.read_bytes() == raw_before
    assert path.stat().st_mtime_ns == mtime_before
    if case == "unreadable":
        assert 'in "<unicode string>"' not in str(exc)
        assert isinstance(exc.__cause__, yaml.YAMLError)


def test_yaml_write_refused_disjoint_from_conflict_and_format_error() -> None:
    """``YamlWriteRefused`` — подкласс ``ValueError``; с ``YamlPatchConflict``/``RecipeFormatError`` не пересекается."""
    from multiprocess_framework.modules import recipe

    refused = recipe.YamlWriteRefused
    assert refused is yaml_io.YamlWriteRefused
    assert issubclass(refused, ValueError)
    for other in (recipe.YamlPatchConflict, recipe.RecipeFormatError):
        assert not issubclass(refused, other)
        assert not issubclass(other, refused)


def test_dump_unreadable_by_pyyaml_refuses_write(tmp_path: Path) -> None:
    """Страховка записи: лист стал строкой ``"On"`` (PyYAML 1.1 читает её как bool) — ValueError, файл прежний."""
    path = tmp_path / "r.yaml"
    raw_before, mtime_before = _write(path, b"# keep\nmode: off_mode\nother: 1\n")

    with pytest.raises(ValueError):
        yaml_io.patch_yaml_preserving(path, {"mode": "off_mode", "other": 1}, {"mode": "On", "other": 1})

    assert path.read_bytes() == raw_before
    assert path.stat().st_mtime_ns == mtime_before


# ---------------------------------------------------------------------------
# Стражи под MISS матрицы инъекций лида (ревью 1.1a, раунд 1): метки новых токенов и снятый EOL
# ---------------------------------------------------------------------------

# Комментарий ``# lead`` лежит в слоте списка (``ca.items[1][1]``), а не в хвосте предыдущего
# элемента, потому что предыдущий элемент кончается пустым flow-контейнером ``meta: {}``.
# Тот же класс входа, что ``color_inspect.yaml`` (``# --- Камера ---`` после ``metadata: {}``).
_LEAD_SRC = b"p:\n  - n: gui\n    meta: {}\n  # lead\n  - a: 1\n    # inner\n    b: 2\n  - n: z\n"
_LEAD_BEFORE = {"p": [{"n": "gui", "meta": {}}, {"a": 1, "b": 2}, {"n": "z"}]}

# case -> (after, комментарии, обязанные остаться в файле ровно по одному разу)
_LEAD_CASES = {
    # Сценарий ревьюера: элемент списка с комментариями заменяется пустым mapping. До фикса р3
    # ``# lead`` и ``# inner`` выходили дважды: общий список токенов оставался в слоте списка.
    "item_emptied": ({"p": [{"n": "gui", "meta": {}}, {}, {"n": "z"}]}, ("# lead", "# inner")),
    # Элемент теряет первый ключ: заголовок элемента дописывается к слоту списка.
    "first_key_gone": ({"p": [{"n": "gui", "meta": {}}, {"b": 2}, {"n": "z"}]}, ("# lead", "# inner")),
}


@pytest.mark.parametrize("case", list(_LEAD_CASES), ids=list(_LEAD_CASES))
def test_item_with_lead_comment_edited_does_not_crash_ruamel_compare(tmp_path: Path, case: str) -> None:
    """Правка элемента списка с комментариями не роняет ruamel: файл читается PyYAML и равен after.

    Без общего списка токенов (``_share_item_header``) representer сравнивает токен слота списка
    с новым токеном заголовка и падает: ``AssertionError`` при метке ``StreamMark``,
    ``AttributeError: 'CommentMark' object has no attribute 'line'`` при метке ``CommentMark``.
    Метка ``StreamMark`` сама по себе здесь не проверяется: общий список исключает сравнение
    меток, поэтому замена одной лишь ``_mark`` на ``CommentMark`` поведение не меняет.
    """
    after, once = _LEAD_CASES[case]
    path = tmp_path / "r.yaml"
    _write(path, _LEAD_SRC)

    yaml_io.patch_yaml_preserving(path, _LEAD_BEFORE, after)

    text = path.read_text(encoding="utf-8")
    assert yaml.safe_load(text) == after
    for marker in once:
        assert text.count(marker) == 1


_SCALAR_EOL_SRC = b"a: 1\nkk: 2.5  # eol\nz: 3\n"
_SCALAR_EOL_BEFORE = {"a": 1, "kk": 2.5, "z": 3}

# case -> (after, ожидаемые байты файла)
_SCALAR_TO_CONTAINER = {
    "map": (
        {"a": 1, "kk": {"x": 1, "y": 2}, "z": 3},
        b"a: 1\nkk:\n  x: 1\n  y: 2\nz: 3\n",
    ),
    "list": (
        {"a": 1, "kk": [1, 2], "z": 3},
        b"a: 1\nkk:\n  - 1\n  - 2\nz: 3\n",
    ),
}


@pytest.mark.parametrize("case", list(_SCALAR_TO_CONTAINER), ids=list(_SCALAR_TO_CONTAINER))
def test_scalar_replaced_by_container_drops_scalar_eol_comment(tmp_path: Path, case: str) -> None:
    """Скаляр с EOL-комментарием заменён контейнером: комментарий старого значения снят.

    ``# eol`` описывал прежнее значение ``2.5``. Без снятия комментарий остаётся на строке ключа
    (``kk:      # eol``). Склейка строк из ревью 1.1a (``kk: 2.5   -``) на ruamel 0.19 не
    воспроизводится: тест страхует только снятие EOL-комментария. Ожидаемые байты заданы литералом.
    """
    after, expected = _SCALAR_TO_CONTAINER[case]
    path = tmp_path / "r.yaml"
    _write(path, _SCALAR_EOL_SRC)

    yaml_io.patch_yaml_preserving(path, _SCALAR_EOL_BEFORE, after)

    raw = path.read_bytes()
    assert yaml.safe_load(raw.decode("utf-8")) == after
    assert raw == expected


# ---------------------------------------------------------------------------
# Ревью 1.1a, раунд 2 (фикс р3): кортеж, AssertionError ruamel, заголовок элемента списка
# ---------------------------------------------------------------------------


def test_new_file_tuple_value_written_as_list(tmp_path: Path) -> None:
    """Новый файл со значением-кортежем: записан список, PyYAML читает ``[1.0, 2.0]`` (страховка не отказывает)."""
    path = tmp_path / "new.yaml"

    yaml_io.patch_yaml_preserving(path, {}, {"k": (1.0, 2.0)})

    assert yaml.safe_load(path.read_text(encoding="utf-8")) == {"k": [1.0, 2.0]}


def test_ruamel_assertion_in_dump_becomes_value_error_file_intact(tmp_path: Path, monkeypatch) -> None:
    """``AssertionError`` внутри дампа ruamel (класс ``merge_comments``) -> ``ValueError``, байты файла прежние."""
    path = tmp_path / "r.yaml"
    raw_before, _ = _write(path, b"# keep\na: 1\n")
    real_make = yaml_io._make_yaml

    def broken_make():
        rt = real_make()

        def dump(data, stream):
            raise AssertionError("assert val == nc")

        rt.dump = dump
        return rt

    monkeypatch.setattr(yaml_io, "_make_yaml", broken_make)

    with pytest.raises(ValueError):
        yaml_io.patch_yaml_preserving(path, {"a": 1}, {"a": 2})

    assert path.read_bytes() == raw_before


# Пример hypothesis для ``test_property_patch_with_comments_reaches_after`` (красный на f5b0b19ac):
# внутренняя карта первого ключа элемента списка опустела, её заголовок ушёл в заголовок элемента —
# отдельным списком токенов, не общим со слотом списка. representer ruamel падал
# ``assert val == nc`` в ``merge_comments``. Закреплён литералом, без локальной базы hypothesis.
_ITEM_HEADER_SRC = (
    b"# c0\nk:  # e1\n  # c2\n  -  # e3\n    # c4\n    k:  # e5\n      # c6\n"
    b"      k: null  # e7\n      # c8\n      ka: null  # e9\n"
)
_ITEM_HEADER_BEFORE = {"k": [{"k": {"k": None, "ka": None}}]}
_ITEM_HEADER_AFTER = {"k": [{"k": {}, "knew": 1}], "knew": 1}


def test_inner_map_of_item_emptied_reaches_after(tmp_path: Path) -> None:
    """Опустела карта первого ключа элемента списка (пример hypothesis): ruamel не падает, PyYAML читает after."""
    path = tmp_path / "r.yaml"
    _write(path, _ITEM_HEADER_SRC)

    yaml_io.patch_yaml_preserving(path, _ITEM_HEADER_BEFORE, _ITEM_HEADER_AFTER)

    assert yaml.safe_load(path.read_text(encoding="utf-8")) == {"k": [{"k": {}, "knew": 1}], "knew": 1}


def test_inner_map_of_item_emptied_keeps_comments_once(tmp_path: Path) -> None:
    """Тот же пример: каждый полнострочный комментарий входа есть в файле ровно один раз."""
    path = tmp_path / "r.yaml"
    _write(path, _ITEM_HEADER_SRC)

    yaml_io.patch_yaml_preserving(path, _ITEM_HEADER_BEFORE, _ITEM_HEADER_AFTER)

    text = path.read_text(encoding="utf-8")
    assert [text.count(f"# c{i}\n") for i in (0, 2, 4, 6, 8)] == [1, 1, 1, 1, 1]


# ---------------------------------------------------------------------------
# design §2.3 «Ключа нет в цели» (ревью 1.1e): равный в before/after ключ не создаётся
# ---------------------------------------------------------------------------


def test_absent_key_equal_in_before_after_not_created(tmp_path: Path) -> None:
    """Ключа ``m`` нет в файле, в before и after он равен: пишется только ``x``, ``m`` не появился."""
    path = tmp_path / "r.yaml"
    _write(path, b"x: 1\n")

    yaml_io.patch_yaml_preserving(path, {"x": 1, "m": {"a": 1}}, {"x": 2, "m": {"a": 1}})

    assert path.read_bytes() == b"x: 2\n"


def test_absent_nested_key_equal_in_before_after_not_created(tmp_path: Path) -> None:
    """Вложенно: ``b.metadata`` нет в файле и он равен в before/after — меняется только ``name``."""
    path = tmp_path / "r.yaml"
    _write(path, b"b:\n  name: p\n")
    meta = {"g": {"k": [1, 2]}}

    yaml_io.patch_yaml_preserving(path, {"b": {"name": "p", "metadata": meta}}, {"b": {"name": "q", "metadata": meta}})

    assert path.read_bytes() == b"b:\n  name: q\n"


def test_absent_key_missing_in_before_is_created(tmp_path: Path) -> None:
    """Страж F10: ``metadata`` нет ни в файле, ни в before — создаётся из after."""
    path = tmp_path / "r.yaml"
    _write(path, b"b:\n  name: p\n")

    yaml_io.patch_yaml_preserving(
        path, {"b": {"name": "p"}}, {"b": {"name": "p", "metadata": {"gui_positions": {"n": [1, 2]}}}}
    )

    assert path.read_bytes() == b"b:\n  name: p\n  metadata:\n    gui_positions:\n      n:\n        - 1\n        - 2\n"


def test_absent_key_none_missing_in_before_is_created(tmp_path: Path) -> None:
    """Ключа ``m`` нет ни в файле, ни в before, в after ``None``: создаётся (пропуск — только при ``key in before``)."""
    path = tmp_path / "r.yaml"
    _write(path, b"x: 1\n")

    yaml_io.patch_yaml_preserving(path, {"x": 1}, {"x": 1, "m": None})

    assert path.read_bytes() == b"x: 1\nm:\n"


def test_absent_key_changed_between_before_after_is_created(tmp_path: Path) -> None:
    """Ключ ``m`` есть в before, но after другой, а в файле его нет: создаётся со значением after."""
    path = tmp_path / "r.yaml"
    _write(path, b"x: 1\n")

    yaml_io.patch_yaml_preserving(path, {"x": 1, "m": {"a": 1}}, {"x": 1, "m": {"a": 2}})

    assert path.read_bytes() == b"x: 1\nm:\n  a: 2\n"
