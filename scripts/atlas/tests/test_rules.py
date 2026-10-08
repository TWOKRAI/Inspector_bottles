"""Приёмочные тесты находок П1-П4 (ADR-175, адаптер `rules`) (Task 1.6c, блок A, RED до кода).

Purpose: находки на фикстуре Ф2 (слои framework/services/prototype): П1 (только структурные не-Qt реализации),
    П2 (нет docstring / Sphinx / NumPy; символы `interfaces.py` и `__all__` корня), П3 (нет `__all__`, висячее
    имя), П4 (запись без замены; атомарная функция не помечается), точный текст detail без номеров строк,
    охват (framework — находки; services/plugins — только доля; prototype — вне охвата), устойчивость ключа
    находки к сдвигу кода на строку (`check`), пин: число `P4_DIRECT_WRITE` = 18.
Public API: тесты test_*; публичных имён нет.
Stability: lite

Находки читаются через `--json` (code, severity, node, detail, source), `check` и `card`; внутренние функции
`rules` не импортируются. Ожидаемые значения выведены ВРУЧНУЮ из текста фикстуры Ф2 по DESIGN п. 9 брифа
plans/2026-10-04_atlas/tasks/1.6c.md. Номера строк source — строки самих фикстур.
"""

from __future__ import annotations

import json
import re
from typing import Any

import pytest

from scripts.atlas.tests.conftest import GitRepo, RepoFactory
from scripts.atlas.tests.test_exam_k0 import _PINNED, pin_db, pinned  # noqa: F401 - фикстуры пина
from scripts.atlas.tests.test_ref_code import (
    REFS,
    commit,
    f4_repo,
    lines_of,
    modules_yaml,
    new_repo,
    put,
)

__all__: list[str] = []

F_INIT = 'from .core import Thing\n\n__all__ = ["Thing", "Gone"]\n'
F_CORE = '''\
class Thing:
    """Вещь.

    Подробно.
    """

    def go(self) -> None:
        """Идти."""

    def silent(self) -> None:
        pass
'''
F_INTERFACES = '''\
"""Интерфейсы f."""
from abc import ABC, abstractmethod

__all__ = ["IGood", "IBad", "INoDoc"]


class IGood(ABC):
    """Хороший интерфейс."""

    @abstractmethod
    def run(self, x: int) -> int:
        """Выполнить.

        Args:
            x: вход.
        """

    @abstractmethod
    def stop(self) -> None:
        """Остановить."""


class IBad(ABC):
    """Плохой стиль.

    :param x: старый стиль.
    """

    @abstractmethod
    def sphinx(self, x: int) -> int:
        """Метод.

        :param x: вход
        :returns: результат
        """

    @abstractmethod
    def numpy(self) -> int:
        """Метод.

        Returns
        -------
        int
        """

    @abstractmethod
    def nodoc(self) -> None:
        pass


class INoDoc(ABC):
    def m(self) -> None:
        """Есть."""
'''
F_IMPLS = """\
from f.interfaces import IGood


class Explicit(IGood):
    def run(self, x: int) -> int:
        return x

    def stop(self) -> None:
        return None


class Structural:
    def run(self, x: int) -> int:
        return x

    def stop(self) -> None:
        return None


class Partial:
    def run(self, x: int) -> int:
        return x
"""
F_IO = """\
import os

open("boot.txt", "wb")


def write_plain(path):
    with open(path, "w") as fh:
        fh.write("x")


def write_atomic(path):
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        fh.write("x")
    os.replace(tmp, path)


def read_only(path):
    with open(path) as fh:
        return fh.read()


def outer():
    def inner(path):
        path.write_bytes(b"x")

    return inner


class Saver:
    def save(self, path):
        path.write_text("x")

    def save_atomic(self, path, tmp):
        tmp.write_bytes(b"x")
        tmp.replace(path)
"""
Q_INTERFACES = '''\
from abc import ABC, abstractmethod

__all__ = ["IQ"]


class IQ(ABC):
    """Q."""

    @abstractmethod
    def a(self) -> None:
        """A."""

    @abstractmethod
    def b(self) -> None:
        """B."""
'''
Q_IMPL = (
    "from PySide6.QtCore import QObject\n\n\nclass Q(QObject):\n    def a(self) -> None:\n        return None\n\n"
    "    def b(self) -> None:\n        return None\n"
)
S_INTERFACES = '''\
from abc import ABC, abstractmethod

__all__ = ["ISvc"]


class ISvc(ABC):
    """Сервис."""

    @abstractmethod
    def a(self) -> None:
        """A."""

    @abstractmethod
    def b(self) -> None:
        pass
'''
S_IMPL = "class Svc:\n    def a(self) -> None:\n        return None\n\n    def b(self) -> None:\n        return None\n"
IO_PLAIN = 'def write_plain(path):\n    with open(path, "w") as fh:\n        fh.write("x")\n'

