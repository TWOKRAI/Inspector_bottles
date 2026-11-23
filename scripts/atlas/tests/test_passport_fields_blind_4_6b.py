"""Слепые приёмочные тесты полей класса в паспорте и привязок модуля в `map` (Task 4.6b, RED до кода).

Purpose: DESIGN п. 1-3 задачи по выписке tester: (а) `interface.members` класса без публичных методов = его поля
    (`{"name", "signature", "where"}`, по строке, без имён, которые есть как метод/вложенный класс), текст
    `  members: публичных методов нет; полей N:` и строки `<имя><sig>  :<строка>` с минимумом 3 и хвостом
    `ещё N; --full`; (б) `map <файл>` добавляет привязки модуля с адресом, `def`/`class` с тем же именем побеждает
    привязку; (в) срез формы B при бюджете держит class/def первыми, привязки заполняют остаток, печать по строке,
    пометка `показано K из N; все: --all members`; (г) защиты: класс хотя бы с одним публичным методом, пустой класс,
    `ProcessModule`-подобный класс (11 привязок тела + методы) и файл только из class/def не меняются; `top` юнита не
    меняется. Контракт — выписка `4.6b-tester-excerpt.md` и форма `signature` 4.6a; реализации при записи нет.
    Красные до кода — всё про поля и привязки; зелёные уже сейчас и обязаны остаться — защиты (в докстринге: «защита»).
Public API: тесты test_*; публичных имён нет.
Stability: lite

Фикстуры - временные git-репозитории (`RepoFactory`); основное дерево и его `data/atlas.sqlite` не трогаются. Номера
строк - литералы, проверенные самопроверкой фикстуры. Ожидаемые значения не выводятся из кода под тестом (калибровка
бюджета в срезе берёт из прогона только число строк вне `members`). Вызовы - через помощники с дедлайном.
"""

from __future__ import annotations

import json
import re
from typing import Any

import pytest

from scripts.atlas.tests.conftest import GitRepo, RepoFactory
from scripts.atlas.tests.test_passport_map import _build as _map_build
from scripts.atlas.tests.test_passport_map import _registry, _row
from scripts.atlas.tests.test_passport_status import _build, _commit, _lines, _render

__all__: list[str] = []

# ---------------------------------------------------------------- фикстура: классы (номер - строка файла)

_MODELS = "\n".join(
    [
        '"""Модели."""',  # 1
        "",  # 2
        "",  # 3
        "class SQLMeta:",  # 4
        "    table_name = 'auth_sessions'",  # 5
        "    indexes = [('user_id', 'login_at')]",  # 6
        "    unique_together: tuple = ()",  # 7
        "    primary_key = ['session_id']",  # 8
        "",  # 9
        "",  # 10
        "class Mixed:",  # 11
        "    l1: float = 325.0",  # 12
        "    READY = 'ready'",  # 13
        "    type Alias = int | str",  # 14
        "    type Gen[T] = list[T]",  # 15
        "    count: int",  # 16
        "",  # 17
        "    class Inner:",  # 18
        "        pass",  # 19
        "",  # 20
        "    Inner = None",  # 21
        "    _priv = 7",  # 22
        "",  # 23
        "    def _priv(self) -> None:",  # 24
        "        pass",  # 25
        "",  # 26
        "",  # 27
        "class Empty:",  # 28
        "    pass",  # 29
        "",  # 30
        "",  # 31
        "class Runner:",  # 32
        "    RETRIES: int = 3",  # 33
        "    NAME = 'r'",  # 34
        "",  # 35
        "    def run(self, x: int) -> int:",  # 36
        "        return x",  # 37
        "",  # 38
        "",  # 39
        "class Single:",  # 40
        "    only: int = 5",  # 41
        "",  # 42
        "",  # 43
        "class Ctor:",  # 44
        "    size: int = 3",  # 45
        "",  # 46
        "    def __init__(self):",  # 47
        "        self.inst = 1",  # 48
        "",
    ]
)

_BIG = "\n".join(["class Big:", *[f"    F{i:02d} = {i}" for i in range(1, 31)], ""])  # F<i> - строка i + 1

