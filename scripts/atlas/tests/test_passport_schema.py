"""Слепой контрактный тест JSON-схемы паспорта символа (Task 4.2b-1, stage 2, RED до кода): REDS 5.

Purpose: схема паспорта руками, без `jsonschema`: словарь «ключ -> тип» конверта, шести разделов и подключей `status`
    для `class` | `function` | `method` (unit/file — Task 4.2b-2). `status.stale` и `status.frozen` — `list` (чистый
    репозиторий — `[]`, не `null`), элемент `frozen` — `dict` из `date`, `text`, `where` (все `str`), элемент `stale` —
    `str`. Контракт — таблицы модульного докстринга `scripts/atlas/passport.py`; реализации stale/frozen при записи
    теста нет (INTERFACE: оба ключа `null`).
Public API: тест test_passport_json_matches_schema; публичных имён нет.
Stability: lite

Типы проверяются точно (`type(x)`): `bool` — не `int`. Ожидаемые значения — литералы. Вызовы идут в daemon-потоке с
дедлайном (помощники `test_passport_status`).
"""

from __future__ import annotations

import json

from scripts.atlas.tests.conftest import GitRepo
from scripts.atlas.tests.test_passport_status import _append, _build, _commit

__all__: list[str] = []

NONE = type(None)

_FILES = {
    "pkg/__init__.py": "",
    "pkg/mod.py": (
        '"""Модуль.\n'  # 1
        "\n"  # 2
        "Tier: core\n"  # 3
        "FREEZE 2026-04-01: не менять публичный API\n"  # 4
        '"""\n'  # 5
        "\n"  # 6
        "\n"  # 7
        "class Handler:\n"  # 8
        '    """Обработчик."""\n'  # 9
        "\n"  # 10
        "    def run(self, x: int) -> str:\n"  # 11
        '        """Запуск."""\n'  # 12
        "        return str(x)\n"  # 13
        "\n"  # 14
        "\n"  # 15
        "def helper(a: int) -> bool:\n"  # 16
        '    """Помощник."""\n'  # 17
        "    return True\n"  # 18
    ),
    "pkg/caller.py": "from pkg.mod import helper\n\n\ndef go():\n    helper(1)\n",
}

ENVELOPE = {
    "passport": (int,),
    "kind": (str,),
    "id": (str,),
    "path": (str,),
    "line": (int,),
    "sha": (str,),
    "scanner": (str,),
}
SECTIONS = ["purpose", "interface", "links", "runtime", "checks", "status"]

_COMMON = {
    "purpose": {
        "text": (str,),
        "called_from": (list,),
        "called_from_more": (int,),
        "declared_at": (NONE,),
    },
    "runtime": {
        "processes": (NONE,),
        "threads": (list,),
        "commands": (list, NONE),
        "io": (list,),
    },
    "checks": {
        "findings": (NONE,),
        "tests": (list,),
    },
    "status": {
        "tier": (str, NONE),
        "doc_missing": (bool,),
        "dynamic": (int,),
        "stale": (list,),
        "frozen": (list,),
    },
}


def _schema(kind: str) -> dict[str, dict[str, tuple[type, ...]]]:
    """Схема «раздел -> ключ -> допустимые типы» для вида символа; не относящееся к виду — `null`."""
    is_class = kind == "class"
    return {
        **_COMMON,
        "interface": {
            "layer": (str,),
            "all": (list, NONE),
            "signature": (str,),
            "members": (list,) if is_class else (NONE,),
        },
        "links": {
            "used_by": (list,),
            "uses": (NONE,),
            "subclasses": (list,),
            "call_sites": (list,),
            "call_sites_unresolved": (int,),
            "bases": (list,) if is_class else (NONE,),
            "structural": (dict, NONE) if is_class else (NONE,),
            "call_sites_by_name": (dict,) if kind == "method" else (NONE,),  # Task 4.5b
        },
    }


def _check(p: dict, kind: str) -> None:
    assert p["kind"] == kind
    assert list(p)[: len(ENVELOPE)] == list(ENVELOPE)  # конверт первым, в порядке докстринга
    assert [k for k in p if k in SECTIONS] == SECTIONS
    assert set(p) == set(ENVELOPE) | set(SECTIONS)
    for key, types in ENVELOPE.items():
        assert type(p[key]) in types, (key, p[key])
    for section, keys in _schema(kind).items():
        assert set(p[section]) == set(keys), (section, sorted(p[section]))
        for key, types in keys.items():
            value = p[section][key]
            assert type(value) in types, f"{section}.{key}: {type(value).__name__} вместо {[t.__name__ for t in types]}"
    status = p["status"]
    for path in status["stale"]:
        assert type(path) is str  # элемент `stale` — путь
    for head in status["frozen"]:
        assert type(head) is dict
        assert set(head) == {"date", "text", "where"}, head
        assert all(type(v) is str for v in head.values()), head
    assert json.loads(json.dumps(p)) == p  # JSON-совместимый `dict` без `default=`