F2_FILES: dict[str, str] = {
    "f/__init__.py": F_INIT,
    "f/core.py": F_CORE,
    "f/interfaces.py": F_INTERFACES,
    "f/impls.py": F_IMPLS,
    "f/io.py": F_IO,
    "f/sub/__init__.py": "from .x import Y\n",
    "f/sub/x.py": "class Y:\n    pass\n",
    "f/good/__init__.py": '__all__ = ["Z"]\n\n\nclass Z:\n    pass\n',
    "f/cond/__init__.py": 'try:\n    from .a import A\nexcept ImportError:\n    A = None\n\n__all__ = ["A"]\n',
    "f/cond/a.py": "class A:\n    pass\n",
    "f/lazy/__init__.py": '__all__ = ["Nope"]\n\n\ndef __getattr__(name):\n    raise AttributeError(name)\n',
    "f/tests/__init__.py": "from .test_w import W\n",
    "f/tests/test_w.py": 'class W:\n    pass\n\n\ndef test_w(tmp_path):\n    open(tmp_path / "a", "w")\n',
    "q/__init__.py": "",
    "q/interfaces.py": Q_INTERFACES,
    "q/impl.py": Q_IMPL,
    "s/__init__.py": "",
    "s/interfaces.py": S_INTERFACES,
    "s/impl.py": S_IMPL,
    "s/io.py": IO_PLAIN,
    "p/__init__.py": "",
    "p/interfaces.py": '__all__ = ["IP"]\n\n\nclass IP:\n    pass\n',
    "p/io.py": IO_PLAIN,
}
F2_ROWS = [("f", "framework"), ("q", "framework"), ("s", "services"), ("p", "prototype")]


def f2_repo(factory: RepoFactory, mp: pytest.MonkeyPatch, name: str = "f2") -> GitRepo:
    repo = new_repo(factory, name)
    repo.write("modules.yaml", modules_yaml(F2_ROWS))
    for rel, text in F2_FILES.items():
        put(repo, rel, text)
    commit(repo, mp, "2026-10-01", "init")
    return repo


def _p_findings(atlas: Any, repo: GitRepo, refs: tuple[str, ...] = REFS) -> list[tuple[str, str, str, str, str]]:
    res = atlas(repo, "--json", *refs)
    assert res.code == 0, res.err
    rows = [
        (f["code"], f["severity"], f["node"], f["detail"], f["source"])
        for f in json.loads(res.out)["findings"]
        if re.match(r"P[1-4]_", f["code"])
    ]
    return sorted(rows)


F_EXPECTED = [
    ("P1_IMPL_NOT_INHERITING", "warning", "module:f", "Structural>IGood", "f/impls.py:12"),
    ("P2_DOCSTRING", "warning", "module:f", "IBad", "f/interfaces.py:23"),
    ("P2_DOCSTRING", "warning", "module:f", "IBad.nodoc", "f/interfaces.py:47"),
    ("P2_DOCSTRING", "warning", "module:f", "IBad.numpy", "f/interfaces.py:38"),
    ("P2_DOCSTRING", "warning", "module:f", "IBad.sphinx", "f/interfaces.py:30"),
    ("P2_DOCSTRING", "warning", "module:f", "INoDoc", "f/interfaces.py:51"),
    ("P2_DOCSTRING", "warning", "module:f", "Thing.silent", "f/core.py:10"),
    ("P3_NO_ALL", "warning", "module:f", "f/__init__.py", "f/__init__.py:1"),
    ("P3_NO_ALL", "warning", "module:f", "f/sub/__init__.py", "f/sub/__init__.py:1"),
    ("P4_DIRECT_WRITE", "warning", "module:f", "f/io.py::<module>", "f/io.py:3"),
    ("P4_DIRECT_WRITE", "warning", "module:f", "f/io.py::Saver.save", "f/io.py:32"),
    ("P4_DIRECT_WRITE", "warning", "module:f", "f/io.py::outer", "f/io.py:25"),
    ("P4_DIRECT_WRITE", "warning", "module:f", "f/io.py::write_plain", "f/io.py:7"),
]


