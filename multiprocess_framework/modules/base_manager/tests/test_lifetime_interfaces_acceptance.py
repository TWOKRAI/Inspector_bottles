"""Независимые приёмочные тесты Task 0.1 (контракт владения в base_manager.interfaces).

Написаны вслепую, ДО реализации, только по разделам «Контракт (точная форма)» и
«Acceptance criteria» файла plans/2026-10-03_lifecycle-owner-scope/task-0.1.md.
Ожидаемые значения — литералы из спека, а не выводы из кода.

Имена импортируются внутри тестов (через _sym), чтобы сбор прошёл и каждый тест
падал сам по себе.
"""

from __future__ import annotations

import ast
import collections.abc
import dataclasses
import importlib
import inspect
import json
import multiprocessing
import pickle
import threading
import typing
from pathlib import Path

import pytest

MODULE = "multiprocess_framework.modules.base_manager.interfaces"

EMPTY = inspect.Parameter.empty
POS_OR_KW = "POSITIONAL_OR_KEYWORD"
KW_ONLY = "KEYWORD_ONLY"


def _sym(name: str):
    return getattr(importlib.import_module(MODULE), name)


def _mk(**over):
    """Собирает CloseReport из пяти обязательных полей + переопределений."""
    kw = dict(path="p", elapsed_s=0.5, survivors=(), killed=(), errors=())
    kw.update(over)
    return _sym("CloseReport")(**kw)


def _full_kwargs():
    """Отчёт со всеми полями непустыми (литералы)."""
    return dict(
        path="proc/x",
        elapsed_s=1.5,
        survivors=("a", "b"),
        killed=("c",),
        errors=(("d", "boom"),),
        emits_after_close=3,
        complete=False,
    )


def _params(func):
    """[(имя, вид, значение по умолчанию)] включая self."""
    return [(p.name, p.kind.name, p.default) for p in inspect.signature(func).parameters.values()]


def _noop():
    pass


# ---------------------------------------------------------------- экспорт

NEW_NAMES = [
    "Stoppable",
    "Resource",
    "CloseReport",
    "Reporter",
    "IHandle",
    "IScope",
    "ScopeClosedError",
]
OLD_NAMES = ["IBaseManager", "IBaseAdapter", "IObservableMixin"]


@pytest.mark.parametrize("name", NEW_NAMES)
def test_new_name_is_importable(name):
    assert getattr(importlib.import_module(MODULE), name) is not None


@pytest.mark.parametrize("name", NEW_NAMES)
def test_new_name_is_in_all(name):
    assert name in importlib.import_module(MODULE).__all__


@pytest.mark.parametrize("name", OLD_NAMES)
def test_old_name_stays_in_all(name):
    assert name in importlib.import_module(MODULE).__all__


# ---------------------------------------------------------------- Protocol-ы и псевдонимы


@pytest.mark.parametrize("name", ["Stoppable", "IHandle", "IScope"])
def test_interface_is_a_typing_protocol(name):
    assert typing.Protocol in _sym(name).__mro__


def test_resource_union_contains_stoppable():
    assert _sym("Stoppable") in typing.get_args(_sym("Resource"))


def test_resource_union_has_exactly_two_members_second_is_callable():
    args = typing.get_args(_sym("Resource"))
    assert len(args) == 2
    callables = [a for a in args if typing.get_origin(a) is collections.abc.Callable]
    assert len(callables) == 1
    # Callable[[], object]: пустой список аргументов, возврат object
    assert typing.get_args(callables[0]) == ([], object)


def test_reporter_is_callable_from_closereport_to_none():
    reporter = _sym("Reporter")
    assert typing.get_origin(reporter) is collections.abc.Callable
    params, ret = typing.get_args(reporter)
    assert params == [_sym("CloseReport")]
    # collections.abc.Callable даёт None, typing.Callable — NoneType: оба = «возврат None»
    assert ret in (None, type(None))


# ---------------------------------------------------------------- сигнатуры

