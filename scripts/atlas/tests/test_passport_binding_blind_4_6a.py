"""Слепые приёмочные тесты паспорта привязки (Task 4.6a, RED до кода): `ref путь::ИМЯ` для констант, алиасов, полей.

Purpose: контракт DESIGN п. 1-3, 6 задачи `plans/2026-11-06_atlas-passport/tasks/4.6a.md` и литералы входного документа
    `reports/4.6-baseline/4.6a-fixtures.md` (§1 фикстура, §2 скелет JSON, §3 схема, §4 текст). Привязка - имя из прямого
    оператора тела модуля или класса (`Assign` по каждой цели-`Name`, `AnnAssign` с целью-`Name`, `TypeAlias`); первый
    оператор побеждает; `def`/`class` с тем же именем побеждает привязку; `kind == "binding"`; `signature` по
    `ast.unparse` со срезом значения до 120 символов; у привязки модуля `used_by` из from-импортов, у класса `[]`;
    не-привязки (кортежная цель, `if`/`try`/`with`/`for`/`while`, `self.x`, `+=`, локальные, голое имя) - `not found`.
    Две группы тестов:
      - красные до реализации: всё, что про `kind == "binding"` (в отчёте tester они перечислены по именам);
      - зелёные уже сейчас и обязаны остаться: неизменность паспортов `def`/`class`/метода и `ProcessModule` (эталон
        `reports/4.6-baseline/`, снят на `1e085652f`), охрана файла с ошибкой разбора.
Public API: тесты test_*; публичных имён нет.
Stability: lite

Фикстуры - временные git-репозитории (`RepoFactory` из conftest; хелперы `_commit`, `_build`, `_render` из
`test_passport_status.py`); основное дерево и его `data/atlas.sqlite` не трогаются. Приёмка по 20 реальным id идёт на
клоне `git clone --shared --no-checkout` + `checkout --detach 1e085652f` во временном каталоге (если коммита нет в
объектах - тесты пропускаются с причиной), код берётся из дерева, где гонят тест. Ожидаемые значения - литералы из
текста задачи, а не вывод кода под тестом. Вызовы идут в daemon-потоке с дедлайном (`run_with_deadline`).
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

import pytest

from scripts.atlas.tests.conftest import GitRepo, RepoFactory, run_with_deadline
from scripts.atlas.tests.test_passport_status import _build, _commit, _lines, _render

__all__: list[str] = []

NONE = type(None)
_CODE_ROOT = Path(__file__).resolve().parents[3]
BASE_SHA = "1e085652f6a7a5b3825f87157769be6de47ad928"
SCANNER = "1-d8b9d44d5b0d"
CLONE_DEADLINE_S = 900.0
BASELINE_DIR = _CODE_ROOT / "plans" / "2026-11-06_atlas-passport" / "reports" / "4.6-baseline"

# ---------------------------------------------------------------- фикстура (4.6a-fixtures.md §1; номер - строка файла)

_X118 = "x" * 118
_X119 = "x" * 119

_CONSTS = "\n".join(
    [
        '"""Константы."""',  # 1
        "from typing import Literal",  # 2
        "LIMIT: int = 0x10",  # 3
        "LIMIT = 99",  # 4
        "A = B = 1",  # 5
        "x, y = 1, 2",  # 6
        "if True:",  # 7
        "    HIDDEN = 1",  # 8
        "type Alias = int | str",  # 9
        'Mode = Literal["a", "b"]',  # 10
        f'EXACT = "{_X118}"',  # 11
        f'OVER = "{_X119}"',  # 12
        "",  # 13
        "",  # 14
        "def helper():",  # 15
        "    local = 1",  # 16
        "",  # 17
        "",  # 18
        "def f():",  # 19
        "    return 1",  # 20
        "",  # 21
        "",  # 22
        "f = 1",  # 23
        "",  # 24
        "",  # 25
        "class Schema:",  # 26
        "    count: int",  # 27
        "    rate: float = 1.5",  # 28
        '    KIND = "s"',  # 29
        "",  # 30
        "    class Meta:",  # 31
        '        table = "t"',  # 32
        "",  # 33
        "    def __init__(self):",  # 34
        "        self.inst = 1",  # 35
        "",
    ]
)

_FROZEN = "\n".join(
    [
        '"""FREEZE 2026-01-01: схема заморожена',  # 1
        "",  # 2
        "Tier: core",  # 3
        '"""',  # 4
        '__all__ = ["Cfg"]',  # 5
        "LEVEL = 1",  # 6
        "",  # 7
        "",  # 8
        "class Cfg:",  # 9
        "    size: int = 3",  # 10
        "",
    ]
)

# дополнительные случаи DESIGN п. 1 (не входят в §1: свой файл, свои литералы строк)
_MORE = "\n".join(
    [
        "try:",  # 1
        "    T1 = 1",  # 2
        "except Exception:",  # 3
        "    T2 = 2",  # 4
        'with open("x") as fh:',  # 5
        "    W1 = 1",  # 6
        "for i in range(3):",  # 7
        "    F1 = 1",  # 8
        "while False:",  # 9
        "    WH = 1",  # 10
        "CNT = 0",  # 11
        "CNT += 1",  # 12
        "ONLY_AUG += 1",  # 13
        "P1 = (Q1, R1) = 1, 2",  # 14
        "B2: int",  # 15
        "B2 = 3",  # 16
        "type Pair[K, V] = dict[K, V]",  # 17
        "G1 = 1",  # 18
        "def G1():",  # 19
        "    return 1",  # 20
        "H1 = 2",  # 21
        "class H1:",  # 22
        "    pass",  # 23
        "class Owner:",  # 24
        "    if True:",  # 25
        "        IN_IF = 1",  # 26
        "    a, b = 1, 2",  # 27
        "    DUP: int = 1",  # 28
        "    DUP = 2",  # 29
        "    z = y = 0",  # 30
        "    def method(self):",  # 31
        "        local = 1",  # 32
        "    method2 = 5",  # 33
        "    other = 1",  # 34
        "    def other(self):",  # 35
        "        return 1",  # 36
        "",
    ]
)