_PROC = "\n".join(
    [
        "class ProcLike:",  # 1
        *[f"    A{i} = {i}" for i in range(1, 12)],  # 2-12: 11 привязок тела
        "",  # 13
        "    def start(self) -> None:",  # 14
        "        pass",  # 15
        "",  # 16
        "    def stop(self, force: bool = False) -> None:",  # 17
        "        pass",  # 18
        "",
    ]
)

# ---------------------------------------------------------------- фикстура: файлы для `map`

_FRAME = "\n".join(
    [
        '"""Фит рамки."""',  # 1
        "",  # 2
        "__all__ = ['FrameFit', 'fit_frame']",  # 3
        "",  # 4
        "MAX_RES: float = 0.5",  # 5
        "MIN_SV: float = 1.0",  # 6
        "type Pair = tuple[int, int]",  # 7
        "type Gen[T] = list[T]",  # 8
        "READY = 'ready'",  # 9
        "helper = 0",  # 10  (до `def helper`: def побеждает)
        "if True:",  # 11
        "    HIDDEN = 1",  # 12
        "",  # 13
        "",  # 14
        "class FrameFit:",  # 15
        "    scale: float = 1.0",  # 16  (поле класса - не привязка модуля)
        "",  # 17
        "",  # 18
        "def fit_frame(a: int) -> int:",  # 19
        "    return a",  # 20
        "",  # 21
        "",  # 22
        "def helper() -> None:",  # 23
        "    return None",  # 24
        "",  # 25
        "",  # 26
        "fit_frame = 2",  # 27  (после `def fit_frame`: def побеждает)
        "LATE = 5",  # 28
        "",
    ]
)

# 30 привязок (строки 2-31), затем class (34) и два def (38, 42)
_MANY = "\n".join(
    [
        '"""Много привязок."""',  # 1
        *[f"K{i:02d} = {i}" for i in range(1, 31)],  # 2-31
        "",  # 32
        "",  # 33
        "class Top:",  # 34
        "    pass",  # 35
        "",  # 36
        "",  # 37
        "def first() -> int:",  # 38
        "    return 1",  # 39
        "",  # 40
        "",  # 41
        "def second(x: int) -> int:",  # 42
        "    return x",  # 43
        "",
    ]
)

_PLAIN = "\n".join(
    [
        '"""Простой."""',  # 1
        "",  # 2
        "",  # 3
        "class A:",  # 4
        "    pass",  # 5
        "",  # 6
        "",  # 7
        "def g(x: int) -> int:",  # 8
        "    return x",  # 9
        "",
    ]
)

_FILES = {
    "modules.yaml": _registry(_row("pkg", "pkg/", purpose="Пакет.")),
    "pkg/__init__.py": "",
    "pkg/models.py": _MODELS,
    "pkg/big.py": _BIG,
    "pkg/proc.py": _PROC,
    "pkg/frame.py": _FRAME,
    "pkg/many.py": _MANY,
    "pkg/plain.py": _PLAIN,
}


@pytest.fixture(scope="module")
def fx(tmp_path_factory: pytest.TempPathFactory) -> GitRepo:
    """Один репозиторий на модуль: тесты только читают его."""
    repo = RepoFactory(tmp_path_factory.mktemp("fx4_6b")).create("repo")
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


def _call_file(fx: GitRepo, path: str) -> dict:
    return _map_build(fx, path)


def _full_block(fx: GitRepo, ident: str) -> list[str]:
    return _block(_render(_build(fx, ident), full=True))


# ---------------------------------------------------------------- 0. самопроверка фикстуры (зелёная)


