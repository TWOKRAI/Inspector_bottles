"""Слепые приёмочные тесты Task 5.9a, часть A: валидатор моделирует проход ключа.

Контракт (plans/transport-single-policy/phase-5.md, Task 5.9a, DESIGN п.1-6):

* рантайм передаёт между плагинами процесса ОДИН dict: ключ живёт до перезаписи,
  поэтому вход узла i покрыт, если ИМЯ его порта есть среди
  ``wired_inputs`` процесса ∪ выходов узлов 0…i-1, и порт совместим с ПОСЛЕДНИМ
  производителем этого имени;
* ``available_keys(chain, *, wired_inputs=()) -> dict[str, Port]`` — одна функция
  для ``validate_chain`` и для ``blueprint._is_covered_by_auto_wiring``;
* ``validate_chain(chain, *, wired_inputs=())`` — keyword-only параметр, старые
  вызовы без него работают;
* имя из провода даёт ``Port(dtype="any")``;
* один вход — одна ошибка; два текста ошибки (нет ключа / ключ несовместим).

Тесты написаны ДО реализации и без доступа к ней. Ожидаемые значения — литералы.
Часть тестов зелёная уже сегодня: они фиксируют то, что реализация не вправе
сломать (старый формат «несовместим», optional, позиционный вызов).

``available_keys`` берётся через атрибут модуля, а не ``from ... import``: пока
символа нет, краснеют только тесты на него (``AttributeError``), а не вся
коллекция файла.
"""

from __future__ import annotations

import inspect

import pytest

from ..plugins import port as port_mod

Port = port_mod.Port
validate_chain = port_mod.validate_chain


def _bgr(name: str, *, optional: bool = False) -> Port:
    return Port(name=name, dtype="image/bgr", shape="(H, W, 3)", optional=optional)


def _gray(name: str, *, optional: bool = False) -> Port:
    return Port(name=name, dtype="image/gray", shape="(H, W)", optional=optional)


def _mask_producer_and_frame_consumer() -> list:
    """A выдаёт ``mask`` (gray); B требует ``frame`` (bgr)."""
    return [
        ("A", [], [_gray("mask")]),
        ("B", [_bgr("frame")], []),
    ]


# --------------------------------------------------------------------------- провод процесса


def test_wired_name_covers_required_input_without_producer_above() -> None:
    """A выдаёт mask, B требует frame, провод процесса приносит ``frame`` -> 0 ошибок."""
    errors = validate_chain(_mask_producer_and_frame_consumer(), wired_inputs=("frame",))
    assert errors == []


def test_without_wire_required_input_is_exactly_one_error_naming_key_and_node() -> None:
    """Та же цепочка без провода -> ровно одна ошибка с ``'frame'`` и именем узла B."""
    errors = validate_chain(_mask_producer_and_frame_consumer(), wired_inputs=())
    assert len(errors) == 1, errors
    assert "'frame'" in errors[0], errors[0]
    assert "B" in errors[0], errors[0]


def test_key_absent_error_uses_the_design_text_a_literally() -> None:
    """DESIGN п.4(а): текст «ключа нет» дословно (в validate_chain — без префикса процесса)."""
    errors = validate_chain(_mask_producer_and_frame_consumer(), wired_inputs=())
    assert errors == [
        "Вход 'B.frame' (image/bgr) не подключен: "
        "ключ 'frame' не производит ни провод процесса, ни узел выше по цепочке"
    ], errors


def test_key_absent_error_is_not_reported_as_incompatibility() -> None:
    """Ключа нет вовсе — это НЕ «несовместим» (п.4(б) — только для ключа, который есть)."""
    errors = validate_chain(_mask_producer_and_frame_consumer(), wired_inputs=())
    assert len(errors) == 1, errors
    assert "несовместим" not in errors[0], errors[0]


# --------------------------------------------------------------------------- проход ключа


def test_key_passes_through_a_node_that_does_not_reemit_it() -> None:
    """A выдаёт frame; B берёт frame и выдаёт только mask; C снова требует frame.

    Рантайм — dict: frame из A жив к моменту C. Сегодня валидатор смотрит только
    на B (выход ``mask``) и ругается на C.
    """
    chain = [
        ("A", [], [_bgr("frame")]),
        ("B", [_bgr("frame")], [_gray("mask")]),
        ("C", [_bgr("frame")], []),
    ]
    assert validate_chain(chain) == []


def test_required_key_is_matched_by_name_not_by_dtype_alone() -> None:
    """A выдаёт ``other`` (image/bgr), B требует ``frame`` (image/bgr).

    dtype совпал, имя — нет. Рантайм достаёт ключ по имени, поэтому ``frame`` взять
    неоткуда. Сравнение только по dtype оставило бы инъекцию «у источника убран
    frame» зелёной, пока выше есть любой другой image/bgr.
    """
    chain = [
        ("A", [], [_bgr("other")]),
        ("B", [_bgr("frame")], []),
    ]
    errors = validate_chain(chain)
    assert len(errors) == 1, errors
    assert "'frame'" in errors[0], errors[0]
    assert "B" in errors[0], errors[0]


def test_last_producer_of_a_name_decides_compatibility() -> None:
    """A: frame bgr; B перезаписывает frame как gray; C требует frame bgr -> ошибка на B.

    Ключ есть, но последний производитель (B) несовместим. Реализация, берущая
    ПЕРВОГО производителя (A, bgr), промолчала бы.
    """
    chain = [
        ("A", [], [_bgr("frame")]),
        ("B", [_bgr("frame")], [_gray("frame")]),
        ("C", [_bgr("frame")], []),
    ]
    errors = validate_chain(chain)
    assert len(errors) == 1, errors
    assert "B" in errors[0], errors[0]
    assert "несовместим" in errors[0], errors[0]


