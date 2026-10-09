"""Тесты по замечаниям reviewer'а (раунд 2) к Атласу 1.6c: общее множество П1, абстрактные свойства, базы модулей.

Purpose: фикстура с корневым пакетом `pk` (модули c, r, t framework и u prototype) и пин-проверки:
    1) абстрактное `@property` + `@abstractmethod` считается; 2) относительный импорт базы `from ..c.interfaces import
    IChan` разрешается; 3) структурная реализация с предком из другого модуля видна в `ref`, находке P1 и доле `card`
    одновременно; 4) интерфейс-реэкспорт ищется по модулю определения; 5) встроенные базы (str, RuntimeError) не дают
    «не определён»; 6) `Path.open("w")` — запись П4; 7) согласие griffe-счёта абстрактных с AST (`Scan.abstract`).
Public API: тесты test_*; публичных имён нет.
Stability: lite

Ожидаемые значения выведены ВРУЧНУЮ из текста фикстуры (номера строк — строки самих файлов) либо взяты из вывода
reviewer'а на пине 857a0248fc554493d40816f19295ffb68763a373.
"""

from __future__ import annotations

import json
import re
from typing import Any

import pytest

from scripts.atlas.tests.conftest import GitRepo, RepoFactory
from scripts.atlas.tests.test_exam_k0 import _M, _PINNED, pin_db, pinned  # noqa: F401 - фикстуры пина
from scripts.atlas.tests.test_ref_code import REFS, block, commit, lines_of, new_repo, put

__all__: list[str] = []

YAML = """version: 1
modules:
  - {id: c, paths: ["pk/c/"], layer: framework, tier: null, docs: [], parent: null}
  - {id: r, paths: ["pk/r/"], layer: framework, tier: null, docs: [], parent: null}
  - {id: t, paths: ["pk/t/"], layer: framework, tier: null, docs: [], parent: null}
  - {id: u, paths: ["pk/u/"], layer: prototype, tier: null, docs: [], parent: null}
"""
C_IFACE = '''\
"""c."""
from abc import ABC, abstractmethod

__all__ = ["IChan"]


class IChan(ABC):
    """Канал."""

    @property
    @abstractmethod
    def ident(self) -> str:
        """Идентификатор."""

    @abstractmethod
    def send(self) -> None:
        """Отправить."""
'''
C_HELPER = '''\
"""Помощник."""


class Helper:
    """Помощник канала."""

    @property
    def ident(self) -> str:
        return "h"

    def send(self) -> None:
        return None
'''
R_IFACE = '''\
"""r."""
from abc import ABC, abstractmethod

from ..c.interfaces import IChan

__all__ = ["IMsg"]


class IMsg(IChan, ABC):
    """Сообщения."""

    @abstractmethod
    def post(self, text: str) -> None:
        """Отправить текст."""

    @abstractmethod
    def peek(self) -> str:
        """Посмотреть."""
'''
R_MGR = '''\
from pk.c.helper import Helper


class Mgr(Helper):
    """Менеджер."""

    def post(self, text: str) -> None:
        return None

    def peek(self) -> str:
        return ""
'''
T_SPEC = '"""Спецификация."""\n\n\nclass Spec:\n    """Спека вкладки."""\n'
T_TABS = 'from ..spec import Spec\n\n__all__ = ["Spec"]\n'
T_IFACE = '''\
"""t."""
from enum import Enum

from .spec import Spec

__all__ = ["Spec", "Level", "Boom"]


class Level(str, Enum):
    """Уровень."""


class Boom(RuntimeError):
    """Ошибка."""
'''
T_IO = """\
import os


def save(tmp, path):
    with tmp.open("w") as fh:
        fh.write("x")
    os.replace(tmp, path)


def dump(path):
    with path.open("w", encoding="utf-8") as fh:
        fh.write("y")
"""
U_USE = "from pk.t.tabs import Spec\n\n\ndef make():\n    return Spec()\n"
T_TEST = "from pk.t.tabs import Spec\n\n\ndef test_spec():\n    assert Spec() is not None\n"

FILES = {
    "pk/__init__.py": "",
    "pk/c/__init__.py": "",
    "pk/c/interfaces.py": C_IFACE,
    "pk/c/helper.py": C_HELPER,
    "pk/r/__init__.py": "",
    "pk/r/interfaces.py": R_IFACE,
    "pk/r/mgr.py": R_MGR,
    "pk/t/__init__.py": "",
    "pk/t/spec.py": T_SPEC,
    "pk/t/tabs/__init__.py": T_TABS,
    "pk/t/interfaces.py": T_IFACE,
    "pk/t/io.py": T_IO,
    "pk/t/tests/test_spec.py": T_TEST,
    "pk/u/__init__.py": "",
    "pk/u/use.py": U_USE,
}