def test_fixture_line_numbers_match_spec() -> None:
    """Контроль самой фикстуры: номера строк в комментариях совпадают с текстом (иначе красные падают по вине теста)."""
    m = _MODELS.splitlines()
    assert m[3] == "class SQLMeta:" and m[4].startswith("    table_name") and m[7].startswith("    primary_key")
    assert m[11] == "    l1: float = 325.0" and m[14] == "    type Gen[T] = list[T]" and m[15] == "    count: int"
    assert m[17] == "    class Inner:" and m[20] == "    Inner = None" and m[21] == "    _priv = 7"
    assert m[23] == "    def _priv(self) -> None:" and m[27] == "class Empty:" and m[31] == "class Runner:"
    assert m[35] == "    def run(self, x: int) -> int:" and m[39] == "class Single:" and m[40] == "    only: int = 5"
    assert m[43] == "class Ctor:" and m[46] == "    def __init__(self):"
    big = _BIG.splitlines()
    assert big[0] == "class Big:" and big[1] == "    F01 = 1" and big[30] == "    F30 = 30" and len(big) == 31
    proc = _PROC.splitlines()
    assert proc[1] == "    A1 = 1" and proc[11] == "    A11 = 11" and proc[13] == "    def start(self) -> None:"
    assert proc[16] == "    def stop(self, force: bool = False) -> None:"
    f = _FRAME.splitlines()
    assert f[2].startswith("__all__") and f[4] == "MAX_RES: float = 0.5" and f[8] == "READY = 'ready'"
    assert f[9] == "helper = 0" and f[11] == "    HIDDEN = 1" and f[14] == "class FrameFit:"
    assert f[15] == "    scale: float = 1.0" and f[18] == "def fit_frame(a: int) -> int:"
    assert f[22] == "def helper() -> None:" and f[26] == "fit_frame = 2" and f[27] == "LATE = 5"
    many = _MANY.splitlines()
    assert many[1] == "K01 = 1" and many[30] == "K30 = 30" and many[33] == "class Top:"
    assert many[37] == "def first() -> int:" and many[41] == "def second(x: int) -> int:"
    plain = _PLAIN.splitlines()
    assert plain[3] == "class A:" and plain[7] == "def g(x: int) -> int:"


# ---------------------------------------------------------------- (а) JSON: members класса без публичных методов = поля


def test_fields_json_literal_class_with_only_bindings(fx: GitRepo) -> None:
    """`SQLMeta` (4 привязки, методов нет): `members` - 4 поля по строкам с `signature` формы 4.6a и `where`."""
    assert _members(fx, "pkg/models.py::SQLMeta") == [
        {"name": "table_name", "signature": "= 'auth_sessions'", "where": "pkg/models.py:5"},
        {"name": "indexes", "signature": "= [('user_id', 'login_at')]", "where": "pkg/models.py:6"},
        {"name": "unique_together", "signature": ": tuple = ()", "where": "pkg/models.py:7"},
        {"name": "primary_key", "signature": "= ['session_id']", "where": "pkg/models.py:8"},
    ]


def test_fields_json_class_with_only_private_method_gets_fields_skips_method_and_nested_class(fx: GitRepo) -> None:
    """`Mixed`: один приватный метод `_priv` (не публичный) -> поля; имена `Inner` (вложенный класс, строка 18) и
    `_priv` (метод, строка 24) полями не становятся, хотя `Inner = None` и `_priv = 7` есть в теле; порядок по
    строке."""
    assert _members(fx, "pkg/models.py::Mixed") == [
        {"name": "l1", "signature": ": float = 325.0", "where": "pkg/models.py:12"},
        {"name": "READY", "signature": "= 'ready'", "where": "pkg/models.py:13"},
        {"name": "Alias", "signature": "type = int | str", "where": "pkg/models.py:14"},
        {"name": "Gen", "signature": "type[T] = list[T]", "where": "pkg/models.py:15"},
        {"name": "count", "signature": ": int", "where": "pkg/models.py:16"},
    ]


def test_fields_json_single_field(fx: GitRepo) -> None:
    """Класс с одним полем: `members` - одна запись."""
    assert _members(fx, "pkg/models.py::Single") == [
        {"name": "only", "signature": ": int = 5", "where": "pkg/models.py:41"}
    ]


# ---------------------------------------------------------------- (а) текст класса с полями


def test_fields_text_header_and_rows_literal(fx: GitRepo) -> None:
    """`SQLMeta`, без среза: заголовок `  members: публичных методов нет; полей 4:` и 4 строки `<имя><sig>  :<строка>`
    с отступом 4 (форма выписки `def1`)."""
    assert _full_block(fx, "pkg/models.py::SQLMeta") == [
        "  members: публичных методов нет; полей 4:",
        "    table_name = 'auth_sessions'  :5",
        "    indexes = [('user_id', 'login_at')]  :6",
        "    unique_together: tuple = ()  :7",
        "    primary_key = ['session_id']  :8",
    ]


