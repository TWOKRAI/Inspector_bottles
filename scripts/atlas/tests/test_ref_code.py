"""Приёмочные тесты `ref`: вид, базы, абстрактные, реализации, «Код модуля», --symbol (Task 1.6c, блок A, RED).

Purpose: вывод `python -m scripts.atlas ref <module> [--symbol ИМЯ]` на временных репозиториях Ф1 (три модуля
    m, b, u), Ф4 (синтаксическая ошибка в одном файле) и на репозитории крышек (cap, wide): строка вида, базы,
    счёт абстрактных, унаследованные, реализации (явно, структурно, Qt), значимые dunder, раздел «Код модуля»,
    ревизия против рабочего дерева, `--symbol`, ошибки.
Public API: фабрики фикстур для соседних тестов (new_repo, modules_yaml, put, commit, f1_repo, f4_repo,
    caps_repo, lines_of, block, USAGE_HEADER); тесты test_*.
Stability: lite

Ожидаемые значения выведены ВРУЧНУЮ из текста фикстур по DESIGN п. 3-8 брифа plans/2026-10-04_atlas/tasks/1.6c.md
(номера строк — строки самих фикстур), а не вычислены кодом проекта. Даты коммитов фиксированы. Все вызовы git и
main() идут через дедлайн conftest.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from scripts.atlas.tests.conftest import GitRepo, RepoFactory

__all__ = [
    "USAGE_HEADER",
    "block",
    "caps_repo",
    "commit",
    "f1_repo",
    "f4_repo",
    "lines_of",
    "modules_yaml",
    "new_repo",
    "put",
]

REFS = ("--ref", "main", "--main-ref", "main")
USAGE_HEADER = (
    "Кто использует (статика: импорты и вызовы по имени; getattr, реестры, patch по строке,"
    " методы объектов и каналы роутера не видны):"
)
USAGE_UNKNOWN = "Кто использует: не определено (исходники не разбираются)"
CODE_PREFIX = "Код модуля (без tests/ и interfaces.py): "


# ---------------------------------------------------------------- общие хелперы


def new_repo(factory: RepoFactory, name: str) -> GitRepo:
    repo = factory.create(name)
    exclude = repo.path / ".git" / "info" / "exclude"
    exclude.parent.mkdir(parents=True, exist_ok=True)
    exclude.write_text("data/\n", encoding="utf-8")
    return repo


def modules_yaml(rows: list[tuple[str, str]]) -> str:
    """rows: (id, layer); paths = [id/], tier null, docs [], parent null."""
    text = "version: 1\nmodules:\n"
    for module_id, layer in rows:
        text += (
            f"  - id: {module_id}\n    paths: {json.dumps([module_id + '/'])}\n    layer: {layer}\n"
            "    tier: null\n    docs: []\n    parent: null\n"
        )
    return text


def put(repo: GitRepo, rel: str, text: str) -> None:
    """Файл с точными байтами (LF)."""
    target = repo.path / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(text.encode("utf-8"))


def commit(repo: GitRepo, mp: pytest.MonkeyPatch, day: str, subject: str) -> str:
    full = f"{day}T10:00:00+0000"
    mp.setenv("GIT_AUTHOR_DATE", full)
    mp.setenv("GIT_COMMITTER_DATE", full)
    return repo.commit(subject)


def lines_of(res: Any) -> list[str]:
    assert res.code == 0, res.err
    assert res.err == ""
    return res.out.splitlines()


def block(lines: list[str], header_prefix: str) -> list[str]:
    """Строка заголовка (без отступа, начинается с header_prefix) и следующие за ней строки с отступом."""
    start = next(i for i, line in enumerate(lines) if line.startswith(header_prefix))
    end = start + 1
    while end < len(lines) and lines[end].startswith(" "):
        end += 1
    return lines[start:end]


# ---------------------------------------------------------------- Ф1

B_INTERFACES = '''\
"""Интерфейсы b."""
from abc import ABC, abstractmethod

__all__ = ["IBase"]


class IBase(ABC):
    """База менеджеров."""

    @abstractmethod
    def base_op(self) -> None:
        """Базовая операция."""
'''

M_INTERFACES = '''\
"""Интерфейсы m."""
from abc import ABC, abstractmethod
from typing import Protocol, runtime_checkable

from b.interfaces import IBase

__all__ = ["IA", "IP", "IPlain", "Sized"]


class IA(IBase, ABC):
    """Контракт A."""

    @abstractmethod
    def alpha(self, x: int) -> int:
        """Альфа."""

    @abstractmethod
    def beta(self) -> str:
        """Бета."""

    def helper(self) -> None:
        """Не абстрактный."""

    def _hidden(self) -> None:
        """Скрыт."""

    def __repr__(self) -> str:
        """Не значимый dunder."""


@runtime_checkable
class IP(Protocol):
    """Вызываемый контракт."""

    def __call__(self, key: str) -> None:
        """Вызов."""


class IPlain:
    """Класс без баз."""

    def __init__(self, size: int = 1) -> None:
        """Конструктор."""

    def plain(self) -> None:
        """Обычный."""


class Sized:
    """Размер."""

    def __len__(self) -> int:
        """Длина."""
'''

M_IMPL = '''\
from PySide6.QtCore import QObject

from m.interfaces import IA


class Impl(IA):
    """Явная реализация."""

    def alpha(self, x: int) -> int:
        return x

    def beta(self) -> str:
        return ""

    def base_op(self) -> None:
        return None


class Duck:
    """Утка."""

    def alpha(self, x: int) -> int:
        return x

    def beta(self) -> str:
        return ""

    def base_op(self) -> None:
        return None


class Qt1(QObject):
    """Qt-реализация."""

    def alpha(self, x: int) -> int:
        return x

    def beta(self) -> str:
        return ""

    def base_op(self) -> None:
        return None


class Child(Qt1):
    """Наследник Qt."""


class One:
    """Один член."""

    def alpha(self, x: int) -> int:
        return x


class Solo:
    """Только вызов."""

    def __call__(self, key: str) -> None:
        return None


class _Internal:
    """Приватный."""
'''

M_MORE = '''\
from .impl import Impl


class Sub(Impl):
    """Подкласс."""
'''

M_HELPER = '''\
__all__ = ["pub"]


def pub(x: int = 1) -> int:
    """Публичная функция. Второе предложение."""
    return x


def hidden() -> None:
    """Не в __all__."""
'''

U_USE = """\
from m.tools.helper import (
    pub,
)