def pk_repo(factory: RepoFactory, mp: pytest.MonkeyPatch, name: str = "pk") -> GitRepo:
    repo = new_repo(factory, name)
    repo.write("modules.yaml", YAML)
    for rel, text in FILES.items():
        put(repo, rel, text)
    commit(repo, mp, "2026-10-01", "init")
    return repo


# ---------------------------------------------------------------- замечания 1-3: абстрактные, базы, П1

# ---------------------------------------------------------------- замечания 1-3: абстрактные, базы, П1


def test_abstract_property_is_counted_and_agrees_with_ast(
    repo_factory: RepoFactory, atlas: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = pk_repo(repo_factory, monkeypatch)
    lines = lines_of(atlas(repo, "ref", "c", *REFS))
    assert block(lines, "IChan — ")[:2] == [
        "IChan — Канал — pk/c/interfaces.py:7 — тестов 0",
        "  вид: ABC; базы: ABC; абстрактных 2 (своих 2)",
    ]
    from scripts.atlas.modules import parse_modules
    from scripts.atlas.rules import Scan

    rows = parse_modules(YAML)
    sources = {rel: text for rel, text in FILES.items()}
    scan = Scan(sources, rows)
    assert len(scan.abstract(("pk/c/interfaces.py", "IChan"))) == 2
    assert len(scan.abstract(("pk/r/interfaces.py", "IMsg"))) == 4


def test_relative_base_from_another_module_resolves(
    repo_factory: RepoFactory, atlas: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = pk_repo(repo_factory, monkeypatch)
    lines = lines_of(atlas(repo, "ref", "r", *REFS))
    assert block(lines, "IMsg — ") == [
        "IMsg — Сообщения — pk/r/interfaces.py:9 — тестов 0",
        "  вид: ABC; базы: IChan, ABC; абстрактных 4 (своих 2)",
        "  post(text: str) -> None  :13",
        "    Отправить текст",
        "  peek() -> str  :17",
        "    Посмотреть",
        "  унаследованные абстрактные от IChan (2): ident, send",
        "  реализации (1):",
        "    Mgr — структурно — pk/r/mgr.py:4",
    ]


def test_p1_finding_ref_pair_and_card_share_are_one_set(
    repo_factory: RepoFactory, atlas: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = pk_repo(repo_factory, monkeypatch)
    res = atlas(repo, "--json", *REFS)
    assert res.code == 0, res.err
    p1 = sorted(
        (f["node"], f["detail"], f["source"])
        for f in json.loads(res.out)["findings"]
        if f["code"] == "P1_IMPL_NOT_INHERITING"
    )
    assert p1 == [
        ("module:c", "Helper>IChan", "pk/c/helper.py:4"),
        ("module:r", "Mgr>IMsg", "pk/r/mgr.py:4"),
    ]
    card = lines_of(atlas(repo, "card", "r", *REFS))
    assert "  П1 реализации с явным наследованием: 0 из 1" in card
    assert "  warning P1_IMPL_NOT_INHERITING module:r Mgr>IMsg" in card


# ---------------------------------------------------------------- замечания 4-6


def test_reexported_interface_uses_the_defining_module(
    repo_factory: RepoFactory, atlas: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = pk_repo(repo_factory, monkeypatch)
    assert lines_of(atlas(repo, "ref", "t", "--symbol", "Spec", *REFS)) == [
        "Справочник модуля t — символ Spec",
        "Spec — реэкспорт из .spec — pk/t/interfaces.py:4 — тестов 1, пример pk/t/tests/test_spec.py",
        "Кто использует (статика: импорты и вызовы по имени; getattr, реестры, patch по строке,"
        " методы объектов и каналы роутера не видны):",
        "Spec — вне модуля 2, тестов 1, файлов 1",
        "  pk/u/use.py:1  импорт",
        "  pk/u/use.py:5  вызов",
        "  тесты:",
        "    pk/t/tests/test_spec.py:1  импорт, тестов 1",
    ]


def test_builtin_and_stdlib_bases_are_known(
    repo_factory: RepoFactory, atlas: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = pk_repo(repo_factory, monkeypatch)
    lines = lines_of(atlas(repo, "ref", "t", *REFS))
    assert block(lines, "Level — ") == [
        "Level — Уровень — pk/t/interfaces.py:9 — тестов 0",
        "  вид: класс; базы: str, Enum; абстрактных 0 (своих 0)",
        "  реализации (0): нет",
    ]
    assert block(lines, "Boom — ") == [
        "Boom — Ошибка — pk/t/interfaces.py:13 — тестов 0",
        "  вид: класс; базы: RuntimeError; абстрактных 0 (своих 0)",
        "  реализации (0): нет",
    ]


def test_method_open_write_is_a_p4_record(
    repo_factory: RepoFactory, atlas: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = pk_repo(repo_factory, monkeypatch)
    res = atlas(repo, "--json", *REFS)
    assert res.code == 0, res.err
    p4 = sorted((f["detail"], f["source"]) for f in json.loads(res.out)["findings"] if f["code"] == "P4_DIRECT_WRITE")
    assert p4 == [("pk/t/io.py::dump", "pk/t/io.py:11")]
    card = lines_of(atlas(repo, "card", "t", *REFS))
    share = "  П4 записи файла в функции с атомарным вызовом (форма записи, не назначение файла): 1 из 2"
    assert share in card


# ---------------------------------------------------------------- пин (литералы reviewer'а)

_ROUTER = f"{_M}/router_module"


def _ref(atlas: Any, pinned: GitRepo, *argv: str) -> list[str]:  # noqa: F811
    res = atlas(pinned, "ref", *argv, *_PINNED)
    assert res.code == 0, res.err
    return res.out.splitlines()


def test_pin_abstract_counts_and_resolved_bases(pinned: GitRepo, atlas: Any) -> None:  # noqa: F811
    config = _ref(atlas, pinned, "config_module")
    assert "  вид: ABC; базы: ABC; абстрактных 9 (своих 9)" in block(config, "IConfig — ")
    router = _ref(atlas, pinned, "router_module")
    assert any(line.endswith("абстрактных 21 (своих 21)") for line in block(router, "IRouterManager — ")), block(
        router, "IRouterManager — "
    )
    assert "  вид: ABC; базы: IChannel; абстрактных 5 (своих 4)" in block(router, "IMessageChannel — ")
    console = _ref(atlas, pinned, "console_module")
    assert "  вид: ABC; базы: IBaseManager, ABC; абстрактных 19 (своих 10)" in block(console, "IConsoleManager — ")


@pytest.mark.slow
def test_pin_p1_findings_are_visible_in_ref_and_card(pinned: GitRepo, atlas: Any) -> None:  # noqa: F811
    res = atlas(pinned, "--json", *_PINNED)
    assert res.code == 0, res.err
    pairs = [
        (f["node"][len("module:") :], f["detail"], f["source"])
        for f in json.loads(res.out)["findings"]
        if f["code"] == "P1_IMPL_NOT_INHERITING"
    ]
    assert len(pairs) >= 26  # reviewer насчитал 26, по факту на пине 29 пар
    for module in sorted({m for m, _, _ in pairs}):
        lines = _ref(atlas, pinned, module)
        for _, detail, source in (p for p in pairs if p[0] == module):
            cls, _, iface = detail.partition(">")
            path, _, line = source.rpartition(":")
            row = f"    {cls} — структурно — {path}:{line}"
            if row in lines:
                at = lines.index(row)
                owner = next(x for x in reversed(lines[:at]) if x and not x.startswith(" "))
                assert owner.startswith(f"{iface} — "), (module, detail, owner)
                continue
            # пара могла не попасть в первые 8 строк (DESIGN п. 3): тогда у интерфейса «реализации (n>8)» и «… ещё k»
            shown = block(lines, f"{iface} — ")
            counts = [int(m.group(1)) for x in shown if (m := re.fullmatch(r"  реализации \((\d+)\):", x))]
            assert counts and counts[0] > 8 and any(x.startswith("    … ещё ") for x in shown), (module, detail)
    router = _ref(atlas, pinned, "router_module")
    assert f"    RouterManager — структурно — {_ROUTER}/core/router_manager.py:123" in router
    card = atlas(pinned, "card", "router_module", *_PINNED)
    assert card.code == 0, card.err
    assert "  П1 реализации с явным наследованием: 4 из 5" in card.out.splitlines()


def test_pin_reexport_builtin_bases_and_method_open(pinned: GitRepo, atlas: Any) -> None:  # noqa: F811
    tab = _ref(atlas, pinned, "frontend_module", "--symbol", "TabSpec")
    assert "  multiprocess_prototype/frontend/tab_factory.py:28  импорт" in tab
    assert "  multiprocess_prototype/frontend/tabs_registry.py:22  импорт" in tab
    assert not any(line.startswith("без использований вне модуля: TabSpec") for line in tab)
    service = _ref(atlas, pinned, "service_module", "--symbol", "ServiceLifecycle")
    assert "  вид: класс; базы: str, Enum; абстрактных 0 (своих 0)" in service
    card = atlas(pinned, "card", "app_module", *_PINNED)
    assert card.code == 0, card.err
    p4 = [x for x in card.out.splitlines() if x.startswith("  П4 ")]
    assert p4 and p4[0].endswith(": 1 из 1"), p4
    assert any("test_tab_registry.py:21  импорт" in line for line in tab), "тест-потребитель TabSpec не найден"