def test_fields_text_row_forms_annotation_value_alias_generic(fx: GitRepo) -> None:
    """`Mixed`: `sig` с `:` приклеивается к имени (`l1: float = 325.0  :12`, `count: int  :16`), прочие - через пробел
    (`READY = 'ready'  :13`, `Alias type = int | str  :14`, `Gen type[T] = list[T]  :15`)."""
    assert _full_block(fx, "pkg/models.py::Mixed") == [
        "  members: публичных методов нет; полей 5:",
        "    l1: float = 325.0  :12",
        "    READY = 'ready'  :13",
        "    Alias type = int | str  :14",
        "    Gen type[T] = list[T]  :15",
        "    count: int  :16",
    ]


def test_fields_text_header_counts_one_field(fx: GitRepo) -> None:
    """Одно поле: число в заголовке - 1."""
    assert _full_block(fx, "pkg/models.py::Single") == [
        "  members: публичных методов нет; полей 1:",
        "    only: int = 5  :41",
    ]


_FIELD_ROW = re.compile(r"^    F\d\d = \d+  :\d+$")
_TAIL = re.compile(r"^    ещё (\d+); --full$")


def test_fields_text_cut_under_tight_budget_keeps_three_with_tail(fx: GitRepo) -> None:
    """30 полей, бюджет 10: заголовок `полей 30:`, показано >= 3 строк в порядке исходника (`F01`, `F02`, ...),
    последняя строка блока - `ещё N; --full`, показано + N == 30, хвост один."""
    block = _block(_render(_build(fx, "pkg/big.py::Big"), budget=10))
    assert block[0] == "  members: публичных методов нет; полей 30:"
    shown = [line for line in block if _FIELD_ROW.match(line)]
    assert len(shown) >= 3, block
    tail = _TAIL.match(block[-1])
    assert tail is not None, block[-1]
    assert len(shown) + int(tail.group(1)) == 30
    assert [line for line in block if "ещё" in line] == [block[-1]]
    assert shown == [f"    F{i:02d} = {i}  :{i + 1}" for i in range(1, len(shown) + 1)]


def test_fields_text_full_shows_all_thirty_without_tail(fx: GitRepo) -> None:
    """`full=True`: все 30 строк полей, строки `ещё` нет."""
    block = _full_block(fx, "pkg/big.py::Big")
    assert block[0] == "  members: публичных методов нет; полей 30:"
    assert block[1:] == [f"    F{i:02d} = {i}  :{i + 1}" for i in range(1, 31)]


def test_fields_cli_ref_full_prints_all_thirty(fx: GitRepo, atlas: Any) -> None:
    """`ref pkg/big.py::Big --format passport --full` через CLI: заголовок и 30 строк полей."""
    res = atlas(fx, "ref", "pkg/big.py::Big", "--format", "passport", "--full")
    assert res.code == 0, res.err
    block = _block(res.out)
    assert block[0] == "  members: публичных методов нет; полей 30:"
    assert block[1:] == [f"    F{i:02d} = {i}  :{i + 1}" for i in range(1, 31)]


# ---------------------------------------------------------------- (г) защиты: зелёные до кода и после


def test_guard_class_with_public_method_keeps_only_methods_json(fx: GitRepo) -> None:
    """Защита: `Runner` (поля `RETRIES`, `NAME` + публичный `run`): `members` - один метод, поля не добавляются."""
    assert _members(fx, "pkg/models.py::Runner") == [
        {"name": "run", "signature": "(x: int) -> int", "where": "pkg/models.py:36"}
    ]


def test_guard_class_with_public_method_text_unchanged(fx: GitRepo) -> None:
    """Защита: текст `Runner` - прежний заголовок `  members:` и одна строка метода, подписи про поля нет."""
    assert _full_block(fx, "pkg/models.py::Runner") == ["  members:", "    run(x: int) -> int  :36"]


def test_guard_class_with_dunder_method_keeps_only_dunder(fx: GitRepo) -> None:
    """Защита: `Ctor` (поле `size` + `__init__`): `members` - только `__init__` (член `_methods`), поле не добавлено."""
    members = _members(fx, "pkg/models.py::Ctor")
    assert [m["name"] for m in members] == ["__init__"]
    assert "публичных методов нет" not in "\n".join(_full_block(fx, "pkg/models.py::Ctor"))