_ANN = ", ".join(["int"] * 45)  # аннотация 'tuple[int, ...]' длиннее 120 символов: не режется
_LONG = "\n".join(
    [
        'S0 = ""',  # 1
        'S300 = "' + "x" * 300 + '"',  # 2
        f"LONG_ANN: tuple[{_ANN}] = 1",  # 3
        "LONG_BOTH: tuple[" + _ANN + '] = "' + "y" * 300 + '"',  # 4
        "",
    ]
)

_FILES = {
    "pkg/__init__.py": "",
    "pkg/consts.py": _CONSTS,
    "pkg/user.py": "from pkg.consts import LIMIT, KIND\n",
    "pkg/user2.py": "from pkg.consts import LIMIT\n",
    "pkg/frozen.py": _FROZEN,
    "pkg/more.py": _MORE,
    "pkg/long.py": _LONG,
    "pkg/nested.py": "def build():\n    class Local:\n        LIMIT = 5\n    return Local\n",
    "pkg/broken.py": "BROKEN_X = 1\ndef (:\n",
}


@pytest.fixture(scope="module")
def fx(tmp_path_factory: pytest.TempPathFactory) -> GitRepo:
    """Один репозиторий на модуль: фикстуры только читают его."""
    repo = RepoFactory(tmp_path_factory.mktemp("fx4_6a")).create("repo")
    _commit(repo, _FILES)
    return repo


def _ids(path: str, *names: str) -> list[str]:
    return [f"{path}::{n}" for n in names]


def _passports(repo: GitRepo, *idents: str) -> list[dict]:
    from scripts.atlas.passport import passports_for

    return run_with_deadline(lambda: passports_for(repo.path, "HEAD", list(idents)), 120.0)


# ---------------------------------------------------------------- 0. самопроверка фикстуры (зелёная: строки §1)


def test_fixture_line_numbers_match_spec() -> None:
    """Контроль самой фикстуры: номера строк §1 совпадают с текстом (иначе красные ниже падают по вине теста)."""
    lines = _CONSTS.splitlines()
    assert lines[2] == "LIMIT: int = 0x10"
    assert lines[3] == "LIMIT = 99"
    assert lines[4] == "A = B = 1"
    assert lines[8] == "type Alias = int | str"
    assert lines[9].startswith("Mode = ")
    assert lines[10].startswith("EXACT = ") and len(lines[10]) == len("EXACT = ") + 120
    assert lines[11].startswith("OVER = ") and len(lines[11]) == len("OVER = ") + 121
    assert lines[14] == "def helper():" and lines[18] == "def f():" and lines[22] == "f = 1"
    assert lines[25] == "class Schema:" and lines[26] == "    count: int" and lines[31] == '        table = "t"'
    assert lines[33] == "    def __init__(self):"
    frozen = _FROZEN.splitlines()
    assert frozen[5] == "LEVEL = 1" and frozen[8] == "class Cfg:" and frozen[9] == "    size: int = 3"
    more = _MORE.splitlines()
    assert more[13].startswith("P1 =") and more[14] == "B2: int" and more[16].startswith("type Pair")
    assert more[23] == "class Owner:" and more[27] == "    DUP: int = 1" and more[34] == "    def other(self):"


# ---------------------------------------------------------------- 1. находятся: путь::ИМЯ -> binding, line, signature

# (id-имя в файле, строка первого оператора, signature по ast.unparse) - литералы §1 и DESIGN п. 1-2
_CONSTS_BINDINGS = [
    ("LIMIT", 3, ": int = 16"),  # первый оператор (AnnAssign), а не `LIMIT = 99` строки 4; 0x10 -> 16
    ("A", 5, "= 1"),  # `A = B = 1`: цель A
    ("B", 5, "= 1"),  # ... и цель B - обе привязки, одна строка
    ("Alias", 9, "type = int | str"),  # `type X = ...` без параметров
    ("Mode", 10, "= Literal['a', 'b']"),  # Literal-алиас, кавычки по ast.unparse
    ("EXACT", 11, "= '" + _X118 + "'"),  # значение ровно 120 символов - без среза и без `…`
    ("OVER", 12, "= '" + _X119 + "…"),  # значение 121 символ -> первые 120 + `…`
    ("Schema.count", 27, ": int"),  # AnnAssign без значения в теле класса
    ("Schema.rate", 28, ": float = 1.5"),
    ("Schema.KIND", 29, "= 's'"),
    ("Schema.Meta.table", 32, "= 't'"),  # вложенный класс
]


@pytest.mark.parametrize(("name", "line", "signature"), _CONSTS_BINDINGS, ids=[b[0] for b in _CONSTS_BINDINGS])
def test_binding_passport_kind_line_signature(fx: GitRepo, name: str, line: int, signature: str) -> None:
    """Привязка модуля/тела класса: `kind == "binding"`, `line` первого оператора, `signature` по `ast.unparse`."""
    ident = f"pkg/consts.py::{name}"
    p = _build(fx, ident)
    assert p["passport"] == 1
    assert p["kind"] == "binding"
    assert p["id"] == ident
    assert p["path"] == "pkg/consts.py"
    assert p["line"] == line
    assert p["interface"]["signature"] == signature


def test_module_constant_text_value_16_not_hex(fx: GitRepo) -> None:
    """`LIMIT: int = 0x10`: значение печатается по `ast.unparse` (`16`), а не по исходному тексту (`0x10`)."""
    assert _build(fx, "pkg/consts.py::LIMIT")["interface"]["signature"] == ": int = 16"


def test_first_binding_wins_not_last(fx: GitRepo) -> None:
    """`LIMIT` (строки 3 и 4): побеждает первый оператор - строка 3, аннотация `: int`, а не `= 99` строки 4."""
    p = _build(fx, "pkg/consts.py::LIMIT")
    assert p["line"] == 3
    assert "99" not in p["interface"]["signature"]


def test_def_wins_over_later_binding(fx: GitRepo) -> None:
    """`def f` (строка 19) и позднее `f = 1` (строка 23): `f` - прежний паспорт функции, не привязка."""
    p = _build(fx, "pkg/consts.py::f")
    assert p["kind"] == "function"
    assert p["line"] == 19


