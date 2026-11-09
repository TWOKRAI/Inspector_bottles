"""Слепые приёмочные тесты индекса связей `scripts/atlas/links.py` (Task 4.1, stage 1, RED до кода).

Purpose: `build_links({путь: FileFacts})` -> `Links.of("путь::qualname")`: `used_by`, `call_sites`
    (+ `call_sites_unresolved`), `subclasses`, `structural`, `tests`; поле `scope` у каждой записи. Контракт —
    докстринг `scripts/atlas/links.py`; реализации при записи тестов нет.
Public API: тесты test_*; публичных имён нет.
Stability: lite

Входные факты — `scan_text(исходник)` по фикстурам-строкам (ровно то, что отдаёт `scan(...).facts`); диск, git и
`data/` не нужны. Номера строк берутся маркером `# @имя` в тексте фикстуры. Построение и опрос индекса идут в
daemon-потоке с дедлайном (цикл по цепочке основ не должен вешать прогон). Ожидаемые значения — литералы.
"""

from __future__ import annotations

from scripts.atlas.tests.conftest import run_with_deadline

__all__: list[str] = []

DEADLINE_S = 30.0


def _links(files: dict[str, str]):
    from scripts.atlas.links import build_links
    from scripts.atlas.scan import scan_text

    return run_with_deadline(lambda: build_links({p: scan_text(s) for p, s in files.items()}), DEADLINE_S)


def _of(links, ident: str):
    return run_with_deadline(lambda: links.of(ident), DEADLINE_S)


def _at(files: dict[str, str], path: str, marker: str) -> str:
    """`путь:строка` места с маркером `# @marker` в фикстуре `path` (ровно одно)."""
    hits = [i for i, text in enumerate(files[path].splitlines(), 1) if text.rstrip().endswith(f"# @{marker}")]
    assert len(hits) == 1, f"маркер {marker!r} в {path}: строк {len(hits)}"
    return f"{path}:{hits[0]}"


def _pad(src: str, lines: int = 9) -> str:
    """Сдвиг на `lines` строк: все номера строк двузначные, порядок «по where» не зависит от сортировки строк."""
    return "#\n" * lines + src


# ---------------------------------------------------------------- 6. F2: вызов в том же файле

_F2 = {  # порядок словаря нарочно не совпадает с порядком ответа: other.py идёт раньше mod.py
    "pkg/__init__.py": "",
    "pkg/other.py": _pad(
        """\
from pkg.mod import write_companion


def run():
    write_companion(4)  # @other
"""
    ),
    "pkg/mod.py": _pad(
        """\
def write_companion(x):
    return x


def persist_session():
    write_companion(1)  # @same_fn


class Svc:
    def save(self):
        write_companion(2)  # @same_method


write_companion(3)  # @same_module
"""
    ),
}


def test_same_file_call_site_listed_with_enclosing():
    """F2: вызов символа в его же файле — в `call_sites` (`same_file: True`, `enclosing` — qualname вызывающего:
    функция, метод, `<module>`); вызов из другого файла по from-импорту — тоже, `same_file: False`;
    порядок записей — по `(where, line)`; сам `def` не вызов."""
    links = _links(_F2)
    res = _of(links, "pkg/mod.py::write_companion")
    assert res is not None
    at = lambda p, m: _at(_F2, p, m)  # noqa: E731
    expected = [
        {
            "where": at("pkg/mod.py", "same_fn"),
            "how": "name-call",
            "scope": "prod",
            "enclosing": "persist_session",
            "same_file": True,
        },
        {
            "where": at("pkg/mod.py", "same_method"),
            "how": "name-call",
            "scope": "prod",
            "enclosing": "Svc.save",
            "same_file": True,
        },
        {
            "where": at("pkg/mod.py", "same_module"),
            "how": "name-call",
            "scope": "prod",
            "enclosing": "<module>",
            "same_file": True,
        },
        {
            "where": at("pkg/other.py", "other"),
            "how": "name-call",
            "scope": "prod",
            "enclosing": "run",
            "same_file": False,
        },
    ]
    assert res["call_sites"] == expected
    assert res["call_sites_unresolved"] == 0
    assert _of(links, "pkg/mod.py::no_such_symbol") is None  # символ без записи в defs


# ---------------------------------------------------------------- 7. что разрешается

_RESOLVE = {
    "lib.py": """\
def f():
    pass


class K:
    def m(self):
        pass

    def run(self):
        self.m()  # @k_self


class J:
    def m(self):
        pass

    def run(self):
        self.m()  # @j_self


def own():
    f()  # @own
""",
    "a.py": """\
from lib import f


def u1():
    f()  # @a_from
""",
    "b.py": """\
import lib


def u2():
    lib.f()  # @b_module
""",
    "e.py": """\
def u5(x):
    x.f()  # @e_unknown_receiver
""",
    "s.py": """\
def f():
    pass


def u7():
    f()  # @s_shadow
""",
    "pkg/__init__.py": "from lib import f\n",
    "r.py": """\
from pkg import f


def u6():
    f()  # @r_reexport
""",
}