def test_passport_json_matches_schema(repo: GitRepo) -> None:
    """Конверт, шесть разделов и подключи `status` — по «ключу -> типу» для класса, функции и метода; `stale` и
    `frozen` — `list` (чистый репозиторий: `stale == []`), элемент `frozen` — `dict` {date, text, where}; после правки
    файла связи элемент `stale` — `str`."""
    _commit(repo, _FILES)
    klass = _build(repo, "pkg/mod.py::Handler")
    func = _build(repo, "pkg/mod.py::helper")
    method = _build(repo, "pkg/mod.py::Handler.run")
    _check(klass, "class")
    _check(func, "function")
    _check(method, "method")
    for p in (klass, func, method):
        assert p["status"]["stale"] == []  # чистый репозиторий, `sha` = HEAD
        assert p["status"]["frozen"] == [
            {"date": "2026-04-01", "text": "не менять публичный API", "where": "pkg/mod.py:4"}
        ]  # непустой: проверен тип элемента

    _append(repo, "pkg/caller.py")
    dirty = _build(repo, "pkg/mod.py::helper")
    _check(dirty, "function")
    assert dirty["status"]["stale"] == ["pkg/caller.py"]


# ---------------------------------------------------------------- Task 4.5b: оговорки и вызовы по имени (REDS 2-8)

THREADS_NOTE = "threads: — (ищет: Thread, Timer, Observer)"
COMMANDS_NOTE = "(ищет только def command_specs(); register_command(...) не читает)"
IO_NOTE = "io: — (ищет: Observer.schedule, os.rename, os.replace, shutil.move)"

_EMPTY_FILES = {
    "pkg/__init__.py": "",
    "pkg/svc.py": "class Plain:\n    pass\n\n\nclass Declared:\n    def command_specs(self):\n        return []\n",
}

_STEP = "class Step:\n    def run_x(self):\n        return 1\n\n    def other(self):\n        self.run_x()\n"
STEP = "pkg/step.py::Step.run_x"


def _text_lines(p: dict) -> list[str]:
    from scripts.atlas.tests.test_passport_status import _render

    return [line.strip() for line in _render(p, full=True).splitlines()]


def _by_name_files(prod: int, tests: int = 0) -> dict[str, str]:
    files = {"pkg/__init__.py": "", "pkg/step.py": _STEP}
    if prod:
        files["pkg/many.py"] = "def many(step):\n" + "    step.run_x()\n" * prod
    if tests:
        files["tests/__init__.py"] = ""
        files["tests/test_step.py"] = "def test_a(step):\n" + "    step.run_x()\n" * tests
    return files


def test_empty_threads_prints_patterns_caveat(repo: GitRepo) -> None:
    """RED 4.5b п. 2: пустой `threads` символа -> `threads: — (ищет: Thread, Timer, Observer)`; JSON — `[]`."""
    _commit(repo, _EMPTY_FILES)
    p = _build(repo, "pkg/svc.py::Plain")
    assert p["runtime"]["threads"] == []
    lines = _text_lines(p)
    assert THREADS_NOTE in lines
    assert "threads: —" not in lines


def test_empty_commands_prints_command_specs_caveat(repo: GitRepo) -> None:
    """RED 4.5b п. 2: `commands` `[]` -> `commands: — (оговорка)`; `null` -> `_NO_SPECS`, пробел, оговорка в конце."""
    _commit(repo, _EMPTY_FILES)
    declared = _build(repo, "pkg/svc.py::Declared")
    plain = _build(repo, "pkg/svc.py::Plain")
    assert declared["runtime"]["commands"] == [] and plain["runtime"]["commands"] is None
    assert f"commands: — {COMMANDS_NOTE}" in _text_lines(declared)
    assert f"commands: форма command_specs() не объявлена {COMMANDS_NOTE}" in _text_lines(plain)


def test_empty_io_caveat_comes_from_constant(repo: GitRepo, monkeypatch) -> None:
    """RED 4.5b п. 2: пустой `io` -> `io: — (ищет: <IO_PATTERNS>)`; `IO_PATTERNS` собран из `_REPLACES` и
    `Observer.schedule`; текст берётся из константы при печати (подмена константы меняет строку)."""
    from scripts.atlas import passport, scan

    assert set(scan.IO_PATTERNS) == {"Observer.schedule", "os.replace", "os.rename", "shutil.move"}
    assert set(scan.IO_PATTERNS) == {"Observer.schedule"} | {f"{m}.{f}" for m, f in scan._REPLACES}
    _commit(repo, _EMPTY_FILES)
    p = _build(repo, "pkg/svc.py::Plain")
    assert p["runtime"]["io"] == []
    assert IO_NOTE in _text_lines(p)
    monkeypatch.setattr(passport, "IO_PATTERNS", ("Fake.io",))
    assert "io: — (ищет: Fake.io)" in _text_lines(p)