def test_def_wins_over_earlier_binding(fx: GitRepo) -> None:
    """`G1 = 1` (18) до `def G1` (19), `H1 = 2` (21) до `class H1` (22): имя из `defs` даёт прежний паспорт."""
    g = _build(fx, "pkg/more.py::G1")
    h = _build(fx, "pkg/more.py::H1")
    assert (g["kind"], g["line"]) == ("function", 19)
    assert (h["kind"], h["line"]) == ("class", 22)


def test_class_def_wins_over_binding_of_same_name(fx: GitRepo) -> None:
    """В теле класса `other = 1` (34) до `def other` (35): `Owner.other` - метод строки 35."""
    p = _build(fx, "pkg/more.py::Owner.other")
    assert (p["kind"], p["line"]) == ("method", 35)


def test_annotation_without_value_first_wins_over_later_assign(fx: GitRepo) -> None:
    """`B2: int` (15), затем `B2 = 3` (16): побеждает первый оператор - строка 15, `signature` `: int`."""
    p = _build(fx, "pkg/more.py::B2")
    assert p["kind"] == "binding"
    assert (p["line"], p["interface"]["signature"]) == (15, ": int")


def test_aug_assign_does_not_create_or_replace_binding(fx: GitRepo) -> None:
    """`CNT = 0` (11), `CNT += 1` (12): привязка - строка 11, `= 0`."""
    p = _build(fx, "pkg/more.py::CNT")
    assert (p["kind"], p["line"], p["interface"]["signature"]) == ("binding", 11, "= 0")


def test_chain_assign_name_target_binds_tuple_target_does_not(fx: GitRepo) -> None:
    """`P1 = (Q1, R1) = 1, 2` (14): `P1` - привязка (`= (1, 2)`), кортежные цели `Q1`, `R1` - нет."""
    p = _build(fx, "pkg/more.py::P1")
    assert (p["kind"], p["line"], p["interface"]["signature"]) == ("binding", 14, "= (1, 2)")


def test_type_alias_with_params_signature(fx: GitRepo) -> None:
    """`type Pair[K, V] = dict[K, V]` (17): `signature` - `type[K, V] = dict[K, V]` (параметры через `, `)."""
    p = _build(fx, "pkg/more.py::Pair")
    assert (p["kind"], p["line"], p["interface"]["signature"]) == ("binding", 17, "type[K, V] = dict[K, V]")


def test_class_body_binding_first_wins_and_chain_targets(fx: GitRepo) -> None:
    """Тело класса: `DUP: int = 1` (28) и позднее `DUP = 2` (29) - строка 28; `z = y = 0` (30) - обе цели привязки;
    `method2 = 5` (33) - привязка."""
    dup = _build(fx, "pkg/more.py::Owner.DUP")
    z = _build(fx, "pkg/more.py::Owner.z")
    y = _build(fx, "pkg/more.py::Owner.y")
    m2 = _build(fx, "pkg/more.py::Owner.method2")
    assert (dup["kind"], dup["line"], dup["interface"]["signature"]) == ("binding", 28, ": int = 1")
    assert (z["kind"], z["line"], z["interface"]["signature"]) == ("binding", 30, "= 0")
    assert (y["kind"], y["line"], y["interface"]["signature"]) == ("binding", 30, "= 0")
    assert (m2["kind"], m2["line"], m2["interface"]["signature"]) == ("binding", 33, "= 5")


def test_class_defined_inside_function_owns_bindings(fx: GitRepo) -> None:
    """Класс внутри функции (`DefFact` `build.Local`): `build.Local.LIMIT` - привязка строки 3, `= 5`."""
    p = _build(fx, "pkg/nested.py::build.Local.LIMIT")
    assert (p["kind"], p["line"], p["interface"]["signature"]) == ("binding", 3, "= 5")


def test_frozen_file_bindings(fx: GitRepo) -> None:
    """`pkg/frozen.py`: `LEVEL = 1` (6) - `= 1`; `Cfg.size: int = 3` (10) - `: int = 3`."""
    level = _build(fx, "pkg/frozen.py::LEVEL")
    size = _build(fx, "pkg/frozen.py::Cfg.size")
    assert (level["kind"], level["line"], level["interface"]["signature"]) == ("binding", 6, "= 1")
    assert (size["kind"], size["line"], size["interface"]["signature"]) == ("binding", 10, ": int = 3")


# ---------------------------------------------------------------- 2. срез значения до 120; аннотация не режется

_LONG_VALUE_ANN = "tuple[" + _ANN + "]"


def test_empty_string_value_not_cut(fx: GitRepo) -> None:
    """Короткое значение `''` (0 символов строки) - без среза: `= ''`."""
    assert _build(fx, "pkg/long.py::S0")["interface"]["signature"] == "= ''"


def test_value_300_chars_cut_to_120_plus_ellipsis(fx: GitRepo) -> None:
    """Значение `'` + 300 x + `'` режется до первых 120 символов (`'` + 119 x) и `…` (U+2026)."""
    sig = _build(fx, "pkg/long.py::S300")["interface"]["signature"]
    assert sig == "= '" + "x" * 119 + "…"
    assert len(sig) == len("= ") + 120 + 1


def test_annotation_is_never_cut(fx: GitRepo) -> None:
    """Аннотация длиннее 120 символов печатается целиком; режется только значение."""
    sig = _build(fx, "pkg/long.py::LONG_ANN")["interface"]["signature"]
    assert sig == ": " + _LONG_VALUE_ANN + " = 1"
    assert len(_LONG_VALUE_ANN) > 120


def test_annotation_whole_and_value_cut_together(fx: GitRepo) -> None:
    """Длинная аннотация целиком + длинное значение режется до 120 символов + `…`."""
    sig = _build(fx, "pkg/long.py::LONG_BOTH")["interface"]["signature"]
    assert sig == ": " + _LONG_VALUE_ANN + " = '" + "y" * 119 + "…"


# ---------------------------------------------------------------- 3. не-привязки -> not found, код 2