def test_findings_p1_p4_on_the_framework_layer_are_exact(
    repo_factory: RepoFactory, atlas: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = f2_repo(repo_factory, monkeypatch)
    assert _p_findings(atlas, repo) == F_EXPECTED


def test_detail_has_no_line_numbers(repo_factory: RepoFactory, atlas: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = f2_repo(repo_factory, monkeypatch)
    rows = _p_findings(atlas, repo)
    assert len(rows) == len(F_EXPECTED)
    for code, _severity, _node, detail, _source in rows:
        assert not re.search(r":\d+", detail), (code, detail)


def test_qt_structural_implementation_is_not_a_p1_finding(
    repo_factory: RepoFactory, atlas: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = f2_repo(repo_factory, monkeypatch)
    rows = _p_findings(atlas, repo)
    assert ("P1_IMPL_NOT_INHERITING", "warning", "module:f", "Structural>IGood", "f/impls.py:12") in rows
    assert [row for row in rows if row[2] == "module:q"] == []


def test_services_and_prototype_get_no_findings(
    repo_factory: RepoFactory, atlas: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = f2_repo(repo_factory, monkeypatch)
    nodes = {row[2] for row in _p_findings(atlas, repo)}
    assert nodes == {"module:f"}, "находки П1-П4 — только слой framework"
    # доля у services есть (запись, структурная реализация и пустой docstring в s), находок нет
    card = lines_of(atlas(repo, "card", "s", *REFS))
    assert not any(" P1_" in line or " P2_" in line or " P3_" in line or " P4_" in line for line in card)
    assert "Правила ADR-175 (рекомендация; находки не поднимаются):" in card
    assert "Правила ADR-175: вне охвата (слой prototype)" in lines_of(atlas(repo, "card", "p", *REFS))


# ---------------------------------------------------------------- устойчивость ключа находки к сдвигу кода

_P_LINE = re.compile(r"^(blocking|warning|info) P[1-4]_")


def _p_lines(out: str) -> list[str]:
    return [line for line in out.splitlines() if _P_LINE.match(line)]


def test_code_shift_keeps_the_key_and_check_shows_nothing_new(
    repo_factory: RepoFactory, atlas: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = f2_repo(repo_factory, monkeypatch)
    repo.git("checkout", "-q", "-b", "feat")
    put(repo, "f/io.py", "# сдвиг на одну строку\n" + F_IO)
    put(repo, "f/impls.py", "# сдвиг на одну строку\n" + F_IMPLS)
    commit(repo, monkeypatch, "2026-10-02", "shift")
    shifted = _p_findings(atlas, repo, ("--ref", "HEAD", "--main-ref", "main"))  # сдвиг закоммичен в ветке feat
    assert [(c, n, d) for c, _s, n, d, _src in shifted] == [(c, n, d) for c, _s, n, d, _src in F_EXPECTED]
    assert ("P4_DIRECT_WRITE", "warning", "module:f", "f/io.py::write_plain", "f/io.py:8") in shifted
    res = atlas(repo, "check")
    assert _p_lines(res.out) == [], res.out

    put(repo, "f/io.py", "# сдвиг на одну строку\n" + F_IO + '\n\ndef fresh(path):\n    path.write_text("y")\n')
    commit(repo, monkeypatch, "2026-10-03", "fresh write")
    res = atlas(repo, "check")
    assert _p_lines(res.out) == ["warning P4_DIRECT_WRITE module:f f/io.py::fresh"], res.out


# ---------------------------------------------------------------- Ф4 и пин


def test_syntax_error_file_is_skipped_by_the_rules(
    repo_factory: RepoFactory, atlas: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = f4_repo(repo_factory, monkeypatch)
    res = atlas(repo, "--json", *REFS)
    assert res.code == 0, res.err
    assert "Traceback" not in res.err
    # хороший файл разобран (запись без замены найдена), файл с синтаксической ошибкой пропущен
    assert _p_findings(atlas, repo) == [
        ("P4_DIRECT_WRITE", "warning", "module:z", "z/good.py::w", "z/good.py:8"),
    ]


def test_p4_direct_write_count_on_the_pin(pinned: GitRepo, atlas: Any) -> None:  # noqa: F811
    res = atlas(pinned, "--json", *_PINNED)
    assert res.code == 0, res.err
    rows = [f for f in json.loads(res.out)["findings"] if f["code"] == "P4_DIRECT_WRITE"]
    assert len(rows) == 18
    assert {f["severity"] for f in rows} == {"warning"}
    assert all(f["node"].startswith("module:") for f in rows)