def test_method_by_name_few_addresses_listed(repo: GitRepo) -> None:
    """RED 4.5b п. 3: три вызова `step.run_x()` в трёх prod-файлах -> count 3, три записи `how: "by-name"`; текст —
    заголовок `по имени метода, тип не проверен (3):` и строка на адрес."""
    files = {"pkg/__init__.py": "", "pkg/step.py": _STEP}
    for x in "abc":
        files[f"pkg/{x}.py"] = f"def caller_{x}(step):\n    step.run_x()\n"
    _commit(repo, files)
    p = _build(repo, STEP)
    got = p["links"]["call_sites_by_name"]
    assert got["count"] == 3
    assert [(e["where"], e["how"], e["scope"], e["same_file"]) for e in got["items"]] == [
        ("pkg/a.py:2", "by-name", "prod", False),
        ("pkg/b.py:2", "by-name", "prod", False),
        ("pkg/c.py:2", "by-name", "prod", False),
    ]
    lines = _text_lines(p)
    assert "по имени метода, тип не проверен (3):" in lines
    for x in "abc":
        assert f"caller_{x} — pkg/{x}.py:2 (by-name)" in lines


def test_method_by_name_threshold(repo: GitRepo) -> None:
    """RED 4.5b п. 3: граница 10 — 10 вызовов -> 10 записей `items`; 11 -> `items` null, строка «имя частое»."""
    _commit(repo, _by_name_files(10))
    ten = _build(repo, STEP)
    assert ten["links"]["call_sites_by_name"]["count"] == 10
    assert len(ten["links"]["call_sites_by_name"]["items"]) == 10
    assert "по имени метода, тип не проверен (10):" in _text_lines(ten)
    _commit(repo, _by_name_files(11))
    eleven = _build(repo, STEP)
    assert eleven["links"]["call_sites_by_name"] == {"count": 11, "items": None}
    lines = _text_lines(eleven)
    assert "по имени метода (prod, без self): 11 вызовов .run_x(...) - имя частое, адреса не печатаются" in lines
    assert not [s for s in lines if "pkg/many.py:" in s]


def test_method_by_name_excludes_tests_scope(repo: GitRepo) -> None:
    """RED 4.5b п. 3: вызовы из тест-файла (scope tests) в `call_sites_by_name` не идут: 1 prod + 2 test -> count 1."""
    _commit(repo, _by_name_files(1, tests=2))
    got = _build(repo, STEP)["links"]["call_sites_by_name"]
    assert got["count"] == 1
    assert [e["where"] for e in got["items"]] == ["pkg/many.py:2"]


def test_method_passport_has_call_sites_by_name(repo: GitRepo) -> None:
    """RED 4.5b п. 4: ключ `links.call_sites_by_name` — `dict` у метода (`{"count": 0, "items": []}` без внешних
    вызовов), `null` у класса и функции; схема `_schema` сверяет ключи равенством множеств."""
    _commit(repo, _FILES)
    method = _build(repo, "pkg/mod.py::Handler.run")
    _check(method, "method")
    assert method["links"]["call_sites_by_name"] == {"count": 0, "items": []}
    for ident, kind in (("pkg/mod.py::Handler", "class"), ("pkg/mod.py::helper", "function")):
        p = _build(repo, ident)
        _check(p, kind)
        assert p["links"]["call_sites_by_name"] is None


def test_method_by_name_slice_lifted_by_all_call_sites(repo: GitRepo) -> None:
    """4.5b п. 3: адреса по имени — список среза (`_alloc`): `--budget 1` режет до 1 записи с пометкой
    `--all call_sites`; `show_all={"call_sites"}` снимает и этот срез (3 записи, пометки нет)."""
    from scripts.atlas.tests.test_passport_status import _render

    files = {"pkg/__init__.py": "", "pkg/step.py": _STEP}
    for x in "abc":
        files[f"pkg/{x}.py"] = f"def caller_{x}(step):\n    step.run_x()\n"
    _commit(repo, files)
    p = _build(repo, STEP)
    cut = [s.strip() for s in _render(p, budget=1).splitlines()]
    head = cut.index("по имени метода, тип не проверен (3):")
    assert cut[head + 1 : head + 3] == ["caller_a — pkg/a.py:2 (by-name)", "показано 1 из 3; все: --all call_sites"]
    lifted = [s.strip() for s in _render(p, budget=1, show_all=frozenset({"call_sites"})).splitlines()]
    head = lifted.index("по имени метода, тип не проверен (3):")
    assert lifted[head + 1 : head + 4] == [f"caller_{x} — pkg/{x}.py:2 (by-name)" for x in "abc"]
    assert not [s for s in lifted if s.startswith("показано")]


def test_method_by_name_excludes_self_receiver(repo: GitRepo) -> None:
    """4.5b п. 3: неотнесённый `self.run_x()` (у класса `Other` метода нет) в `call_sites_by_name` не идёт, хотя он
    в `call_sites_unresolved`; `obj.run_x()` из того же файла идёт."""
    files = {
        "pkg/__init__.py": "",
        "pkg/step.py": _STEP,
        "pkg/other.py": "class Other:\n    def go(self, obj):\n        self.run_x()\n        obj.run_x()\n",
    }
    _commit(repo, files)
    p = _build(repo, STEP)
    assert p["links"]["call_sites_unresolved"] == 2
    got = p["links"]["call_sites_by_name"]
    assert got["count"] == 1
    assert [(e["where"], e["enclosing"]) for e in got["items"]] == [("pkg/other.py:4", "Other.go")]