def run() -> int:
    return pub()
"""

U_TEST = '''\
from m import pub as p


def test_calls() -> None:
    assert p() == 1


def test_mentions() -> None:
    """Упоминание pub в docstring."""
    assert True
'''

M_TEST_X = """\
from m.interfaces import IA


class Fake:
    pass


def test_ia() -> None:
    assert IA is not None
"""

M_TEST_Z = """\
from m.interfaces import IA


def test_iz() -> None:
    assert IA is not None
"""

M_TEST_WORD = '''\
from m.interfaces import IP


def test_word() -> None:
    """Упоминание IP в docstring."""  # IP и в комментарии
    assert True
'''

M_TEST_Y = """\
class FakeY:
    pass


def test_y() -> None:
    pass
"""

F1_FILES: dict[str, str] = {
    "b/__init__.py": "",
    "b/interfaces.py": B_INTERFACES,
    "m/__init__.py": 'from .tools import pub\n\n__all__ = ["pub"]\n',
    "m/interfaces.py": M_INTERFACES,
    "m/core/__init__.py": "",
    "m/core/impl.py": M_IMPL,
    "m/core/more.py": M_MORE,
    "m/tools/__init__.py": 'from .helper import pub\n\n__all__ = ["pub"]\n',
    "m/tools/helper.py": M_HELPER,
    "m/tests/test_x.py": M_TEST_X,
    "m/tests/test_z.py": M_TEST_Z,
    "m/tests/test_word.py": M_TEST_WORD,
    "m/tools/tests/test_y.py": M_TEST_Y,
    "u/__init__.py": "",
    "u/use.py": U_USE,
}


def f1_repo(factory: RepoFactory, mp: pytest.MonkeyPatch, name: str = "f1") -> GitRepo:
    """Два коммита: init (без u/tests) и tests (добавляет u/tests/test_use.py)."""
    repo = new_repo(factory, name)
    repo.write("modules.yaml", modules_yaml([("m", "framework"), ("b", "framework"), ("u", "prototype")]))
    for rel, text in F1_FILES.items():
        put(repo, rel, text)
    commit(repo, mp, "2026-10-01", "init")
    put(repo, "u/tests/test_use.py", U_TEST)
    commit(repo, mp, "2026-10-02", "tests")
    return repo


IA_BLOCK = [
    "IA — Контракт A — m/interfaces.py:10 — тестов 2, пример m/tests/test_x.py",
    "  вид: ABC; базы: IBase, ABC; абстрактных 3 (своих 2)",
    "  alpha(x: int) -> int  :14",
    "    Альфа",
    "  beta() -> str  :18",
    "    Бета",
    "  helper() -> None  :21",
    "    Не абстрактный",
    "  унаследованные абстрактные от IBase (1): base_op",
    "  реализации (5):",
    "    Child — структурно (Qt) — m/core/impl.py:45",
    "    Duck — структурно — m/core/impl.py:19",
    "    Impl — явно — m/core/impl.py:6",
    "    Qt1 — структурно (Qt) — m/core/impl.py:32",
    "    Sub — явно — m/core/more.py:4",
]
IP_BLOCK = [
    "IP — Вызываемый контракт — m/interfaces.py:32 — тестов 0",
    "  вид: Protocol, runtime_checkable; базы: Protocol; абстрактных 1 (своих 1)",
    "  __call__(key: str) -> None  :35",
    "    Вызов",
    "  реализации (0): нет",
]
IPLAIN_BLOCK = [
    "IPlain — Класс без баз — m/interfaces.py:39 — тестов 0",
    "  вид: класс; базы: —; абстрактных 0 (своих 0)",
    "  __init__(size: int = 1) -> None  :42",
    "    Конструктор",
    "  plain() -> None  :45",
    "    Обычный",
    "  реализации (0): нет",
]
SIZED_BLOCK = [
    "Sized — Размер — m/interfaces.py:49 — тестов 0",
    "  вид: класс; базы: —; абстрактных 0 (своих 0)",
    "  __len__() -> int  :52",
    "    Длина",
    "  реализации (0): нет",
]


def test_ref_interface_blocks_kind_members_inherited_and_implementations(
    repo_factory: RepoFactory, atlas: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = f1_repo(repo_factory, monkeypatch)
    lines = lines_of(atlas(repo, "ref", "m", *REFS))
    assert lines[0] == "Справочник модуля m — m/interfaces.py, интерфейсов 4"
    assert block(lines, "IA — ") == IA_BLOCK
    assert block(lines, "IP — ") == IP_BLOCK
    assert block(lines, "IPlain — ") == IPLAIN_BLOCK
    assert block(lines, "Sized — ") == SIZED_BLOCK
    interface_headers = [line for line in lines[1:] if line and not line.startswith(" ")][:4]
    assert [h.split(" — ")[0] for h in interface_headers] == ["IA", "IP", "IPlain", "Sized"]


def test_ref_private_and_other_dunders_are_hidden(
    repo_factory: RepoFactory, atlas: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = f1_repo(repo_factory, monkeypatch)
    lines = lines_of(atlas(repo, "ref", "m", *REFS))
    joined = "\n".join(block(lines, "IA — "))
    assert "_hidden" not in joined
    assert "__repr__" not in joined
    assert "  __call__(key: str) -> None  :35" in lines
    assert "  __init__(size: int = 1) -> None  :42" in lines
    assert "  __len__() -> int  :52" in lines


def test_single_member_matches_are_not_implementations(
    repo_factory: RepoFactory, atlas: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = f1_repo(repo_factory, monkeypatch)
    lines = lines_of(atlas(repo, "ref", "m", *REFS))
    names = [row.strip().split(" — ")[0] for row in lines if row.startswith("    ") and " — " in row]
    assert "One" not in names, "One совпал с одним членом из трёх: не реализация"
    assert "Solo" not in names, "Solo совпал с единственным членом IP: порог >= 2"
    assert "  реализации (0): нет" in block(lines, "IP — ")


# ---------------------------------------------------------------- Ф1: «Код модуля»

_CODE_HEADER = CODE_PREFIX + "файлов 3, классов 7, функций 1"


def _code_section(lines: list[str]) -> list[str]:
    start = next(i for i, line in enumerate(lines) if line.startswith("Код модуля"))
    end = next(i for i, line in enumerate(lines) if i > start and line.startswith("Кто использует"))
    return lines[start:end]


def test_module_code_scope_header_counts_and_symbols(
    repo_factory: RepoFactory, atlas: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = f1_repo(repo_factory, monkeypatch)
    section = _code_section(lines_of(atlas(repo, "ref", "m", *REFS)))
    assert section[0] == _CODE_HEADER
    assert [line for line in section if not line.startswith(" ")] == [
        _CODE_HEADER,
        "m/core/impl.py",
        "m/core/more.py",
        "m/tools/helper.py",
    ]
    classes = [
        "  Impl(IA) — Явная реализация — :6",
        "  Duck — Утка — :19",
        "  Qt1(QObject) — Qt-реализация — :32",
        "  Child(Qt1) — Наследник Qt — :45",
        "  One — Один член — :49",
        "  Solo — Только вызов — :56",
    ]
    positions = [section.index(row) for row in classes]
    assert positions == sorted(positions), "классы файла идут в порядке исходника"
    for row in (
        "  Sub(Impl) — Подкласс — :4",
        "  pub(x: int = 1) -> int — Публичная функция — :4",
        "    alpha(x: int) -> int  :9",
        "    beta() -> str  :12",
        "    base_op() -> None  :15",
        "    __call__(key: str) -> None  :59",
    ):
        assert row in section, row
    text = "\n".join(section[1:])  # заголовок раздела сам содержит «interfaces.py»
    for absent in ("_Internal", "hidden", "Fake", "FakeY", "IA —", "IBase", "interfaces.py"):
        assert absent not in text, absent


def test_symbol_narrows_every_section_for_an_interface(
    repo_factory: RepoFactory, atlas: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = f1_repo(repo_factory, monkeypatch)
    assert lines_of(atlas(repo, "ref", "m", "--symbol", "IA", *REFS)) == [
        "Справочник модуля m — символ IA",
        *IA_BLOCK,
        USAGE_HEADER,
        "IA — вне модуля 0, тестов 2, файлов 0",
        "  тесты:",
        "    m/tests/test_x.py:1  импорт, тестов 1",
        "    m/tests/test_z.py:1  импорт, тестов 1",
    ]


def test_symbol_narrows_every_section_for_a_code_symbol(
    repo_factory: RepoFactory, atlas: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = f1_repo(repo_factory, monkeypatch)
    assert lines_of(atlas(repo, "ref", "m", "--symbol", "pub", *REFS)) == [
        "Справочник модуля m — символ pub",
        "m/tools/helper.py",
        "  pub(x: int = 1) -> int — Публичная функция — :4",
        USAGE_HEADER,
        "pub — вне модуля 2, тестов 1, файлов 1",
        "  u/use.py:2  импорт",
        "  u/use.py:7  вызов",
        "  тесты:",
        "    u/tests/test_use.py:1  импорт, тестов 1",
    ]
    unused = lines_of(atlas(repo, "ref", "m", "--symbol", "Duck", *REFS))
    assert unused[0] == "Справочник модуля m — символ Duck"
    assert unused[-1] == "без использований вне модуля: Duck"


def test_unknown_symbol_is_an_error(repo_factory: RepoFactory, atlas: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = f1_repo(repo_factory, monkeypatch)
    res = atlas(repo, "ref", "m", "--symbol", "NoSuchName", *REFS)
    assert (res.code, res.out, res.err) == (2, "", "atlas: symbol not found\n")


# ---------------------------------------------------------------- Ф1: ревизия, а не рабочее дерево


def test_output_follows_the_revision_not_the_working_tree(
    repo_factory: RepoFactory, atlas: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = f1_repo(repo_factory, monkeypatch)
    prev = ("--ref", "HEAD~1", "--main-ref", "main")
    head = ("--ref", "HEAD", "--main-ref", "main")
    before_prev = lines_of(atlas(repo, "ref", "m", "--symbol", "pub", *prev))
    before_head = lines_of(atlas(repo, "ref", "m", "--symbol", "pub", *head))
    assert before_prev != before_head
    assert "pub — вне модуля 2, тестов 0, файлов 1" in before_prev
    assert "  тесты:" not in before_prev
    assert "pub — вне модуля 2, тестов 1, файлов 1" in before_head
    assert "    u/tests/test_use.py:1  импорт, тестов 1" in before_head

    put(repo, "u/use.py", U_USE + "\n\nextra = pub()\n")  # правка рабочего дерева без коммита
    put(repo, "m/tools/helper.py", M_HELPER.replace("x: int = 1", "x: int = 2"))
    assert lines_of(atlas(repo, "ref", "m", "--symbol", "pub", *prev)) == before_prev
    assert lines_of(atlas(repo, "ref", "m", "--symbol", "pub", *head)) == before_head


# ---------------------------------------------------------------- Ф4: синтаксическая ошибка в одном файле

Z_INTERFACES = '''\
from nowhere_pkg import Thing

__all__ = ["IZ"]


class IZ(Thing):
    """Зет."""

    def go(self) -> None:
        """Идти."""
'''


Z_GOOD = '''\
def ok() -> int:
    """Хорошая."""
    return 1


def w(path):
    """Пишет."""
    open(path, "w")
'''


def f4_repo(factory: RepoFactory, mp: pytest.MonkeyPatch, name: str = "f4") -> GitRepo:
    repo = new_repo(factory, name)
    repo.write("modules.yaml", modules_yaml([("z", "framework")]))
    put(repo, "z/__init__.py", "")
    put(repo, "z/interfaces.py", Z_INTERFACES)
    put(repo, "z/good.py", Z_GOOD)
    put(repo, "z/bad.py", "def broken(:\n    pass\n")
    commit(repo, mp, "2026-10-01", "init")
    return repo


def test_unresolvable_base_gives_undefined_kind_and_syntax_error_is_skipped(
    repo_factory: RepoFactory, atlas: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = f4_repo(repo_factory, monkeypatch)
    res = atlas(repo, "ref", "z", *REFS)
    lines = lines_of(res)
    assert lines[0] == "Справочник модуля z — z/interfaces.py, интерфейсов 1"
    assert "  вид: не определён" in block(lines, "IZ — ")
    assert any(line.startswith("  вид: ") and "не определён" in line for line in lines)
    assert "z/bad.py" not in res.out, "файл с синтаксической ошибкой пропускается без пути в выводе"
    assert CODE_PREFIX + "файлов 1, классов 0, функций 2" in lines
    assert "z/good.py" in lines
    assert "  ok() -> int — Хорошая — :1" in lines


# ---------------------------------------------------------------- крышки: реализации, методы, раздел


def caps_repo(factory: RepoFactory, mp: pytest.MonkeyPatch, name: str = "caps") -> GitRepo:
    repo = new_repo(factory, name)
    repo.write("modules.yaml", modules_yaml([("cap", "framework"), ("wide", "framework")]))
    put(repo, "cap/__init__.py", "")
    put(
        repo,
        "cap/interfaces.py",
        'from abc import ABC, abstractmethod\n\n__all__ = ["ICap"]\n\n\nclass ICap(ABC):\n    """Капы."""\n\n'
        '    @abstractmethod\n    def go(self) -> None:\n        """Идти."""\n',
    )
    classes = [f"class C{i:02d}(ICap):\n    pass\n" for i in range(10, 0, -1)]  # C10 первым: порядок не исходный
    put(repo, "cap/impl.py", "from cap.interfaces import ICap\n\n\n" + "\n\n".join(classes))
    methods = [f"    def m{i:02d}(self) -> None:\n        pass\n" for i in range(1, 15)]
    put(repo, "cap/big.py", 'class Big:\n    """Большой."""\n\n' + "\n".join(methods))
    put(repo, "wide/__init__.py", "")
    for i in range(1, 81):
        put(repo, f"wide/f{i:02d}.py", f'def f{i:02d}() -> None:\n    """Функция {i:02d}."""\n')
    commit(repo, mp, "2026-10-01", "init")
    return repo


def test_implementations_cap_eight_total_order_and_rest(
    repo_factory: RepoFactory, atlas: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = caps_repo(repo_factory, monkeypatch)
    lines = lines_of(atlas(repo, "ref", "cap", *REFS))
    assert block(lines, "ICap — ") == [
        "ICap — Капы — cap/interfaces.py:6 — тестов 0",
        "  вид: ABC; базы: ABC; абстрактных 1 (своих 1)",
        "  go() -> None  :10",
        "    Идти",
        "  реализации (10):",
        "    C01 — явно — cap/impl.py:40",
        "    C02 — явно — cap/impl.py:36",
        "    C03 — явно — cap/impl.py:32",
        "    C04 — явно — cap/impl.py:28",
        "    C05 — явно — cap/impl.py:24",
        "    C06 — явно — cap/impl.py:20",
        "    C07 — явно — cap/impl.py:16",
        "    C08 — явно — cap/impl.py:12",
        "    … ещё 2",
    ]


def test_module_code_method_cap_is_twelve(
    repo_factory: RepoFactory, atlas: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = caps_repo(repo_factory, monkeypatch)
    section = _code_section(lines_of(atlas(repo, "ref", "cap", *REFS)))
    assert section[0] == CODE_PREFIX + "файлов 2, классов 11, функций 0"
    at = section.index("  Big — Большой — :1")
    sigs = [line for line in section[at + 1 :] if line.startswith("    ") and not line.startswith("     ")]
    assert sigs[:12] == [f"    m{i:02d}() -> None  :{4 + 3 * (i - 1)}" for i in range(1, 13)]
    assert sigs[12] == "    … ещё 2"
    assert not any("m13" in line or "m14" in line for line in section)


def test_module_code_section_is_capped_at_150_lines(
    repo_factory: RepoFactory, atlas: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = caps_repo(repo_factory, monkeypatch)
    lines = lines_of(atlas(repo, "ref", "wide", *REFS))
    assert lines[0] == "Справочник модуля wide — интерфейсов 0"
    section = _code_section(lines)
    assert section[0] == CODE_PREFIX + "файлов 80, классов 0, функций 80"
    assert section[1:3] == ["wide/f01.py", "  f01() -> None — Функция 01 — :1"]
    assert len(section) == 150, "в лимит входят строка заголовка раздела и строка «… ещё»"
    assert section[-1] == "… ещё 12 строк, сузить: ref wide --symbol ИМЯ"
