"""Тесты автора Task 4.6b: поля класса в `members` паспорта и привязки модуля в `map <файл>` — REDS 1-10.

Purpose: красные до правки `passport.py` (REDS 1, 2, 3, 6-10), защиты REDS 4, 5 зелёные до и после. Фикстура — три
    файла `pkg/s.py`, `pkg/m.py`, `pkg/many.py` дословно по `tasks/4.6b.md` (REDS); номера строк — литералы по тексту
    фикстуры, самопроверка — `test_fixture_line_numbers`. Слепой набор — `test_passport_fields_blind_4_6b.py`
    (здесь не читается и не правится).
Public API: тесты test_*; публичных имён нет.
Stability: lite

Хелперы — из `conftest.py` (`RepoFactory`) и `test_passport_status.py` (`_commit`, `_build`, `_render`, `_lines`);
`map` — `test_passport_map.py` (`_build` как `_map_build`, `_registry`, `_row`). Ожидаемые значения — литералы,
не вывод кода под тестом.
"""

from __future__ import annotations

import ast

import pytest

from scripts.atlas.tests.conftest import GitRepo, RepoFactory
from scripts.atlas.tests.test_passport_map import _build as _map_build
from scripts.atlas.tests.test_passport_map import _registry, _row
from scripts.atlas.tests.test_passport_status import _build, _commit, _lines, _render

__all__: list[str] = []

_S = "\n".join(
    [
        '"""Схемы."""',  # 1
        "",  # 2
        "",  # 3
        "class Plain:",  # 4
        "    a: int",  # 5
        '    b: str = "x"',  # 6
        "    C = 3",  # 7
        "    _PRIV = 1",  # 8
        "",  # 9
        "",  # 10
        "class Big:",  # 11
        *[f"    f{k}: int = {k}" for k in range(1, 10)],  # 12-20
        "",  # 21
        "",  # 22
        "class Mixed:",  # 23
        "    n: int = 0",  # 24
        "    m: int = 1",  # 25
        "",  # 26
        "    def run(self) -> None:",  # 27
        "        pass",  # 28
        "",  # 29
        "",  # 30
        "class Empty:",  # 31
        "    pass",  # 32
        "",  # 33
        "",  # 34
        "class Priv:",  # 35
        "    x = 1",  # 36
        "    _h = None",  # 37
        "    Meta = None",  # 38
        "",  # 39
        "    def _h(self) -> None:",  # 40
        "        pass",  # 41
        "",  # 42
        "    class Meta:",  # 43
        "        pass",  # 44
        "",
    ]
)

_M = "\n".join(
    [
        '__all__ = ["A", "f"]',  # 1
        "_PRIV = 1",  # 2
        "LIMIT: int = 16",  # 3
        "type Alias = int | str",  # 4
        "type Gen[T] = list[T]",  # 5
        "",  # 6
        "",  # 7
        "class A:",  # 8
        "    pass",  # 9
        "",  # 10
        "",  # 11
        "def f() -> None:",  # 12
        "    pass",  # 13
        "",  # 14
        "",  # 15
        "f = 1",  # 16
        "",
    ]
)

_MANY = "\n".join(
    [
        *[f"K{k} = {k}" for k in range(10)],  # 1-10
        "",  # 11
        "",  # 12
        "def a() -> None:",  # 13
        "    pass",  # 14
        "",  # 15
        "",  # 16
        "def b() -> None:",  # 17
        "    pass",  # 18
        "",  # 19
        "",  # 20
        "class C:",  # 21
        "    pass",  # 22
        "",
    ]
)

_FILES = {
    "modules.yaml": _registry(_row("pkg", "pkg/", purpose="Пакет.")),
    "pkg/__init__.py": "",
    "pkg/s.py": _S,
    "pkg/m.py": _M,
    "pkg/many.py": _MANY,
}


@pytest.fixture(scope="module")
def fx(tmp_path_factory: pytest.TempPathFactory) -> GitRepo:
    """Один репозиторий на модуль: тесты только читают его."""
    repo = RepoFactory(tmp_path_factory.mktemp("fields")).create("repo")
    _commit(repo, _FILES)
    return repo


