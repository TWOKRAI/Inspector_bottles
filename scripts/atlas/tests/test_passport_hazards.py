"""Авторские hazard-тесты паспорта (Task 4.2a GREEN): что приёмочные RED 1-10 не покрывают.

Purpose: `exclude` по границе каталога (не по подстроке), `::`-id в исключённом файле, `not found`/`ambiguous` и дубли
    в `passports_for`, символ в непарсящемся файле, основа без адреса в JSON (`where: null`), непустые `threads`/`io`
    только своей области, `command_specs` с нелитеральным `return` и формой `name=`, круг тела кэша.
Public API: тесты test_*; публичных имён нет.
Stability: lite

Ожидания — литералы (номера строк — из текста фикстуры, без маркеров). Вызовы — в daemon-потоке с дедлайном.
"""

from __future__ import annotations

import pytest

from scripts.atlas.tests.conftest import GitRepo, run_with_deadline

__all__: list[str] = []

DEADLINE_S = 120.0


def _commit(repo: GitRepo, files: dict[str, str]) -> None:
    for rel, text in files.items():
        repo.write(rel, text)
    repo.commit("fixture")


def _many(repo: GitRepo, idents: list[str], **kwargs: object) -> list[dict]:
    from scripts.atlas.passport import passports_for

    return run_with_deadline(lambda: passports_for(repo.path, "HEAD", idents, **kwargs), DEADLINE_S)


def _one(repo: GitRepo, ident: str, **kwargs: object) -> dict:
    from scripts.atlas.passport import build_passport

    return run_with_deadline(lambda: build_passport(repo.path, "HEAD", ident, **kwargs), DEADLINE_S)


_EXCL = {
    "pkg/__init__.py": "",
    "pkg/lib.py": "def used():\n    return 1\n",
    "pkg/gen/__init__.py": "",
    "pkg/gen/auto.py": "from pkg.lib import used\n\n\ndef regen():\n    used()\n",
    "pkg/generic.py": "from pkg.lib import used\n\n\ndef generic():\n    used()\n",
}


def test_exclude_is_directory_boundary_not_substring(repo: GitRepo) -> None:
    """`exclude=("pkg/gen",)` режет `pkg/gen/auto.py`, но не `pkg/generic.py`; символ исключённого файла — `not found`
    и `AtlasError` у `build_passport`."""
    from scripts.atlas.tree import AtlasError

    _commit(repo, _EXCL)
    [p] = _many(repo, ["pkg/lib.py::used"], exclude=("pkg/gen",))
    assert [e["where"] for e in p["links"]["call_sites"]] == ["pkg/generic.py:5"]
    assert [e["where"] for e in p["links"]["used_by"]] == ["pkg/generic.py:1"]
    assert _many(repo, ["pkg/gen/auto.py::regen", "regen"], exclude=("pkg/gen/",)) == [
        {"id": "pkg/gen/auto.py::regen", "error": "not found"},
        {"id": "regen", "error": "not found"},
    ]
    with pytest.raises(AtlasError):
        _one(repo, "pkg/gen/auto.py::regen", exclude=("pkg/gen",))


_ERR = {
    "pkg/__init__.py": "",
    "pkg/a.py": "def dup():\n    return 1\n\n\ndef solo():\n    return 2\n",
    "pkg/b.py": "def dup():\n    return 3\n",
    "pkg/bad.py": "def broken(:\n    return 4\n",
}


def test_errors_ambiguous_duplicates_and_unparsable_file(repo: GitRepo) -> None:
    """Порядок и дубли `idents` сохраняются; `ambiguous` — кандидаты по пути; символ непарсящегося файла — `not found`
    (паспорт не бросает), соседний паспорт полон."""
    _commit(repo, _ERR)
    got = _many(repo, ["dup", "solo", "pkg/bad.py::broken", "broken", "solo", "pkg/a.py::nope"])
    assert got[0] == {"id": "dup", "error": "ambiguous", "candidates": ["pkg/a.py::dup", "pkg/b.py::dup"]}
    assert (got[1]["id"], got[1]["kind"], got[1]["line"]) == ("pkg/a.py::solo", "function", 5)
    assert got[2] == {"id": "pkg/bad.py::broken", "error": "not found"}
    assert got[3] == {"id": "broken", "error": "not found"}
    assert got[4] == got[1]  # дубль id -> дубль записи
    assert got[5] == {"id": "pkg/a.py::nope", "error": "not found"}