def test_guard_processmodule_like_class_keeps_methods_and_text(fx: GitRepo) -> None:
    """Защита: класс с 11 привязками тела и методами `start`/`stop` (как `ProcessModule`): `members` - два метода,
    текст - прежний, строки привязок `A1 = 1  :2` в нём нет."""
    members = _members(fx, "pkg/proc.py::ProcLike")
    assert members == [
        {"name": "start", "signature": "() -> None", "where": "pkg/proc.py:14"},
        {"name": "stop", "signature": "(force: bool = False) -> None", "where": "pkg/proc.py:17"},
    ]
    assert _full_block(fx, "pkg/proc.py::ProcLike") == [
        "  members:",
        "    start() -> None  :14",
        "    stop(force: bool = False) -> None  :17",
    ]


def test_guard_empty_class_members_empty_and_dash(fx: GitRepo) -> None:
    """Защита: пустой класс - `members == []`, текст `  members: —`."""
    assert _members(fx, "pkg/models.py::Empty") == []
    assert _full_block(fx, "pkg/models.py::Empty") == ["  members: —"]


# ---------------------------------------------------------------- (б) map <файл>: привязки модуля


def test_map_file_json_members_include_module_bindings_by_line(fx: GitRepo) -> None:
    """`map pkg/frame.py`: `members` - class/def и привязки модуля по строке (устойчивая сортировка); `def`/`class` с
    тем же именем побеждает привязку (`helper = 0` до `def helper`, `fit_frame = 2` после `def fit_frame`); оператор
    внутри `if` (`HIDDEN`) и поле класса (`scale`) в привязки модуля не входят."""
    assert _call_file(fx, "pkg/frame.py")["interface"]["members"] == [
        {"name": "__all__", "signature": "= ['FrameFit', 'fit_frame']", "where": "pkg/frame.py:3"},
        {"name": "MAX_RES", "signature": ": float = 0.5", "where": "pkg/frame.py:5"},
        {"name": "MIN_SV", "signature": ": float = 1.0", "where": "pkg/frame.py:6"},
        {"name": "Pair", "signature": "type = tuple[int, int]", "where": "pkg/frame.py:7"},
        {"name": "Gen", "signature": "type[T] = list[T]", "where": "pkg/frame.py:8"},
        {"name": "READY", "signature": "= 'ready'", "where": "pkg/frame.py:9"},
        {"name": "FrameFit", "signature": "", "where": "pkg/frame.py:15"},
        {"name": "fit_frame", "signature": "(a: int) -> int", "where": "pkg/frame.py:19"},
        {"name": "helper", "signature": "() -> None", "where": "pkg/frame.py:23"},
        {"name": "LATE", "signature": "= 5", "where": "pkg/frame.py:28"},
    ]


def test_map_file_text_rows_literal(fx: GitRepo) -> None:
    """Текст `map pkg/frame.py` без среза: привязки - `<имя><sig>  :<строка>` (как поле класса), class/def - как раньше,
    всё в порядке строк."""
    text = _render(_call_file(fx, "pkg/frame.py"), full=True)
    assert _block(text) == [
        "  members:",
        "    __all__ = ['FrameFit', 'fit_frame']  :3",
        "    MAX_RES: float = 0.5  :5",
        "    MIN_SV: float = 1.0  :6",
        "    Pair type = tuple[int, int]  :7",
        "    Gen type[T] = list[T]  :8",
        "    READY = 'ready'  :9",
        "    class FrameFit  :15",
        "    def fit_frame(a: int) -> int  :19",
        "    def helper() -> None  :23",
        "    LATE = 5  :28",
    ]


# ---------------------------------------------------------------- (в) срез формы B: class/def первыми


def _map_cut(fx: GitRepo, path: str, keep: int, **kwargs: Any) -> tuple[list[str], int]:
    """Блок `members` текста `map` при бюджете, дающем ровно `keep` записей + строка пометки. Число строк вне `members`
    берётся из полного прогона (форма текста, не содержимое); возвращает `(блок, строк вне members)`."""
    p = _call_file(fx, path)
    full = _lines(_render(p, full=True))
    start = next(i for i, line in enumerate(full) if line == "  members:")
    end = next(i for i in range(start + 1, len(full)) if full[i].startswith("links:"))
    base = len(full) - (end - start - 1)
    return _block(_render(p, budget=base + keep + 1, **kwargs)), base