def _members(fx: GitRepo, ident: str) -> list[dict]:
    return _build(fx, ident)["interface"]["members"]


def _block(text: str) -> list[str]:
    """Строки текста от заголовка `  members...` до строки перед `links:` (заголовок входит)."""
    lines = _lines(text)
    start = next(i for i, line in enumerate(lines) if line.startswith("  members"))
    end = next(i for i in range(start + 1, len(lines)) if lines[i].startswith("links:"))
    return lines[start:end]


def test_fixture_line_numbers() -> None:
    """Контроль фикстуры: номера строк из REDS совпадают с текстом."""
    s, m, many = _S.splitlines(), _M.splitlines(), _MANY.splitlines()
    assert s[3] == "class Plain:" and s[4] == "    a: int" and s[7] == "    _PRIV = 1"
    assert s[10] == "class Big:" and s[11] == "    f1: int = 1" and s[19] == "    f9: int = 9"
    assert s[22] == "class Mixed:" and s[26] == "    def run(self) -> None:" and s[30] == "class Empty:"
    assert s[34] == "class Priv:" and s[35] == "    x = 1" and s[39] == "    def _h(self) -> None:"
    assert s[42] == "    class Meta:"
    assert m[0].startswith("__all__") and m[7] == "class A:" and m[11] == "def f() -> None:" and m[15] == "f = 1"
    assert many[0] == "K0 = 0" and many[9] == "K9 = 9" and many[12] == "def a() -> None:"
    assert many[16] == "def b() -> None:" and many[20] == "class C:"


# ---------------------------------------------------------------- RED 1-3: поля класса без публичных методов


def test_fields_only_class_members_json(fx: GitRepo) -> None:
    """`Plain` (4 привязки, методов нет): `members` — поля по строке, `signature` формы 4.6a, приватное `_PRIV` тоже."""
    assert _members(fx, "pkg/s.py::Plain") == [
        {"name": "a", "signature": ": int", "where": "pkg/s.py:5"},
        {"name": "b", "signature": ": str = 'x'", "where": "pkg/s.py:6"},
        {"name": "C", "signature": "= 3", "where": "pkg/s.py:7"},
        {"name": "_PRIV", "signature": "= 1", "where": "pkg/s.py:8"},
    ]


def test_fields_only_class_text(fx: GitRepo) -> None:
    """Заголовок `публичных методов нет; полей 4:` и строки `<имя><sig>  :<строка>` (`:` приклеивается к имени)."""
    assert _block(_render(_build(fx, "pkg/s.py::Plain"), full=True)) == [
        "  members: публичных методов нет; полей 4:",
        "    a: int  :5",
        "    b: str = 'x'  :6",
        "    C = 3  :7",
        "    _PRIV = 1  :8",
    ]


def test_fields_cut_min3_and_full(fx: GitRepo) -> None:
    """`Big`, бюджет 10: три поля и `ещё 6; --full`; `full=True` — 9 строк, последняя `f9: int = 9  :20`."""
    cut = _block(_render(_build(fx, "pkg/s.py::Big"), budget=10))
    assert cut == [
        "  members: публичных методов нет; полей 9:",
        "    f1: int = 1  :12",
        "    f2: int = 2  :13",
        "    f3: int = 3  :14",
        "    ещё 6; --full",
    ]
    full = _block(_render(_build(fx, "pkg/s.py::Big"), full=True))
    assert len(full) == 10 and full[-1] == "    f9: int = 9  :20"


# ---------------------------------------------------------------- RED 4, 5: защиты (зелёные до и после)


def test_class_with_methods_unchanged(fx: GitRepo) -> None:
    """Защита: `Mixed` (поля `n`, `m` + публичный `run`) — только метод, поля не добавляются (убивает «поля всегда»)."""
    assert _members(fx, "pkg/s.py::Mixed") == [{"name": "run", "signature": "() -> None", "where": "pkg/s.py:27"}]
    assert _block(_render(_build(fx, "pkg/s.py::Mixed"), full=True)) == ["  members:", "    run() -> None  :27"]


