"""Тесты автора Task 4.6a: паспорт привязки (`ref путь::ИМЯ` для констант, алиасов и полей) — REDS 1-9.

Purpose: красные до правки `passport.py`, зелёные после. Фикстура и литералы — `reports/4.6-baseline/4.6a-fixtures.md`
    §1-4 (`pkg/consts.py`, `pkg/user.py`, `pkg/user2.py`, `pkg/frozen.py`); номера строк — литералы по тексту
    фикстуры. Слепой набор — `test_passport_binding_blind_4_6a.py` (здесь не читается и не правится).
Public API: тесты test_*; публичных имён нет.
Stability: lite

Хелперы — из `conftest.py` (`repo`, `atlas`) и `test_passport_status.py` (`_commit`, `_build`, `_render`).
Ожидаемые значения — литералы, не вывод кода под тестом.
"""

from __future__ import annotations

import json

from scripts.atlas.tests.conftest import GitRepo, run_with_deadline
from scripts.atlas.tests.test_passport_status import _build, _commit, _render

__all__: list[str] = []

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

_FILES = {
    "pkg/__init__.py": "",
    "pkg/consts.py": _CONSTS,
    "pkg/user.py": "from pkg.consts import LIMIT, KIND\n",
    "pkg/user2.py": "from pkg.consts import LIMIT\n",
    "pkg/frozen.py": _FROZEN,
}
C = "pkg/consts.py::"


def _resolve(repo: GitRepo, ident: str) -> list[str]:
    from scripts.atlas.passport import resolve_ident

    return run_with_deadline(lambda: resolve_ident(repo.path, "HEAD", ident), 120.0)


def _setup(repo: GitRepo) -> None:
    _commit(repo, _FILES)


def test_empty_qualname_segment_is_not_binding(repo: GitRepo) -> None:
    """Ревью r1: пустой сегмент qualname (`.LIMIT`, `Schema..rate`, …) — не привязка, `[]` как до 4.6a."""
    _setup(repo)
    for bad in (".LIMIT", "LIMIT.", "Schema..rate", "Schema.rate.", ".Schema.rate", "."):
        assert _resolve(repo, C + bad) == [], bad
    assert _resolve(repo, C + "LIMIT") == ["pkg/consts.py::LIMIT"]


def test_module_constant_passport(repo: GitRepo) -> None:
    """RED 1: `LIMIT: int = 0x10` (строка 3, первый оператор) -> `binding`, строка 3, `: int = 16` (unparse)."""
    _setup(repo)
    p = _build(repo, C + "LIMIT")
    assert p["kind"] == "binding"
    assert p["id"] == "pkg/consts.py::LIMIT"
    assert p["path"] == "pkg/consts.py"
    assert p["line"] == 3
    assert p["interface"]["signature"] == ": int = 16"


def test_first_binding_wins_and_def_wins(repo: GitRepo) -> None:
    """RED 2: `LIMIT` повторно на строке 4 — побеждает строка 3; `A = B = 1` — обе цели, строка 5; `f` (def на 19 и
    `f = 1` на 23) — прежний паспорт функции."""
    _setup(repo)
    assert _build(repo, C + "LIMIT")["line"] == 3
    for name in ("A", "B"):
        p = _build(repo, C + name)
        assert (p["kind"], p["line"], p["interface"]["signature"]) == ("binding", 5, "= 1")
    f = _build(repo, C + "f")
    assert f["kind"] == "function"
    assert f["line"] == 19


def test_type_alias_and_literal_alias(repo: GitRepo) -> None:
    """RED 3: `type Alias = int | str` -> `type = int | str`; `Mode = Literal["a", "b"]` -> `= Literal['a', 'b']`."""
    _setup(repo)
    alias = _build(repo, C + "Alias")
    assert (alias["kind"], alias["line"], alias["interface"]["signature"]) == ("binding", 9, "type = int | str")
    mode = _build(repo, C + "Mode")
    assert (mode["kind"], mode["line"], mode["interface"]["signature"]) == ("binding", 10, "= Literal['a', 'b']")


def test_class_body_and_nested_class(repo: GitRepo) -> None:
    """RED 4: поля тела класса и вложенного класса: `Schema.count` 27, `rate` 28, `KIND` 29, `Schema.Meta.table` 32."""
    _setup(repo)
    expected = {
        "Schema.count": (27, ": int"),
        "Schema.rate": (28, ": float = 1.5"),
        "Schema.KIND": (29, "= 's'"),
        "Schema.Meta.table": (32, "= 't'"),
    }
    for qualname, (line, sig) in expected.items():
        p = _build(repo, C + qualname)
        assert p["kind"] == "binding", qualname
        assert p["id"] == C + qualname
        assert (p["line"], p["interface"]["signature"]) == (line, sig), qualname