def test_call_sites_resolve_by_import_or_self_only():
    """Разрешаются: голое имя в своём файле, голое имя по `from m import f`, `m.f()` по `import m`, `self.m()` внутри
    класса символа. Не разрешаются и не считаются: вызовы по алиасу (`as`) и через реэкспорт `__init__`;
    собственный `f` другого файла — не `lib.f`. `x.f()` по произвольному получателю — только счётчик.
    Алиасы (`import lib as L`, `from lib import f as g`) здесь НЕ проверяются: `ImportRec` алиас не хранит, из фактов
    файла `L.f()` не отличить от `x.f()` (см. отчёт tester: граница «не видно» из контракта не наблюдаема)."""
    links = _links(_RESOLVE)
    at = lambda p, m: _at(_RESOLVE, p, m)  # noqa: E731

    res = _of(links, "lib.py::f")
    assert res is not None
    expected_f = [
        {"where": at("a.py", "a_from"), "how": "name-call", "scope": "prod", "enclosing": "u1", "same_file": False},
        {"where": at("b.py", "b_module"), "how": "name-call", "scope": "prod", "enclosing": "u2", "same_file": False},
        {"where": at("lib.py", "own"), "how": "name-call", "scope": "prod", "enclosing": "own", "same_file": True},
    ]
    assert res["call_sites"] == expected_f
    # `x.f()` из e.py — единственное «совпало имя, не отнесено»: реэкспорт (r.py) и собственный `f` в s.py
    # (s.py::f, а не lib.f) сюда не попадают
    assert res["call_sites_unresolved"] == 1
    assert isinstance(res["call_sites_unresolved"], int)

    # self.m() — только метод своего класса
    k_m = _of(links, "lib.py::K.m")
    j_m = _of(links, "lib.py::J.m")
    assert k_m is not None and j_m is not None
    assert k_m["call_sites"] == [
        {"where": at("lib.py", "k_self"), "how": "name-call", "scope": "prod", "enclosing": "K.run", "same_file": True}
    ]
    assert j_m["call_sites"] == [
        {"where": at("lib.py", "j_self"), "how": "name-call", "scope": "prod", "enclosing": "J.run", "same_file": True}
    ]


# ---------------------------------------------------------------- 8. scope у каждой записи

_IMPORT_SYMBOL = "from pkg.core import Base\n"
_USER = (
    _IMPORT_SYMBOL
    + """

class Sub(Base):
    pass


def go():
    Base()
"""
)
_SCOPE = {
    "pkg/__init__.py": "",
    "pkg/core.py": "class Base:\n    pass\n",
    # test: каталог tests/ на любой глубине; test_*.py; *_test.py; conftest.py
    "tests/test_core.py": _USER + "\n\ndef test_base():\n    Base()\n",
    "pkg/tests/helpers.py": _USER,
    "conftest.py": _USER,
    "pkg/test_x.py": _USER + "\n\ndef test_x():\n    Base()\n",
    "pkg/x_test.py": _USER + "\n\ndef test_y():\n    Base()\n",
    # prod: обычные файлы, `testing/` (поставляемые двойники), имена-близнецы без границы каталога/суффикса
    "pkg/mod.py": _USER,
    "testing/fake.py": _USER,
    "contests/x.py": _USER,
    "pkg/contest.py": _USER,
}
_SCOPE_EXPECTED = {
    "tests/test_core.py": "test",
    "pkg/tests/helpers.py": "test",
    "conftest.py": "test",
    "pkg/test_x.py": "test",
    "pkg/x_test.py": "test",
    "pkg/mod.py": "prod",
    "testing/fake.py": "prod",
    "contests/x.py": "prod",
    "pkg/contest.py": "prod",
}


def test_every_link_has_scope_prod_or_test():
    """У каждой записи любого раздела `scope` — `test` для `(^|/)tests/`, `test_*.py`, `*_test.py`, `conftest.py`
    (помощники внутри `tests/` — тоже тест), иначе `prod` (`testing/` и `contests/` — prod)."""
    res = _of(_links(_SCOPE), "pkg/core.py::Base")
    assert res is not None
    for section in ("used_by", "subclasses", "call_sites"):
        scopes: dict[str, set[str]] = {}
        for entry in res[section]:
            scopes.setdefault(entry["where"].rsplit(":", 1)[0], set()).add(entry["scope"])
        # на файл — ровно один scope (у файла с тестами несколько вызовов в call_sites), и он ожидаемый
        expected = {path: [scope] for path, scope in _SCOPE_EXPECTED.items()}
        assert {path: sorted(sc) for path, sc in scopes.items()} == expected, section
    assert len(res["used_by"]) == len(res["subclasses"]) == len(_SCOPE_EXPECTED)
    # `tests` — всегда scope test, по одной записи на тест-функцию
    tests = res["tests"]
    assert sorted(e["where"].rsplit(":", 1)[0] for e in tests) == [
        "pkg/test_x.py",
        "pkg/x_test.py",
        "tests/test_core.py",
    ]
    assert {e["scope"] for e in tests} == {"test"}
    assert {e["how"] for e in tests} == {"test-body"}