# --------------------------------------------------------------------------- optional / несовместимый


def test_optional_input_absent_upstream_is_not_an_error() -> None:
    """B требует frame и имеет optional ``mask``; A выдаёт только frame -> 0 ошибок."""
    chain = [
        ("A", [], [_bgr("frame")]),
        ("B", [_bgr("frame"), _gray("mask", optional=True)], []),
    ]
    assert validate_chain(chain) == []


def test_key_present_but_incompatible_keeps_the_old_error_format() -> None:
    """gray_source(frame:image/gray) -> needs_bgr(frame:image/bgr): одна ошибка, прежний формат."""
    chain = [
        ("gray_source", [], [Port(name="frame", dtype="image/gray", shape="(H, W, 1)")]),
        ("needs_bgr", [Port(name="frame", dtype="image/bgr", shape="(H, W, 3)")], []),
    ]
    errors = validate_chain(chain)
    assert len(errors) == 1, errors
    assert "gray_source" in errors[0], errors[0]
    assert "несовместим" in errors[0], errors[0]


# --------------------------------------------------------------------------- одна ошибка на вход


def test_two_unsatisfied_inputs_give_exactly_two_errors_one_per_input() -> None:
    """B требует frame (bgr) и depth (gray); у A есть только mask (gray).

    Ни frame, ни depth по имени неоткуда взять -> ровно две ошибки, по одной на вход.
    (По dtype depth совпал бы с mask — сегодняшняя ошибка одна.)
    """
    chain = [
        ("A", [], [_gray("mask")]),
        ("B", [_bgr("frame"), _gray("depth")], []),
    ]
    errors = validate_chain(chain)
    assert len(errors) == 2, errors
    assert sum("'frame'" in e for e in errors) == 1, errors
    assert sum("'depth'" in e for e in errors) == 1, errors


# --------------------------------------------------------------------------- сигнатура


def test_old_positional_call_without_wired_inputs_still_works() -> None:
    """Старый вызов ``validate_chain(chain)`` — без изменений (0 ошибок на совместимой цепочке)."""
    chain = [
        ("A", [], [_bgr("frame")]),
        ("B", [_bgr("frame")], []),
    ]
    assert validate_chain(chain) == []


def test_wired_inputs_passed_positionally_is_a_type_error() -> None:
    """``wired_inputs`` — keyword-only: вторым позиционным аргументом -> TypeError."""
    with pytest.raises(TypeError):
        validate_chain(_mask_producer_and_frame_consumer(), ("frame",))  # type: ignore[call-arg]


def test_validate_chain_wired_inputs_is_keyword_only_with_empty_default() -> None:
    """Сигнатура, а не только TypeError: сегодня TypeError даёт и «нет параметра вовсе»."""
    param = inspect.signature(validate_chain).parameters["wired_inputs"]
    assert param.kind is inspect.Parameter.KEYWORD_ONLY
    assert param.default == ()


@pytest.mark.parametrize(
    "make_wired",
    [
        pytest.param(lambda: ["frame"], id="list"),
        pytest.param(lambda: {"frame"}, id="set"),
        pytest.param(lambda: frozenset({"frame"}), id="frozenset"),
        pytest.param(lambda: (n for n in ("frame",)), id="generator"),
    ],
)
def test_wired_inputs_accepts_any_iterable_of_names(make_wired) -> None:
    """Контракт ``Iterable[str]``: одноразовый генератор тоже годится (цепочка из 2 узлов)."""
    chain = [
        ("A", [], [_gray("mask")]),
        ("B", [_bgr("frame")], []),
        ("C", [_bgr("frame")], []),
    ]
    assert validate_chain(chain, wired_inputs=make_wired()) == []


# --------------------------------------------------------------------------- available_keys


def test_available_keys_maps_a_wired_name_to_a_dtype_any_port() -> None:
    """Имя из провода -> ``Port(name=<имя>, dtype="any")`` (dtype провода сверен циклом Wire)."""
    chain = [("A", [], [_gray("mask")]), ("B", [_bgr("frame")], [])]
    keys = port_mod.available_keys(chain, wired_inputs=("frame",))
    assert keys["frame"].dtype == "any"
    assert keys["frame"].name == "frame"


def test_available_keys_contains_upstream_outputs_with_their_own_port() -> None:
    """Выход узла выше попадает в множество со своим портом (dtype не затёрт на any)."""
    chain = [("A", [], [_gray("mask")]), ("B", [_bgr("frame")], [])]
    keys = port_mod.available_keys(chain)
    assert keys["mask"].dtype == "image/gray"


def test_available_keys_does_not_invent_a_name_nobody_produces() -> None:
    """Без провода и без производителя имени ``frame`` в множестве нет."""
    chain = [("A", [], [_gray("mask")]), ("B", [_bgr("frame")], [])]
    keys = port_mod.available_keys(chain)
    assert "frame" not in keys


def test_available_keys_last_producer_of_a_name_wins() -> None:
    """Два узла выдают ``frame`` (bgr, потом gray); третий — приёмник -> в множестве gray."""
    chain = [
        ("A", [], [_bgr("frame")]),
        ("B", [], [_gray("frame")]),
        ("C", [_bgr("frame")], []),
    ]
    keys = port_mod.available_keys(chain)
    assert keys["frame"].dtype == "image/gray"


def test_available_keys_wired_inputs_is_keyword_only() -> None:
    """``available_keys(chain, ("frame",))`` -> TypeError (keyword-only, как у validate_chain)."""
    chain = [("A", [], [_gray("mask")])]
    with pytest.raises(TypeError):
        port_mod.available_keys(chain, ("frame",))