def test_non_bindings_not_found(repo: GitRepo, atlas) -> None:
    """RED 5: контроль — `LIMIT` и `A` находятся (красный до правки); не привязки — `[]`: кортежная цель, `if`,
    локальная переменная функции, `self.x`, имя внутри метода, голое имя, пустой qualname. CLI — код 2."""
    _setup(repo)
    assert _resolve(repo, C + "LIMIT") == [C + "LIMIT"]
    assert _resolve(repo, C + "A") == [C + "A"]
    for ident in (
        C + "x",
        C + "HIDDEN",
        C + "helper.local",
        C + "Schema.inst",
        C + "Schema.__init__.x",
        "LIMIT",
        "pkg/consts.py::",
    ):
        assert _resolve(repo, ident) == [], ident
    res = atlas(repo, "ref", C + "x", "--format", "passport")
    assert res.code == 2 and "not found" in res.err
    res = atlas(repo, "ref", "LIMIT", "--format", "passport")
    assert res.code == 2 and "not found" in res.err


def test_binding_sections_null(repo: GitRepo) -> None:
    """RED 6: ключи `null` скелета §2 у `LIMIT` и `pkg/frozen.py::LEVEL`; `LEVEL`: `all == []` (в `__all__` лишь
    `Cfg`), `tier == "core"`, `frozen` литералом."""
    _setup(repo)
    for ident in (C + "LIMIT", "pkg/frozen.py::LEVEL"):
        p = _build(repo, ident)
        assert p["purpose"] == {"text": None, "called_from": None, "called_from_more": 0, "declared_at": None}
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
        assert p["runtime"] == {"processes": None, "threads": None, "commands": None, "io": None}
        assert p["checks"] == {"findings": None, "tests": None}
        assert p["status"]["doc_missing"] is None and p["status"]["dynamic"] is None
    level = _build(repo, "pkg/frozen.py::LEVEL")
    assert level["interface"]["all"] == []
    assert level["status"]["tier"] == "core"
    assert level["status"]["frozen"] == [{"date": "2026-01-01", "text": "схема заморожена", "where": "pkg/frozen.py:1"}]
    assert level["line"] == 6


def test_binding_used_by_from_import(repo: GitRepo) -> None:
    """RED 7: `LIMIT.used_by` — 2 записи from-импорта в порядке пути; `Schema.rate` и `Schema.KIND` — `[]` (импорт
    `KIND` — имя модуля); срез `budget=10` -> `показано 1 из 2`; `show_all={"used_by"}` — обе записи."""
    _setup(repo)
    p = _build(repo, C + "LIMIT")
    assert p["links"]["used_by"] == [
        {"where": "pkg/user.py:1", "how": "import", "scope": "prod", "enclosing": "<module>"},
        {"where": "pkg/user2.py:1", "how": "import", "scope": "prod", "enclosing": "<module>"},
    ]
    assert _build(repo, C + "Schema.rate")["links"]["used_by"] == []
    assert _build(repo, C + "Schema.KIND")["links"]["used_by"] == []
    cut = _render(p, budget=10).splitlines()
    assert "    показано 1 из 2; все: --all used_by" in cut
    full = _render(p, budget=10, show_all=frozenset({"used_by"})).splitlines()
    assert "    <module> — pkg/user.py:1 (import)" in full
    assert "    <module> — pkg/user2.py:1 (import)" in full
    assert not [s for s in full if s.strip().startswith("показано")]