_BASES = {
    "pkg/__init__.py": "",
    "pkg/base.py": "class Base:\n    pass\n",
    "pkg/mod.py": "import abc\n\nfrom pkg.base import Base\n\n\nclass K(abc.ABC, Base):\n    pass\n",
}


def test_unresolved_base_is_where_null_record_not_null_section(repo: GitRepo) -> None:
    """Основа без адреса — запись с `where/how/scope: null` (адрес не разрешён), раздел `bases` — список."""
    _commit(repo, _BASES)
    p = _one(repo, "pkg/mod.py::K")
    assert p["links"]["bases"] == [
        {"name": "abc.ABC", "where": None, "how": None, "scope": None},
        {"name": "Base", "where": "pkg/base.py:1", "how": "import", "scope": "prod"},
    ]
    base = _one(repo, "pkg/base.py::Base")
    assert [(e["where"], e["how"], e["enclosing"]) for e in base["links"]["subclasses"]] == [
        ("pkg/mod.py:6", "import", "K")
    ]


_RUN = {
    "pkg/__init__.py": "",
    "pkg/svc.py": """\
import os
import threading


class Svc:
    def start(self):
        threading.Thread(target=self.run, daemon=True).start()

    def save(self, tmp, dst):
        os.replace(tmp, dst)


def other(a, b):
    t = threading.Timer(1.0, print)
    t.start()
    os.rename(a, b)
""",
}


def test_threads_and_io_only_inside_symbol(repo: GitRepo) -> None:
    """Пуски и `replaces` метода входят в паспорт класса, чужие (функция `other`) — нет; `where` — строка вызова."""
    _commit(repo, _RUN)
    svc = _one(repo, "pkg/svc.py::Svc")["runtime"]
    assert svc["threads"] == [{"pattern": "Thread", "daemon": True, "where": "pkg/svc.py:7"}]
    assert svc["io"] == [{"op": "replaces", "path": "dst", "where": "pkg/svc.py:10"}]
    other = _one(repo, "pkg/svc.py::other")["runtime"]
    assert other["threads"] == [{"pattern": "Timer", "daemon": None, "where": "pkg/svc.py:14"}]
    assert other["io"] == [{"op": "replaces", "path": "b", "where": "pkg/svc.py:16"}]
    method = _one(repo, "pkg/svc.py::Svc.save")["runtime"]
    assert method["threads"] == [] and len(method["io"]) == 1


_SPECS = {
    "pkg/__init__.py": "",
    "pkg/svc.py": """\
SPECS = []


class Dyn:
    def command_specs(self):
        return SPECS


class Kw:
    def command_specs(self):
        return (CommandSpec(name="halt"), CommandSpec(help="без имени"))
""",
}


def test_command_specs_nonliteral_return_and_name_keyword(repo: GitRepo) -> None:
    """`return SPECS` — объявлена, записей нет, одна динамика; `CommandSpec(name=...)` — запись; без имени — dynamic."""
    _commit(repo, _SPECS)
    dyn = _one(repo, "pkg/svc.py::Dyn")
    assert dyn["runtime"]["commands"] == [] and dyn["status"]["dynamic"] == 1
    kw = _one(repo, "pkg/svc.py::Kw")
    assert kw["runtime"]["commands"] == [{"name": "halt", "where": "pkg/svc.py:11", "how": "declared"}]
    assert kw["status"]["dynamic"] == 1


def test_command_specs_survive_cache_body() -> None:
    """Тело кэша несёт `command_specs`: круг `to_json` -> `from_json` равен, `None` остаётся `None`."""
    from scripts.atlas.scan import FileFacts, scan_text

    facts = scan_text(_SPECS["pkg/svc.py"])
    assert facts.command_specs == (
        ("", 6, "dynamic", "Dyn.command_specs"),
        ("halt", 11, "call", "Kw.command_specs"),
        ("", 11, "dynamic", "Kw.command_specs"),
    )
    assert facts.command_specs_dynamic == 2
    assert FileFacts.from_json(facts.to_json()) == facts
    plain = scan_text("def f():\n    return 1\n")
    assert plain.command_specs is None and FileFacts.from_json(plain.to_json()).command_specs is None