SIGNATURES = [
    ("Stoppable", "request_stop", [("self", POS_OR_KW, EMPTY)]),
    ("Stoppable", "join_until", [("self", POS_OR_KW, EMPTY), ("deadline", POS_OR_KW, EMPTY)]),
    (
        "IHandle",
        "close",
        [("self", POS_OR_KW, EMPTY), ("budget_s", POS_OR_KW, None)],
    ),
    (
        "IScope",
        "own",
        [
            ("self", POS_OR_KW, EMPTY),
            ("res", POS_OR_KW, EMPTY),
            ("name", KW_ONLY, EMPTY),
            ("kind", KW_ONLY, "resource"),
        ],
    ),
    (
        "IScope",
        "child",
        [
            ("self", POS_OR_KW, EMPTY),
            ("name", POS_OR_KW, EMPTY),
            ("budget_s", KW_ONLY, None),
            ("kill_reserve_s", KW_ONLY, None),
        ],
    ),
    ("IScope", "barrier", [("self", POS_OR_KW, EMPTY)]),
    (
        "IScope",
        "spawn",
        [
            ("self", POS_OR_KW, EMPTY),
            ("target", POS_OR_KW, EMPTY),
            ("name", KW_ONLY, EMPTY),
        ],
    ),
    ("IScope", "cancel", [("self", POS_OR_KW, EMPTY)]),
    (
        "IScope",
        "close",
        [
            ("self", POS_OR_KW, EMPTY),
            ("budget_s", POS_OR_KW, None),
            ("deadline", KW_ONLY, None),
        ],
    ),
    ("IScope", "live", [("self", POS_OR_KW, EMPTY)]),
]


@pytest.mark.parametrize(
    "cls_name,method,expected",
    SIGNATURES,
    ids=[f"{c}.{m}" for c, m, _ in SIGNATURES],
)
def test_method_signature_matches_contract(cls_name, method, expected):
    assert _params(getattr(_sym(cls_name), method)) == expected


def test_stoppable_has_no_join_attribute():
    assert not hasattr(_sym("Stoppable"), "join")


@pytest.mark.parametrize("name", ["kill", "close"])
def test_stoppable_kill_and_close_are_not_protocol_members(name):
    assert not hasattr(_sym("Stoppable"), name)


# ---------------------------------------------------------------- read-only property

PROPERTIES = [
    ("IScope", "path"),
    ("IScope", "closed"),
    ("IScope", "parent"),
    ("IHandle", "path"),
    ("IHandle", "kind"),
]


@pytest.mark.parametrize("cls_name,attr", PROPERTIES, ids=[f"{c}.{a}" for c, a in PROPERTIES])
def test_attribute_is_read_only_property_in_protocol_dict(cls_name, attr):
    obj = _sym(cls_name).__dict__[attr]
    assert isinstance(obj, property)
    assert obj.fset is None


# ---------------------------------------------------------------- isinstance(…, Stoppable)


def test_isinstance_stoppable_true_for_request_stop_and_join_until():
    class Ok:
        def request_stop(self):
            return None

        def join_until(self, deadline):
            return True

    assert isinstance(Ok(), _sym("Stoppable")) is True


def test_isinstance_stoppable_false_without_join_until():
    class OnlyRequestStop:
        def request_stop(self):
            return None

    assert isinstance(OnlyRequestStop(), _sym("Stoppable")) is False


def test_isinstance_stoppable_false_for_request_stop_and_join_without_join_until():
    class OldShape:
        def request_stop(self):
            return None

        def join(self, timeout=None):
            return None

    assert isinstance(OldShape(), _sym("Stoppable")) is False


def test_isinstance_stoppable_false_for_thread_subclass_with_request_stop():
    class StoppableLookingThread(threading.Thread):
        def request_stop(self):
            return None

    assert isinstance(StoppableLookingThread(target=_noop), _sym("Stoppable")) is False


def test_isinstance_stoppable_false_for_plain_function():
    assert isinstance(_noop, _sym("Stoppable")) is False


def test_isinstance_stoppable_false_for_unstarted_thread():
    assert isinstance(threading.Thread(target=_noop), _sym("Stoppable")) is False


def test_isinstance_stoppable_false_for_unstarted_process():
    assert isinstance(multiprocessing.Process(target=_noop), _sym("Stoppable")) is False


# ---------------------------------------------------------------- CloseReport: форма


def test_closereport_field_order_is_contract_order():
    names = [f.name for f in dataclasses.fields(_sym("CloseReport"))]
    assert names == [
        "path",
        "elapsed_s",
        "survivors",
        "killed",
        "errors",
        "emits_after_close",
        "complete",
        "kind",  # поправка DTO, вердикт CTO 2026-10-05 (ADR-BM-008 «Канал счётчика»)
    ]


def test_closereport_defaults_are_zero_and_true():
    r = _mk()
    assert r.emits_after_close == 0
    assert r.complete is True


def test_closereport_is_frozen():
    r = _mk()
    with pytest.raises(dataclasses.FrozenInstanceError):
        r.path = "other"


def test_closereport_frozen_also_for_non_default_field():
    r = _mk()
    with pytest.raises(dataclasses.FrozenInstanceError):
        r.emits_after_close = 9


# ---------------------------------------------------------------- CloseReport: нормализация