_RATE_TEXT = """== pkg/consts.py::Schema.rate ==
pkg/consts.py:28; sha {sha}; scanner {scanner}
purpose: не искали
  зовут из: не искали
  declared_at: не искали
interface: layer other; signature : float = 1.5
  all: не искали
  members: не искали
links: найдено 0; не видно: динамика, аннотации, упоминания, импорт через фасад __init__
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


def test_binding_text_literal(repo: GitRepo) -> None:
    """RED 8: литерал 1 — текст `Schema.rate` целиком (26 строк); литерал 2 — `pkg/frozen.py::Cfg.size`: строки
    `all`, `status`, `frozen`."""
    _setup(repo)
    p = _build(repo, C + "Schema.rate")
    text = _render(p)
    assert text == _RATE_TEXT.format(sha=p["sha"], scanner=p["scanner"])
    assert len(text.splitlines()) == 26
    cfg = _build(repo, "pkg/frozen.py::Cfg.size")
    lines = _render(cfg).splitlines()
    assert lines[1] == f"pkg/frozen.py:10; sha {cfg['sha']}; scanner {cfg['scanner']}"
    assert "interface: layer other; signature : int = 3" in lines
    assert "  all: pkg/frozen.py" in lines
    assert "status: tier core; doc_missing не искали; dynamic не искали" in lines
    assert "  frozen: 2026-01-01 схема заморожена (pkg/frozen.py:1)" in lines


def test_value_cut_at_120(repo: GitRepo) -> None:
    """RED 9: `EXACT` — значение ровно 120 символов (`'` + 118 x + `'`), без среза; `OVER` — 121 символ: первые 120
    (`'` + 119 x) и `…`."""
    _setup(repo)
    assert _build(repo, C + "EXACT")["interface"]["signature"] == f"= '{_X118}'"
    assert _build(repo, C + "OVER")["interface"]["signature"] == f"= '{_X119}…"


def test_binding_json_roundtrip(repo: GitRepo) -> None:
    """Паспорт привязки — JSON-совместимый `dict` без `default=`; порядок ключей конверта прежний."""
    _setup(repo)
    p = _build(repo, C + "LIMIT")
    assert json.loads(json.dumps(p)) == p
    assert list(p)[:7] == ["passport", "kind", "id", "path", "line", "sha", "scanner"]


_FLOW = "\n".join(
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
        "OK = 1",  # 11
        "",
    ]
)


def test_try_with_for_while_names_not_bindings(repo: GitRepo) -> None:
    """Стадия 3 (инъекция 05c): имена из `try`/`except`/`with`/`for`/`while` модуля — не привязки (`[]`); прямой
    оператор `OK` (строка 11) в том же файле — привязка (контроль: тест не пустой)."""
    _commit(repo, {"pkg/__init__.py": "", "pkg/flow.py": _FLOW})
    assert _resolve(repo, "pkg/flow.py::OK") == ["pkg/flow.py::OK"]
    assert _build(repo, "pkg/flow.py::OK")["line"] == 11
    for name in ("T1", "T2", "W1", "F1", "WH"):
        assert _resolve(repo, f"pkg/flow.py::{name}") == [], name


def test_broken_facts_file_has_no_bindings(repo: GitRepo, monkeypatch) -> None:
    """Стадия 3 (инъекция 14): файл с `v2_error` (разбор полей v2 упал, `ast.parse` цел) и файл с `error` (упал разбор
    полей A1, `ast.parse` цел) привязок не дают — как и символов (контракт `Pre`/`Raises` `build_passport`). Контроль:
    тот же текст в файле без сбоя — привязка есть. Сбой — подмена `scan._collect_v2` / `scan.read_freeze`: у файла
    с настоящей синтаксической ошибкой охрану прикрывает `ast.parse`, и убрать её тест не заметил бы."""
    import ast

    from scripts.atlas import scan
    from scripts.atlas.passport import _Ctx

    def failing(real):
        def wrapper(tree, *args, **kwargs):
            if any(isinstance(n, ast.Name) and n.id == "TRIGGER_FAIL" for n in ast.walk(tree)):
                raise ValueError("boom")
            return real(tree, *args, **kwargs)

        return wrapper

    monkeypatch.setattr(scan, "_collect_v2", failing(scan._collect_v2))
    text = "GOOD = 2\n"
    _commit(repo, {"pkg/__init__.py": "", "pkg/ok.py": text, "pkg/v2.py": text + "TRIGGER_FAIL = 1\n"})
    facts = run_with_deadline(lambda: _Ctx.open(repo.path, "HEAD", ()).facts, 120.0)
    assert facts["pkg/ok.py"].error is None and facts["pkg/ok.py"].v2_error is None
    assert facts["pkg/v2.py"].v2_error == "ValueError" and facts["pkg/v2.py"].error is None
    assert _resolve(repo, "pkg/ok.py::GOOD") == ["pkg/ok.py::GOOD"]
    assert _resolve(repo, "pkg/v2.py::GOOD") == []

    monkeypatch.setattr(scan, "read_freeze", failing(scan.read_freeze))
    _commit(repo, {"pkg/a1.py": "GOOD = 3\nTRIGGER_FAIL = 1\n"})  # другой текст: тот же blob взял бы факты из кэша
    facts = run_with_deadline(lambda: _Ctx.open(repo.path, "HEAD", ()).facts, 120.0)
    assert facts["pkg/a1.py"].error == "ValueError"
    assert _resolve(repo, "pkg/a1.py::GOOD") == []