def test_map_cut_keeps_class_and_defs_first_then_earliest_bindings(fx: GitRepo) -> None:
    """`pkg/many.py` (30 привязок, class `Top` :34, def `first` :38, def `second` :42), место на 5 записей: все три
    class/def и две ПЕРВЫЕ привязки (`K01`, `K02`), печать по строке, пометка `показано 5 из 33; все: --all members`.
    Простая сортировка по строке дала бы `K01`-`K05` без class/def."""
    block, _ = _map_cut(fx, "pkg/many.py", 5)
    assert block == [
        "  members:",
        "    K01 = 1  :2",
        "    K02 = 2  :3",
        "    class Top  :34",
        "    def first() -> int  :38",
        "    def second(x: int) -> int  :42",
        "    показано 5 из 33; все: --all members",
    ]


def test_map_cut_with_room_for_two_keeps_first_two_class_def_not_bindings(fx: GitRepo) -> None:
    """Место на 2 записи: остаются два первых class/def (`Top`, `first`) - ключ `(приоритет, индекс)`; привязок нет;
    пометка `показано 2 из 33; все: --all members`."""
    block, _ = _map_cut(fx, "pkg/many.py", 2)
    assert block == [
        "  members:",
        "    class Top  :34",
        "    def first() -> int  :38",
        "    показано 2 из 33; все: --all members",
    ]


def test_map_show_all_members_lists_all_in_line_order_without_mark(fx: GitRepo) -> None:
    """`show_all={"members"}` при минимальном бюджете: все 33 записи в порядке строк (30 привязок, затем class и два
    def), пометки нет."""
    block = _block(_render(_call_file(fx, "pkg/many.py"), budget=1, show_all=frozenset({"members"})))
    expected = [f"    K{i:02d} = {i}  :{i + 1}" for i in range(1, 31)]
    expected += ["    class Top  :34", "    def first() -> int  :38", "    def second(x: int) -> int  :42"]
    assert block == ["  members:", *expected]


def test_map_cli_all_members_lists_all_33(fx: GitRepo, atlas: Any) -> None:
    """`map pkg/many.py --all members --budget 1` через CLI: 33 строки записей, пометки `показано` нет."""
    res = atlas(fx, "map", "pkg/many.py", "--all", "members", "--budget", "1")
    assert res.code == 0, res.err
    block = _block(res.out)
    assert len(block) == 34 and block[0] == "  members:"
    assert block[1] == "    K01 = 1  :2" and block[-1] == "    def second(x: int) -> int  :42"
    assert not [line for line in block if "показано" in line]


# ---------------------------------------------------------------- (г) защиты map: файл без привязок, юнит


def test_guard_map_file_without_bindings_unchanged(fx: GitRepo) -> None:
    """Защита: файл только из class/def - `members` прежние (два члена), в тексте строки `class A  :4` и
    `def g(x: int) -> int  :8`, срез не ломает порядок."""
    p = _call_file(fx, "pkg/plain.py")
    assert p["interface"]["members"] == [
        {"name": "A", "signature": "", "where": "pkg/plain.py:4"},
        {"name": "g", "signature": "(x: int) -> int", "where": "pkg/plain.py:8"},
    ]
    assert _block(_render(p, full=True)) == ["  members:", "    class A  :4", "    def g(x: int) -> int  :8"]
    assert _block(_render(p, budget=1)) == ["  members:", "    class A  :4", "    показано 1 из 2; все: --all members"]


def test_guard_map_unit_top_has_no_bindings(fx: GitRepo) -> None:
    """Защита: форма A (юнит) не меняется - `top` файла `pkg/frame.py` содержит имена class/def и не содержит ни одной
    привязки модуля; члены юнита - файлы."""
    unit = _call_file(fx, "pkg")
    assert unit["kind"] == "unit"
    names = [m["name"] for m in unit["interface"]["members"]]
    assert "pkg/frame.py" in names
    assert all(n.endswith(".py") for n in names)
    top = next(m["top"] for m in unit["interface"]["members"] if m["name"] == "pkg/frame.py")
    assert "FrameFit" in top
    for binding in ("__all__", "MAX_RES", "READY", "LATE", "Pair"):
        assert binding not in top


def test_guard_json_serializable(fx: GitRepo) -> None:
    """Защита: паспорта класса с полями и файла с привязками остаются JSON-совместимыми без `default=`."""
    for p in (_build(fx, "pkg/models.py::Mixed"), _call_file(fx, "pkg/frame.py")):
        assert json.loads(json.dumps(p)) == p