# ---------------------------------------------------------------- 9. structural

_PROTO = {
    "pkg/__init__.py": "",
    "pkg/proto.py": """\
from abc import ABC, abstractmethod
from typing import Protocol


class IOne(Protocol):
    def only(self): ...


class IMix(Protocol):
    def one(self): ...
    def _private(self): ...
    def __len__(self): ...


class ITwo(Protocol):
    def read(self): ...
    def write(self): ...
    def _hidden(self): ...
    def __enter__(self): ...


class IAbc(ABC):
    @abstractmethod
    def run(self): ...

    @abstractmethod
    def stop(self): ...


def helper():
    pass
""",
    "pkg/impl.py": """\
from pkg.proto import ITwo


class Good:
    def read(self): ...
    def write(self): ...
    def close(self): ...


class Child(ITwo):
    def read(self): ...
    def write(self): ...


class _Private:
    def read(self): ...
    def write(self): ...


class Partial:
    def read(self): ...


class Anyone:
    def only(self): ...
    def one(self): ...


class Runner:
    def run(self): ...
    def stop(self): ...
""",
    "pkg/duck.py": """\
class Duck:
    def write(self): ...
    def read(self): ...
""",
}


def test_single_member_protocol_structural_null():
    """F7: обязательные имена — неприватные не-dunder методы основы; меньше двух -> `structural is None` и
    «слишком общий протокол» в `note` (приватный/dunder не считаются). Двойник — неприватный класс со всеми
    обязательными методами, не наследующий основу (наследник и `_Private` — не двойники); идентификатор
    `путь::qualname`. Раздела `structural` у функции нет."""
    res_of = lambda name: _of(links, f"pkg/proto.py::{name}")  # noqa: E731
    links = _links(_PROTO)

    two = res_of("ITwo")
    assert two is not None
    assert two["structural"] is not None
    assert two["structural"]["required"] == ["read", "write"]
    assert sorted(two["structural"]["twins"]) == ["pkg/duck.py::Duck", "pkg/impl.py::Good"]

    abc = res_of("IAbc")
    assert abc is not None and abc["structural"] is not None
    assert abc["structural"]["required"] == ["run", "stop"]
    assert abc["structural"]["twins"] == ["pkg/impl.py::Runner"]

    for name in ("IOne", "IMix"):  # `Anyone` имеет `only` и `one`, но протокол слишком общий — двойников нет
        res = res_of(name)
        assert res is not None, name
        assert res["structural"] is None, name
        assert "слишком общий протокол" in str(res.get("note")), name

    func = res_of("helper")
    assert func is not None
    assert "structural" not in func


# ---------------------------------------------------------------- 10. tests по символу

_TESTS = {
    "pkg/__init__.py": "",
    "pkg/core.py": """\
def calc_x():
    pass


def calc_y():
    pass


def calc_z():
    pass
""",
    "tests/__init__.py": "",
    "tests/test_core.py": """\
from pkg.core import calc_x, calc_y


def test_a():
    calc_x()


class TestK:
    def test_c(self):
        calc_x()
        calc_y()


def test_e():
    calc_x()
    calc_x()


def test_d():
    unrelated()


def make_data():
    calc_x()
""",
    "tests/test_other.py": """\
def test_z():
    calc_x()
""",
    "pkg/user.py": """\
from pkg.core import calc_x


def use():
    calc_x()
""",
}


def test_tests_by_symbol_count_test_functions_naming_it():
    """`tests`: по одной записи на тест-функцию (`test_defs`), в чьём теле символ назван и чей файл импортирует файл
    символа. X -> 3 (`test_a`, `TestK.test_c`, `test_e` с двумя вызовами — один тест); Y -> 1; не тесты
    (`make_data`, `pkg/user.py::use`) и файл без импорта (`test_other.py`) не считаются; нетронутый символ -> []."""
    from scripts.atlas.scan import scan_text

    # входной факт: test_defs — (qualname, строка) только функций test* и методов test* в Test*
    assert scan_text(_TESTS["tests/test_core.py"]).test_defs == (
        ("test_a", 4),
        ("TestK.test_c", 9),
        ("test_e", 14),
        ("test_d", 19),
    )

    links = _links(_TESTS)
    x = _of(links, "pkg/core.py::calc_x")
    y = _of(links, "pkg/core.py::calc_y")
    z = _of(links, "pkg/core.py::calc_z")
    assert x is not None and y is not None and z is not None
    assert len(x["tests"]) == 3
    assert sorted(e["enclosing"] for e in x["tests"]) == ["TestK.test_c", "test_a", "test_e"]
    assert {(e["where"].rsplit(":", 1)[0], e["how"], e["scope"]) for e in x["tests"]} == {
        ("tests/test_core.py", "test-body", "test")
    }
    assert len(y["tests"]) == 1
    assert y["tests"][0]["enclosing"] == "TestK.test_c"
    assert z["tests"] == []