def test_survivors_list_becomes_tuple():
    r = _mk(survivors=["a"])
    assert r.survivors == ("a",)
    assert type(r.survivors) is tuple


def test_killed_list_becomes_tuple():
    r = _mk(killed=["k"])
    assert r.killed == ("k",)
    assert type(r.killed) is tuple


def test_errors_list_of_lists_becomes_tuple_of_tuples():
    r = _mk(errors=[["p", "e"]])
    assert r.errors == (("p", "e"),)
    assert type(r.errors) is tuple
    assert type(r.errors[0]) is tuple


def test_report_built_from_lists_is_hashable():
    r = _mk(survivors=["a"], killed=["k"], errors=[["p", "e"]])
    assert isinstance(hash(r), int)


def test_report_built_from_lists_equals_report_built_from_tuples():
    from_lists = _mk(survivors=["a"], killed=[], errors=[["p", "e"]])
    from_tuples = _mk(survivors=("a",), killed=(), errors=(("p", "e"),))
    assert from_lists == from_tuples
    assert hash(from_lists) == hash(from_tuples)


@pytest.mark.parametrize("field", ["survivors", "killed"])
def test_string_in_place_of_sequence_raises_type_error(field):
    with pytest.raises(TypeError):
        _mk(**{field: "a"})


def test_string_in_place_of_errors_sequence_raises_type_error():
    with pytest.raises(TypeError):
        _mk(errors="pe")


def test_string_in_place_of_pair_inside_errors_raises_type_error():
    with pytest.raises(TypeError):
        _mk(errors=["pe"])


def test_triple_inside_errors_raises_type_error():
    with pytest.raises(TypeError):
        _mk(errors=[("p", "e", "x")])


def test_one_element_pair_inside_errors_raises_type_error():
    with pytest.raises(TypeError):
        _mk(errors=[("p",)])


# ---------------------------------------------------------------- CloseReport.ok


def test_ok_is_a_property():
    assert isinstance(_sym("CloseReport").__dict__["ok"], property)


def test_ok_true_for_empty_report():
    assert _mk().ok is True


def test_ok_false_with_one_survivor():
    assert _mk(survivors=("a",)).ok is False


def test_ok_false_with_one_killed():
    assert _mk(killed=("a",)).ok is False


def test_ok_false_with_one_error():
    assert _mk(errors=(("p", "e"),)).ok is False


def test_ok_false_when_incomplete():
    assert _mk(complete=False).ok is False


def test_ok_true_with_emits_after_close_five_and_nothing_else():
    assert _mk(emits_after_close=5).ok is True


# ---------------------------------------------------------------- CloseReport.to_dict

TO_DICT_KEYS = {
    "path",
    "elapsed_s",
    "survivors",
    "killed",
    "errors",
    "emits_after_close",
    "complete",
    "kind",  # поправка DTO, вердикт CTO 2026-10-05 (ADR-BM-008 «Канал счётчика»)
    "ok",
}


def test_to_dict_key_set_is_exact_for_empty_report():
    assert set(_mk().to_dict()) == TO_DICT_KEYS


def test_to_dict_key_set_is_exact_for_full_report():
    assert set(_mk(**_full_kwargs()).to_dict()) == TO_DICT_KEYS


def test_to_dict_of_empty_report_has_empty_lists():
    d = _mk().to_dict()
    assert d["survivors"] == []
    assert d["killed"] == []
    assert d["errors"] == []


def test_to_dict_full_report_equals_literal():
    d = _mk(**_full_kwargs()).to_dict()
    assert d == {
        "path": "proc/x",
        "elapsed_s": 1.5,
        "survivors": ["a", "b"],
        "killed": ["c"],
        "errors": [{"path": "d", "error": "boom"}],
        "emits_after_close": 3,
        "complete": False,
        "kind": "close",
        "ok": False,
    }


def test_to_dict_ok_key_is_true_for_empty_report():
    assert _mk().to_dict()["ok"] is True


def test_to_dict_passes_json_dumps_without_default():
    text = json.dumps(_mk(**_full_kwargs()).to_dict())
    assert json.loads(text)["errors"] == [{"path": "d", "error": "boom"}]


def test_to_dict_errors_entries_have_exactly_path_and_error_keys():
    d = _mk(errors=(("p1", "e1"), ("p2", "e2"))).to_dict()
    assert [set(e) for e in d["errors"]] == [{"path", "error"}, {"path", "error"}]


# ---------------------------------------------------------------- CloseReport.from_dict


def _minimal_dict():
    return {
        "path": "p",
        "elapsed_s": 0.5,
        "survivors": [],
        "killed": [],
        "errors": [],
    }