# `resolve` обязан ответить `[]`; голое имя и пустой qualname - из DESIGN п. 1, 7; остальное - §1 и тело DESIGN п. 1
_NOT_BINDINGS = [
    "pkg/consts.py::x",  # кортежная цель `x, y = ...`
    "pkg/consts.py::y",
    "pkg/consts.py::HIDDEN",  # внутри `if`
    "pkg/consts.py::helper.local",  # локальное имя функции
    "pkg/consts.py::Schema.inst",  # `self.inst = 1` в методе
    "pkg/consts.py::Schema.__init__.x",
    "pkg/consts.py::KIND",  # `KIND` есть у класса Schema, но не у модуля
    "pkg/consts.py::LIMIT.x",  # владелец - привязка, а не класс
    "pkg/consts.py::Schema.nothing",  # нет такого имени
    "pkg/consts.py::Nothing.table",  # нет такого владельца
    "pkg/consts.py::",  # пустой qualname
    "pkg/more.py::T1",  # внутри `try`
    "pkg/more.py::T2",  # внутри `except`
    "pkg/more.py::W1",  # внутри `with`
    "pkg/more.py::fh",  # цель `with ... as`: не `Assign`
    "pkg/more.py::F1",  # внутри `for`
    "pkg/more.py::i",  # цель цикла `for`
    "pkg/more.py::WH",  # внутри `while`
    "pkg/more.py::ONLY_AUG",  # только `+=`
    "pkg/more.py::Q1",  # кортежная цель в цепочке
    "pkg/more.py::R1",
    "pkg/more.py::Owner.IN_IF",  # внутри `if` тела класса
    "pkg/more.py::Owner.a",  # кортежная цель в теле класса
    "pkg/more.py::Owner.b",
    "pkg/more.py::Owner.method.local",  # локальное имя метода
    "pkg/broken.py::BROKEN_X",  # файл с ошибкой разбора: символы не находятся (контракт `facts.error`)
]


def test_controls_resolve_finds_bindings(fx: GitRepo) -> None:
    """Контроль к списку не-привязок: `LIMIT` и `A` модуля, `Schema.KIND` - найдены (`resolve` = [id])."""
    from scripts.atlas.passport import resolve_ident

    for ident in ("pkg/consts.py::LIMIT", "pkg/consts.py::A", "pkg/consts.py::Schema.KIND"):
        assert run_with_deadline(lambda i=ident: resolve_ident(fx.path, "HEAD", i), 120.0) == [ident], ident


@pytest.mark.parametrize("ident", _NOT_BINDINGS)
def test_non_binding_resolves_to_nothing(fx: GitRepo, ident: str) -> None:
    """Не-привязка: `resolve_ident` -> `[]`, `passports_for` -> запись с `error` (`not found`)."""
    from scripts.atlas.passport import resolve_ident

    assert run_with_deadline(lambda: resolve_ident(fx.path, "HEAD", ident), 120.0) == []
    (record,) = _passports(fx, ident)
    assert record["id"] == ident
    assert "not found" in record["error"]


def test_bare_name_is_not_resolved(fx: GitRepo) -> None:
    """Голое `LIMIT` (без `путь::`) привязку не ищет: `[]` / `not found` (п. 7, голое имя не входит в 4.6a)."""
    from scripts.atlas.passport import resolve_ident

    assert run_with_deadline(lambda: resolve_ident(fx.path, "HEAD", "LIMIT"), 120.0) == []
    (record,) = _passports(fx, "LIMIT")
    assert "not found" in record["error"]


def test_cli_non_binding_exit_2_and_binding_exit_0(fx: GitRepo, atlas: Any) -> None:
    """CLI: привязка - код 0 и паспорт `binding` в JSON; не-привязка `HIDDEN` - код 2 и `not found` в stderr."""
    ok = atlas(fx, "ref", "pkg/consts.py::LIMIT", "--format", "json")
    assert ok.code == 0, ok.err
    assert json.loads(ok.out)[0]["kind"] == "binding"
    bad = atlas(fx, "ref", "pkg/consts.py::HIDDEN", "--format", "json")
    assert bad.code == 2
    assert "not found" in bad.err
    assert json.loads(bad.out)[0]["id"] == "pkg/consts.py::HIDDEN"


def test_cli_bare_name_exit_2(fx: GitRepo, atlas: Any) -> None:
    """CLI: голое `LIMIT --format passport` - код 2 (текст ошибки может получить подсказку: не сравнивается)."""
    res = atlas(fx, "ref", "LIMIT", "--format", "passport")
    assert res.code == 2
    assert res.err.strip() != ""


def test_cli_one_bad_id_does_not_cancel_binding_passport(fx: GitRepo, atlas: Any) -> None:
    """`ref <привязка> <не-привязка> --format json`: код 2, но первый паспорт полный (`binding`), второй - ошибка."""
    res = atlas(fx, "ref", "pkg/consts.py::LIMIT", "pkg/consts.py::x", "--format", "json")
    assert res.code == 2
    first, second = json.loads(res.out)
    assert first["kind"] == "binding" and first["id"] == "pkg/consts.py::LIMIT"
    assert second["id"] == "pkg/consts.py::x" and "error" in second


def test_cli_text_format_prints_binding_header(fx: GitRepo, atlas: Any) -> None:
    """CLI `--format passport`: код 0, первая строка `== pkg/consts.py::Schema.rate ==`."""
    res = atlas(fx, "ref", "pkg/consts.py::Schema.rate", "--format", "passport")
    assert res.code == 0, res.err
    assert res.out.splitlines()[0] == "== pkg/consts.py::Schema.rate =="


# ---------------------------------------------------------------- 4. разделы паспорта привязки (скелет §2)

_ENVELOPE_KEYS = [
    "passport",
    "kind",
    "id",
    "path",
    "line",
    "sha",
    "scanner",
    "purpose",
    "interface",
    "links",
    "runtime",
    "checks",
    "status",
]


def test_binding_json_key_order_exact(fx: GitRepo) -> None:
    """Конверт и разделы - в порядке скелета §2, подключи каждого раздела - литерал списка и порядка."""
    p = _build(fx, "pkg/consts.py::LIMIT")
    assert list(p) == _ENVELOPE_KEYS
    assert list(p["purpose"]) == ["text", "called_from", "called_from_more", "declared_at"]
    assert list(p["interface"]) == ["layer", "all", "signature", "members"]
    assert list(p["links"]) == [
        "used_by",
        "uses",
        "subclasses",
        "call_sites",
        "call_sites_unresolved",
        "bases",
        "structural",
        "call_sites_by_name",
    ]
    assert list(p["runtime"]) == ["processes", "threads", "commands", "io"]
    assert list(p["checks"]) == ["findings", "tests"]
    assert list(p["status"]) == ["tier", "doc_missing", "dynamic", "stale", "frozen"]


