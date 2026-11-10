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