def test_from_dict_is_a_classmethod():
    assert isinstance(inspect.getattr_static(_sym("CloseReport"), "from_dict"), classmethod)


def test_from_dict_of_to_dict_roundtrips_full_report():
    r = _mk(**_full_kwargs())
    assert _sym("CloseReport").from_dict(r.to_dict()) == r


def test_from_dict_roundtrip_returns_closereport_instance():
    r = _mk(**_full_kwargs())
    assert type(_sym("CloseReport").from_dict(r.to_dict())) is _sym("CloseReport")


def test_from_dict_without_emits_after_close_defaults_to_zero():
    assert _sym("CloseReport").from_dict(_minimal_dict()).emits_after_close == 0


def test_from_dict_without_complete_defaults_to_true():
    assert _sym("CloseReport").from_dict(_minimal_dict()).complete is True


def test_from_dict_ignores_ok_false_on_empty_report():
    d = _minimal_dict()
    d["ok"] = False
    assert _sym("CloseReport").from_dict(d).ok is True


def test_from_dict_ignores_ok_true_when_survivors_present():
    d = _minimal_dict()
    d["survivors"] = ["a"]
    d["ok"] = True
    assert _sym("CloseReport").from_dict(d).ok is False


@pytest.mark.parametrize("missing", ["path", "elapsed_s", "survivors", "killed", "errors"])
def test_from_dict_missing_required_key_raises_value_error_naming_key(missing):
    d = _minimal_dict()
    del d[missing]
    with pytest.raises(ValueError) as exc:
        _sym("CloseReport").from_dict(d)
    assert missing in str(exc.value)


def test_from_dict_extra_key_raises_value_error_naming_key():
    d = _minimal_dict()
    d["extra"] = 1
    with pytest.raises(ValueError) as exc:
        _sym("CloseReport").from_dict(d)
    assert "extra" in str(exc.value)


def test_from_dict_missing_key_message_does_not_print_the_dict():
    d = _minimal_dict()
    d["path"] = "SECRET-VALUE-7"
    del d["survivors"]
    with pytest.raises(ValueError) as exc:
        _sym("CloseReport").from_dict(d)
    text = str(exc.value)
    assert "survivors" in text  # якорь: сообщение вообще есть и называет ключ
    assert "SECRET-VALUE-7" not in text


def test_from_dict_extra_key_message_does_not_print_the_dict():
    d = _minimal_dict()
    d["path"] = "SECRET-VALUE-7"
    d["extra"] = 1
    with pytest.raises(ValueError) as exc:
        _sym("CloseReport").from_dict(d)
    text = str(exc.value)
    assert "extra" in text  # якорь
    assert "SECRET-VALUE-7" not in text


def test_from_dict_result_is_hashable():
    d = {
        "path": "p",
        "elapsed_s": 0.5,
        "survivors": ["a"],
        "killed": ["k"],
        "errors": [{"path": "q", "error": "e"}],
    }
    assert isinstance(hash(_sym("CloseReport").from_dict(d)), int)


# ---------------------------------------------------------------- pickle


def test_closereport_pickle_roundtrip_equals_original():
    r = _mk(**_full_kwargs())
    assert pickle.loads(pickle.dumps(r)) == r


# ---------------------------------------------------------------- ScopeClosedError


def test_scope_closed_error_is_runtime_error_subclass():
    assert issubclass(_sym("ScopeClosedError"), RuntimeError)


# ---------------------------------------------------------------- interfaces.py: только stdlib

ALLOWED_IMPORTS = {
    "__future__",
    "abc",
    "collections.abc",
    "dataclasses",
    "threading",
    "typing",
}


def _imported_modules(source: str) -> list[str]:
    """Все импорты файла (включая вложенные в функции/if), относительные — с точками."""
    mods: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            mods.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            mods.append("." * node.level + (node.module or ""))
    return mods


def test_import_checker_flags_forbidden_and_relative_imports():
    # контроль самого сторожа: он обязан видеть чужой модуль в любой форме
    src = "import os\nfrom json import dumps\nfrom . import sibling\nimport typing\n"
    forbidden = [m for m in _imported_modules(src) if m not in ALLOWED_IMPORTS]
    assert forbidden == ["os", "json", "."]


def test_interfaces_py_imports_only_allowed_stdlib_modules():
    path = Path(__file__).resolve().parent.parent / "interfaces.py"
    mods = _imported_modules(path.read_text(encoding="utf-8"))
    assert mods, "interfaces.py без единого импорта — проверка пуста"
    assert [m for m in mods if m not in ALLOWED_IMPORTS] == []