def test_binding_sections_not_searched_are_null(fx: GitRepo) -> None:
    """Всё, что для привязки не искали, - `null` (а не `[]`/`0`/`False`): скелет §2."""
    p = _build(fx, "pkg/consts.py::LIMIT")
    assert p["purpose"]["text"] is None
    assert p["purpose"]["called_from"] is None
    assert p["purpose"]["called_from_more"] == 0
    assert p["purpose"]["declared_at"] is None
    assert p["interface"]["members"] is None
    for key in (
        "uses",
        "subclasses",
        "call_sites",
        "call_sites_unresolved",
        "bases",
        "structural",
        "call_sites_by_name",
    ):
        assert p["links"][key] is None, key
    for key in ("processes", "threads", "commands", "io"):
        assert p["runtime"][key] is None, key
    assert p["checks"]["findings"] is None
    assert p["checks"]["tests"] is None
    assert p["status"]["doc_missing"] is None
    assert p["status"]["dynamic"] is None


def test_binding_sections_null_in_class_body_binding_too(fx: GitRepo) -> None:
    """Привязка тела класса: те же `null` (`bases`, `structural`, `call_sites`, `checks.tests`)."""
    p = _build(fx, "pkg/consts.py::Schema.rate")
    assert p["links"]["bases"] is None
    assert p["links"]["structural"] is None
    assert p["links"]["call_sites"] is None
    assert p["checks"]["tests"] is None


def test_binding_envelope_values(fx: GitRepo) -> None:
    """`sha` - HEAD репозитория (40 hex), `scanner` - непустая строка, `layer` - `other` (фикстура без реестра),
    `stale == []` на чистом репозитории, `frozen == []` у файла без шапки `FREEZE`."""
    p = _build(fx, "pkg/consts.py::LIMIT")
    assert p["sha"] == fx.head
    assert re.fullmatch(r"[0-9a-f]{40}", p["sha"])
    assert type(p["scanner"]) is str and p["scanner"] != ""
    assert p["interface"]["layer"] == "other"
    assert p["status"]["stale"] == []
    assert p["status"]["frozen"] == []
    assert p["status"]["tier"] is None  # у `pkg/consts.py` нет шапки `Tier:` (текст: `tier нет шапки`)


def test_binding_all_is_none_without_dunder_all(fx: GitRepo) -> None:
    """Файл и пакет без `__all__`: `interface.all is None` (как у метода: `_all_chain`)."""
    assert _build(fx, "pkg/consts.py::LIMIT")["interface"]["all"] is None


def test_binding_all_chain_by_first_qualname_segment(fx: GitRepo) -> None:
    """`pkg/frozen.py` с `__all__ = ["Cfg"]`: `Cfg.size` -> `["pkg/frozen.py"]` (сегмент `Cfg`), `LEVEL` -> `[]`."""
    assert _build(fx, "pkg/frozen.py::Cfg.size")["interface"]["all"] == ["pkg/frozen.py"]
    assert _build(fx, "pkg/frozen.py::LEVEL")["interface"]["all"] == []


def test_binding_status_tier_and_frozen_from_file_header(fx: GitRepo) -> None:
    """`pkg/frozen.py::LEVEL`: `status.tier == "core"`, `status.frozen` - одна шапка `FREEZE` с литералами §1."""
    p = _build(fx, "pkg/frozen.py::LEVEL")
    assert p["status"]["tier"] == "core"
    assert p["status"]["frozen"] == [{"date": "2026-01-01", "text": "схема заморожена", "where": "pkg/frozen.py:1"}]


def test_binding_status_stale_lists_dirty_path(fx: GitRepo, tmp_path: Path) -> None:
    """`stale` у привязки считается как у символа: правка файла связи в рабочем дереве даёт его путь в `stale`."""
    repo = RepoFactory(tmp_path).create("stale")
    _commit(
        repo, {"pkg/__init__.py": "", "pkg/consts.py": "LIMIT = 1\n", "pkg/user.py": "from pkg.consts import LIMIT\n"}
    )
    with (repo.path / "pkg/user.py").open("ab") as fh:
        fh.write(b"# edit\n")
    p = _build(repo, "pkg/consts.py::LIMIT")
    assert p["kind"] == "binding"
    assert p["status"]["stale"] == ["pkg/user.py"]


# ---------------------------------------------------------------- 5. used_by

_USED_LIMIT = [
    {"where": "pkg/user.py:1", "how": "import", "scope": "prod", "enclosing": "<module>"},
    {"where": "pkg/user2.py:1", "how": "import", "scope": "prod", "enclosing": "<module>"},
]


def test_module_binding_used_by_from_imports(fx: GitRepo) -> None:
    """`LIMIT` импортируют `pkg/user.py:1` и `pkg/user2.py:1` (from-импорт): две записи, порядок по пути."""
    assert _build(fx, "pkg/consts.py::LIMIT")["links"]["used_by"] == _USED_LIMIT


def test_module_binding_without_importers_has_empty_used_by(fx: GitRepo) -> None:
    """`A` никто не импортирует: `used_by == []` (список, а не `null`)."""
    assert _build(fx, "pkg/consts.py::A")["links"]["used_by"] == []


def test_class_binding_used_by_is_empty_not_module_import(fx: GitRepo) -> None:
    """`Schema.KIND` - член класса: `used_by == []`, хотя `user.py` импортирует модульное имя `KIND`."""
    assert _build(fx, "pkg/consts.py::Schema.KIND")["links"]["used_by"] == []


def test_class_binding_named_like_imported_module_name_is_empty(fx: GitRepo) -> None:
    """Поле класса `build.Local.LIMIT` (имя совпадает с импортируемым модульным `LIMIT` другого файла): `[]`."""
    assert _build(fx, "pkg/nested.py::build.Local.LIMIT")["links"]["used_by"] == []


# ---------------------------------------------------------------- 6. схема JSON (4.6a-fixtures.md §3)