def test_empty_class_still_dash(fx: GitRepo) -> None:
    """Защита: пустой класс — `[]` и `  members: —`."""
    assert _members(fx, "pkg/s.py::Empty") == []
    assert _block(_render(_build(fx, "pkg/s.py::Empty"), full=True)) == ["  members: —"]


# ---------------------------------------------------------------- RED 6: имена `defs` у класса не поля


def test_private_methods_class_lists_fields_not_defs(fx: GitRepo) -> None:
    """`Priv`: только приватный метод `_h` и вложенный класс `Meta` -> поля; имена `_h` (метод) и `Meta` (класс) —
    не поля, хотя `_h = None` и `Meta = None` есть в теле: побеждает `DefFact`."""
    assert _members(fx, "pkg/s.py::Priv") == [{"name": "x", "signature": "= 1", "where": "pkg/s.py:36"}]


# ---------------------------------------------------------------- RED 7, 8: привязки в `map <файл>`


def test_map_file_text_bindings_by_line(fx: GitRepo) -> None:
    """`map pkg/m.py`: привязки модуля и class/def — по строке; `f = 1` (:16) после `def f` — строки нет."""
    assert _block(_render(_map_build(fx, "pkg/m.py"), full=True)) == [
        "  members:",
        "    __all__ = ['A', 'f']  :1",
        "    _PRIV = 1  :2",
        "    LIMIT: int = 16  :3",
        "    Alias type = int | str  :4",
        "    Gen type[T] = list[T]  :5",
        "    class A  :8",
        "    def f() -> None  :12",
    ]


def test_map_file_json_bindings(fx: GitRepo) -> None:
    """JSON `map pkg/m.py`: имена по строке, записи привязок в форме `{"name", "signature", "where"}`."""
    members = _map_build(fx, "pkg/m.py")["interface"]["members"]
    assert [m["name"] for m in members] == ["__all__", "_PRIV", "LIMIT", "Alias", "Gen", "A", "f"]
    assert members[0] == {"name": "__all__", "signature": "= ['A', 'f']", "where": "pkg/m.py:1"}
    assert members[2] == {"name": "LIMIT", "signature": ": int = 16", "where": "pkg/m.py:3"}


# ---------------------------------------------------------------- RED 9: `_is_binding_sig`


def test_is_binding_sig_matches_binding_sig() -> None:
    """`_is_binding_sig(_binding_sig(stmt))` — `True` для всех форм привязки; `False` для подписей функций и класса."""
    from scripts.atlas.passport import _binding_sig, _is_binding_sig

    for src in ("x: int", "x: int = 1", "x = 1", "type A = int", "type B[T] = list[T]"):
        assert _is_binding_sig(_binding_sig(ast.parse(src).body[0])), src
    for sig in ("(x: int) -> str", "async (x) -> None", "-> int", ""):
        assert not _is_binding_sig(sig), sig


# ---------------------------------------------------------------- RED 10: срез формы B — class/def первыми


def test_map_cut_keeps_defs_first(fx: GitRepo) -> None:
    """`map pkg/many.py`, бюджет 22: 22 строки; из 13 записей остаются `K0` (первая привязка) и три class/def, печать
    по строке; `show_all={"members"}` — все 13 по строке."""
    p = _map_build(fx, "pkg/many.py")
    text = _render(p, budget=22)
    assert len(text.splitlines()) == 22
    assert _block(text) == [
        "  members:",
        "    K0 = 0  :1",
        "    def a() -> None  :13",
        "    def b() -> None  :17",
        "    class C  :21",
        "    показано 4 из 13; все: --all members",
    ]
    all_block = _block(_render(p, budget=22, show_all=frozenset({"members"})))
    assert all_block == [
        "  members:",
        *[f"    K{k} = {k}  :{k + 1}" for k in range(10)],
        "    def a() -> None  :13",
        "    def b() -> None  :17",
        "    class C  :21",
    ]