_BINDING_SCHEMA: dict[str, dict[str, tuple[type, ...]]] = {
    "purpose": {"text": (NONE,), "called_from": (NONE,), "called_from_more": (int,), "declared_at": (NONE,)},
    "interface": {"layer": (str,), "all": (list, NONE), "signature": (str,), "members": (NONE,)},
    "links": {
        "used_by": (list,),
        "uses": (NONE,),
        "subclasses": (NONE,),
        "call_sites": (NONE,),
        "call_sites_unresolved": (NONE,),
        "bases": (NONE,),
        "structural": (NONE,),
        "call_sites_by_name": (NONE,),
    },
    "runtime": {"processes": (NONE,), "threads": (NONE,), "commands": (NONE,), "io": (NONE,)},
    "checks": {"findings": (NONE,), "tests": (NONE,)},
    "status": {
        "tier": (str, NONE),
        "doc_missing": (NONE,),
        "dynamic": (NONE,),
        "stale": (list,),
        "frozen": (list,),
    },
}
_ENVELOPE_TYPES = {"passport": int, "kind": str, "id": str, "path": str, "line": int, "sha": str, "scanner": str}


@pytest.mark.parametrize(
    "ident",
    [
        "pkg/consts.py::LIMIT",
        "pkg/consts.py::Schema.rate",
        "pkg/consts.py::Alias",
        "pkg/frozen.py::LEVEL",
        "pkg/more.py::Owner.z",
    ],
)
def test_binding_json_matches_schema_table(fx: GitRepo, ident: str) -> None:
    """Типы ключей паспорта привязки - точно по таблице §3 (`type(x)`); JSON-совместим без `default=`."""
    p = _build(fx, ident)
    assert p["kind"] == "binding"
    for key, typ in _ENVELOPE_TYPES.items():
        assert type(p[key]) is typ, (key, p[key])
    for section, keys in _BINDING_SCHEMA.items():
        assert set(p[section]) == set(keys), (section, sorted(p[section]))
        for key, types in keys.items():
            assert type(p[section][key]) in types, f"{section}.{key}: {type(p[section][key]).__name__}"
    for path in p["status"]["stale"]:
        assert type(path) is str
    for head in p["status"]["frozen"]:
        assert set(head) == {"date", "text", "where"} and all(type(v) is str for v in head.values())
    assert json.loads(json.dumps(p)) == p


# ---------------------------------------------------------------- 7. текст паспорта (4.6a-fixtures.md §4)

_RATE_TEXT = """\
== pkg/consts.py::Schema.rate ==
pkg/consts.py:28; sha {sha}; scanner {scanner}
purpose: не искали
  зовут из: не искали
  declared_at: не искали
interface: layer other; signature : float = 1.5
  all: не искали
  members: не искали
links: найдено 0; не видно: динамика, аннотации, упоминания
  из продукта 0, из тестов 0
  used_by: —
  call_sites: не искали
  subclasses: не искали
  call_sites_unresolved: не искали
  uses: не искали
  bases: не искали
  structural: не искали
runtime: processes не искали
  threads: не искали
  commands: не искали
  io: не искали
checks: findings не искали
  tests: не искали
status: tier нет шапки; doc_missing не искали; dynamic не искали
  stale: —
  frozen: —"""


def test_render_text_full_literal_for_class_binding(fx: GitRepo) -> None:
    """`ref pkg/consts.py::Schema.rate --format passport` - 26 строк ровно по литералу §4 (RED 8, литерал 1)."""
    p = _build(fx, "pkg/consts.py::Schema.rate")
    text = _render(p)
    expected = _RATE_TEXT.format(sha=p["sha"], scanner=p["scanner"]).splitlines()
    assert _lines(text) == expected
    assert len(_lines(text)) == 26


def test_render_text_all_and_frozen_lines_literal(fx: GitRepo) -> None:
    """`ref pkg/frozen.py::Cfg.size`: строки литерала 2 §4 - адрес, `interface`, `all`, `status`, `frozen`."""
    p = _build(fx, "pkg/frozen.py::Cfg.size")
    lines = _lines(_render(p))
    assert lines[0] == "== pkg/frozen.py::Cfg.size =="
    assert f"pkg/frozen.py:10; sha {p['sha']}; scanner {p['scanner']}" in lines
    assert "interface: layer other; signature : int = 3" in lines
    assert "  all: pkg/frozen.py" in lines
    assert "status: tier core; doc_missing не искали; dynamic не искали" in lines
    assert "  frozen: 2026-01-01 схема заморожена (pkg/frozen.py:1)" in lines


def test_render_text_used_by_cut_by_budget(fx: GitRepo) -> None:
    """`render_text(<паспорт LIMIT>, budget=10)`: пометка среза `    показано 1 из 2; все: --all used_by`."""
    text = _render(_build(fx, "pkg/consts.py::LIMIT"), budget=10)
    assert "    показано 1 из 2; все: --all used_by" in text.splitlines()


def test_render_text_used_by_show_all_prints_both_rows(fx: GitRepo) -> None:
    """`show_all={"used_by"}`: обе строки `    <module> — pkg/user.py:1 (import)` и `... pkg/user2.py:1 (import)`."""
    lines = _render(_build(fx, "pkg/consts.py::LIMIT"), budget=10, show_all=frozenset({"used_by"})).splitlines()
    assert "    <module> — pkg/user.py:1 (import)" in lines
    assert "    <module> — pkg/user2.py:1 (import)" in lines
    assert not any("показано" in line for line in lines)


def test_render_text_show_all_rejects_unknown_section_for_binding(fx: GitRepo) -> None:
    """Для `kind == "binding"` `show_all` проверяется по `SHOW_ALL_SECTIONS`: чужое имя - `ValueError`."""
    p = _build(fx, "pkg/consts.py::LIMIT")
    with pytest.raises(ValueError):
        _render(p, show_all=frozenset({"members"}))


def test_render_text_show_all_accepts_known_sections_for_binding(fx: GitRepo) -> None:
    """Имена из `SHOW_ALL_SECTIONS` (`used_by`, `call_sites`, `tests`) для привязки допустимы - без исключения."""
    p = _build(fx, "pkg/consts.py::LIMIT")
    assert _render(p, show_all=frozenset({"used_by", "call_sites", "tests"})) != ""


# ---------------------------------------------------------------- 8. неизменность def/class/метода (зелёные уже сейчас)

_SYMBOL_KEYS = [
    "passport",
    "kind",
    "id",
    "path",
    "line",
    "sha",
    "scanner",
    "purpose",
    "interface",
    "links",
    "runtime",
    "checks",
    "status",
]


@pytest.mark.parametrize(
    ("name", "kind", "line"),
    [
        ("helper", "function", 15),
        ("f", "function", 19),
        ("Schema", "class", 26),
        ("Schema.Meta", "class", 31),
        ("Schema.__init__", "method", 34),
    ],
)
def test_def_and_class_passports_keep_their_kind_and_line(fx: GitRepo, name: str, kind: str, line: int) -> None:
    """Имена из `defs` дают прежний паспорт: прежний `kind`, `line` и конверт."""
    p = _build(fx, f"pkg/consts.py::{name}")
    assert p["kind"] == kind
    assert p["line"] == line
    assert list(p) == _SYMBOL_KEYS


def test_function_passport_sections_keep_old_value_rules(fx: GitRepo) -> None:
    """Паспорт функции: разделы по прежним правилам (не `null` привязки): `purpose.called_from` - список,
    `checks.tests` - список, `status.doc_missing` - bool, `runtime.threads` - список, `links.call_sites` - список."""
    p = _build(fx, "pkg/consts.py::helper")
    assert type(p["purpose"]["called_from"]) is list
    assert type(p["checks"]["tests"]) is list
    assert type(p["status"]["doc_missing"]) is bool
    assert type(p["runtime"]["threads"]) is list
    assert type(p["links"]["call_sites"]) is list
    assert type(p["links"]["subclasses"]) is list


def test_class_passport_members_still_list(fx: GitRepo) -> None:
    """`Schema` (класс): `interface.members` - список методов (`__init__`), поля-привязки в `members` не попадают."""
    members = _build(fx, "pkg/consts.py::Schema")["interface"]["members"]
    assert [m["name"] for m in members] == ["__init__"]


def test_def_passport_text_keeps_header_and_signature(fx: GitRepo) -> None:
    """Текст функции остаётся прежним (зелёный и сейчас): первая строка `== pkg/consts.py::helper ==`, строка
    `interface: layer other; signature ()`; текст `_render_binding` на него не влияет."""
    lines = _lines(_render(_build(fx, "pkg/consts.py::helper")))
    assert lines[0] == "== pkg/consts.py::helper =="
    assert "interface: layer other; signature ()" in lines


def test_broken_file_def_and_binding_not_found(fx: GitRepo) -> None:
    """Файл с ошибкой разбора (`pkg/broken.py`): привязка `BROKEN_X` не находится даже при корректной первой строке
    (охрана `facts.error`); зелёный и сейчас - красным станет только при потере охраны в реализации."""
    from scripts.atlas.passport import resolve_ident

    assert run_with_deadline(lambda: resolve_ident(fx.path, "HEAD", "pkg/broken.py::BROKEN_X"), 120.0) == []


# ---------------------------------------------------------------- 9. реальные id и эталон (клон на 1e085652f)


@pytest.fixture(scope="module")
def clone(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """`git clone --shared --no-checkout` + `checkout --detach 1e085652f` во временном каталоге."""
    dest = tmp_path_factory.mktemp("c4_6a") / "c"

    def run(*argv: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", check=False)

    probe = run_with_deadline(lambda: run("git", "-C", str(_CODE_ROOT), "cat-file", "-t", BASE_SHA), 60.0)
    if probe.returncode != 0 or probe.stdout.strip() != "commit":
        pytest.skip(f"коммит {BASE_SHA} недоступен в объектах репозитория: приёмка по реальным id не запускается")
    done = run_with_deadline(
        lambda: run("git", "clone", "-q", "--shared", "--no-checkout", str(_CODE_ROOT), str(dest)), 300.0
    )
    assert done.returncode == 0, done.stderr
    done = run_with_deadline(lambda: run("git", "-C", str(dest), "checkout", "-q", "--detach", BASE_SHA), 300.0)
    assert done.returncode == 0, done.stderr
    return dest


# (путь, имя в файле, строка, signature | None: проверяется только строка) - ACCEPTANCE, 20 привязок
_REAL = [
    ("Services/hikvision_camera/sdk/constants.py", "MV_USB_DEVICE", 13, ": int = 4"),
    (
        "multiprocess_framework/modules/process_module/configs/observation_policy.py",
        "LEGACY_SOURCE_NAME",
        125,
        "= 'telemetry.publish'",
    ),
    (
        "multiprocess_framework/modules/process_module/commands/builtin_commands.py",
        "_ORIGIN_SWITCH",
        56,
        "= 'switch:broadcast'",
    ),
    ("Services/device_hub/drivers/exchange_log.py", "_OP_NAME", 72, ": dict[int, str] = {}"),
    ("Plugins/sim/scene_source/plugin.py", "_DEFAULT_WIDTH", 102, "= 640"),
    ("Services/code_reader/plugin/sdk_plugin.py", "_COORD_LIMIT", 514, "= 2 ** 30"),
    ("Services/dataset_gen/export.py", "LabelsFormat", 33, "= Literal['csv', 'json', 'parquet']"),
    ("Services/ml_inference/core/model_spec.py", "LayoutType", 19, "= Literal['NCHW', 'NHWC']"),
    (
        "multiprocess_framework/modules/frontend_module/components/base/control_hooks.py",
        "ControlKind",
        14,
        "= Literal['checkbox', 'numeric', 'slider', 'spinbox']",
    ),
    (
        "Services/device_hub/kinds.py",
        "DriverBuild",
        53,
        "type = Callable[[type, DeviceEntry, Any, DriverContext], DeviceDriver]",
    ),
    ("multiprocess_framework/modules/recipe/migrations.py", "MigrationStep", 40, "= Callable[[dict], dict]"),
    (
        "multiprocess_framework/modules/process_module/commands/command_contracts.py",
        "WorkerCreateParams.priority",
        106,
        ": Optional[str] = None",
    ),
    ("Plugins/io/database/schemas.py", "DetectionSchema.timestamp", 39, ": float"),
    ("Services/robot_comm/kinematics.py", "ScaraModel.l1", 101, ": float = 325.0"),
    ("Plugins/render/renderer_compositor/registers.py", "RendererCompositorRegisters.layout_mode", 21, None),
    ("multiprocess_framework/modules/base_manager/types/process_status.py", "ProcessStatus.READY", 25, "= 'ready'"),
    (
        "Plugins/sources/capture/plugin.py",
        "CapturePlugin.REQUIRES",
        44,
        ": tuple[str, ...] = ('manager:command_manager',)",
    ),
    ("multiprocess_framework/modules/shared_resources_module/types/types.py", "ResourceType.EVENT", 25, "= 'event'"),
    ("Services/auth/models.py", "SessionEntry.SQLMeta.table_name", 262, "= 'auth_sessions'"),
    ("Services/documents/schema.py", "DocumentRow.SQLMeta.primary_key", 36, "= ['doc_id']"),
]

_BASELINE = [  # эталон `reports/4.6-baseline/`: (файл, id)
    ("def1.passport.txt", "Services/auth/models.py::SessionEntry.SQLMeta"),
    ("def2.passport.txt", "Plugins/sim/pult_web/plugin.py::_build_handler._PultHandler"),
    ("def3.passport.txt", "Plugins/sim/pult_web/plugin.py::_build_handler._PultHandler.log_message"),
    ("def4.passport.txt", "multiprocess_framework/modules/base_manager/interfaces.py::IHandle.kind"),
    ("def5.passport.txt", "Services/robot_comm/server/belt.py::BeltDrive.mm_s_at_max_freq"),
    ("def6.passport.txt", "Services/vfd_comm/core/client.py::VfdClient.config"),
    ("ProcessModule.passport.txt", "ProcessModule"),
]


@pytest.fixture(scope="module")
def real(clone: Path) -> dict[str, dict]:
    """Одна выборка паспортов за раз (один скан клона): 20 привязок, 7 эталонных id, голое `MV_USB_DEVICE`."""
    from scripts.atlas.passport import passports_for

    idents = [f"{p}::{n}" for p, n, _, _ in _REAL] + [i for _, i in _BASELINE] + ["MV_USB_DEVICE"]
    records = run_with_deadline(lambda: passports_for(clone, "HEAD", idents), CLONE_DEADLINE_S)
    return dict(zip(idents, records, strict=True))


@pytest.mark.parametrize(("path", "name", "line", "signature"), _REAL, ids=[f"{p}::{n}" for p, n, _, _ in _REAL])
def test_real_binding_id_passport(
    clone: Path, real: dict[str, dict], path: str, name: str, line: int, signature: str | None
) -> None:
    """Реальная привязка из ACCEPTANCE: паспорт `binding` без ошибки, `line` = литералу (строка файла содержит имя),
    вторая строка текста `<путь>:<N>; sha <40 hex>; scanner ...`, `interface:` кончается `signature <S>`."""
    ident = f"{path}::{name}"
    rec = real[ident]
    assert "error" not in rec, rec
    assert rec["kind"] == "binding"
    assert rec["line"] == line
    source_line = (clone / path).read_text(encoding="utf-8").splitlines()[line - 1]
    assert name.rsplit(".", 1)[-1] in source_line
    if signature is not None:
        assert rec["interface"]["signature"] == signature
    from scripts.atlas.passport import render_text

    lines = render_text(rec).splitlines()
    assert re.fullmatch(re.escape(f"{path}:{line}") + r"; sha [0-9a-f]{40}; scanner \S+", lines[1]), lines[1]
    iface = next(ln for ln in lines if ln.startswith("interface:"))
    if signature is not None:
        assert iface.endswith(f"signature {signature}")


def test_real_mv_usb_device_json_sections(real: dict[str, dict]) -> None:
    """`MV_USB_DEVICE --format json`: `used_by` - 6 записей (пути из ACCEPTANCE), `call_sites`, `bases`, `structural`,
    `checks.tests` - `null`."""
    rec = real["Services/hikvision_camera/sdk/constants.py::MV_USB_DEVICE"]
    assert "error" not in rec, rec
    assert rec["kind"] == "binding"
    used = rec["links"]["used_by"]
    assert len(used) == 6
    wheres = {e["where"] for e in used}
    for lined in (
        "Services/code_reader/tools/id3000_discover.py:46",
        "Services/hikvision_camera/core/camera.py:26",
        "Services/hikvision_camera/core/discovery.py:19",
        "Services/hikvision_camera/tools/mvs_probe.py:45",
    ):
        assert lined in wheres
    paths = {w.partition(":")[0] for w in wheres}
    assert "Services/hikvision_camera/sdk/__init__.py" in paths
    assert "Services/hikvision_camera/tests/test_constants.py" in paths
    assert rec["links"]["call_sites"] is None
    assert rec["links"]["bases"] is None
    assert rec["links"]["structural"] is None
    assert rec["checks"]["tests"] is None


def test_real_bare_mv_usb_device_not_found(real: dict[str, dict]) -> None:
    """21-й id - голое `MV_USB_DEVICE`: `not found` (код 2 в CLI)."""
    rec = real["MV_USB_DEVICE"]
    assert "error" in rec and "not found" in rec["error"]


@pytest.mark.parametrize(("file", "ident"), _BASELINE, ids=[b[0] for b in _BASELINE])
def test_baseline_text_unchanged(real: dict[str, dict], file: str, ident: str) -> None:
    """Эталон «до» (зелёный и сейчас): текст паспорта `def`/`class`/метода/`ProcessModule` на клоне 1e085652f
    побайтно равен файлу `reports/4.6-baseline/<file>`."""
    from scripts.atlas.passport import render_text

    expected = (BASELINE_DIR / file).read_text(encoding="utf-8")
    rec = real[ident]
    assert "error" not in rec, rec
    assert render_text(rec).rstrip("\n") == expected.rstrip("\n")


def test_baseline_process_module_json_unchanged(real: dict[str, dict]) -> None:
    """Эталон «до»: `ref ProcessModule --format json` побайтно равен `ProcessModule.json` (зелёный и сейчас)."""
    expected = (BASELINE_DIR / "ProcessModule.json").read_text(encoding="utf-8")
    got = json.dumps([real["ProcessModule"]], ensure_ascii=False, indent=2)
    assert got.rstrip("\n") == expected.rstrip("\n")
