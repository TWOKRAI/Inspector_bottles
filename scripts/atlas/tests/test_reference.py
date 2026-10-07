"""Приёмочные тесты видов `ref` и `index` и поля `purpose` (Task 1.6b, RED до кода).

Purpose: вывод `python -m scripts.atlas ref | index | card` на временных репозиториях (рецепты Ф1-Ф5 брифа):
    сигнатуры, типы, первые фразы, Pre/Post, тесты интерфейса, индекс проекта, `--write`/`--check`, назначение
    только из `purpose`, формы CLI, ленивая сборка, стабильность вывода под разными PYTHONHASHSEED.
Public API: тесты test_*; публичных имён нет.
Stability: lite

Ожидаемые значения — литералы из раздела «Эталонные выводы» брифа plans/2026-10-04_atlas/tasks/1.6b.md. Весь stdout
сравнивается списком строк (`splitlines()`), stderr — строкой с `\\n` в конце, файл INDEX.md — байтами. Ссылки заданы
явно (`--ref main --main-ref main`). Все вызовы git, subprocess и main() идут через дедлайн conftest.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from scripts.atlas.tests.conftest import GitRepo, RepoFactory, run_with_deadline

__all__: list[str] = []

_REFS = ("--ref", "main", "--main-ref", "main")
_ROOT = Path(__file__).resolve().parents[3]
_LAYERS = {"m": "framework"}
_HEADER = "# Индекс проекта — собран командой `python -m scripts.atlas index --write`, руками не править"
_STALE_ERR = "atlas index: INDEX.md отстал — запусти atlas index --write\n"


# ---------------------------------------------------------------- хелперы (копии из test_views.py)


def _new_repo(factory: RepoFactory, name: str) -> GitRepo:
    repo = factory.create(name)
    exclude = repo.path / ".git" / "info" / "exclude"
    exclude.parent.mkdir(parents=True, exist_ok=True)
    exclude.write_text("data/\n", encoding="utf-8")
    return repo


def _modules(rows: list[tuple[Any, ...]]) -> str:
    """rows: (id, paths, tier или None, docs[, purpose]); purpose пишется JSON-значением (строка или число)."""
    text = "version: 1\nmodules:\n"
    for row in rows:
        module_id, paths, tier, docs = row[:4]
        layer = _LAYERS.get(module_id, "scripts")
        text += (
            f"  - id: {module_id}\n    paths: {json.dumps(paths)}\n    layer: {layer}\n"
            f"    tier: {tier or 'null'}\n    docs: {json.dumps(docs)}\n    parent: null\n"
        )
        if len(row) > 4:
            text += f"    purpose: {json.dumps(row[4], ensure_ascii=False)}\n"
    return text


def _env(mp: pytest.MonkeyPatch, stamp: str) -> None:
    full = stamp if "T" in stamp else f"{stamp}T10:00:00+0000"
    mp.setenv("GIT_AUTHOR_DATE", full)
    mp.setenv("GIT_COMMITTER_DATE", full)


def _commit(repo: GitRepo, mp: pytest.MonkeyPatch, stamp: str, subject: str) -> str:
    _env(mp, stamp)
    return repo.commit(subject)


def _put(repo: GitRepo, rel: str, text: str) -> None:
    """Файл с точными байтами (LF), без перевода строк платформы."""
    target = repo.path / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(text.encode("utf-8"))


def _lines(res: Any) -> list[str]:
    assert res.code == 0, res.err
    assert res.err == ""
    return res.out.splitlines()


def _builds_count(repo: GitRepo) -> int:
    db = repo.path / "data" / "atlas.sqlite"
    if not db.exists():
        return 0
    con = sqlite3.connect(db)
    try:
        return int(con.execute("SELECT COUNT(*) FROM builds").fetchone()[0])
    except sqlite3.OperationalError:  # таблицы нет — сборок нет
        return 0
    finally:
        con.close()


# ---------------------------------------------------------------- Ф1: файлы и литерал `ref m`

_M_INTERFACES = '''\
"""Интерфейсы m."""
from typing import Any, Dict, List, Optional, Union

from .core import Impl

__all__ = ["Beta", "Alpha", "Impl", "make", "LIMIT", "Quiet"]


class Alpha:
    """Контракт альфа. Второе предложение не показывается.

    Подробности тоже.
    """

    @property
    def name(self) -> str:
        """Имя альфа."""

    def send(
        self,
        message: Union["Msg", Dict[str, Any]],
        priority: str = "normal",
        *,
        retry: Optional[int] = None,
    ) -> Optional["Msg"]:
        """Отправить сообщение. Блокирует вызов.

        Pre:
          - message не пустое.
        Post:
          - результат None при отказе.
        """

    async def fetch(self, *keys: str, **opts: Any) -> List[str]:
        """Прочитать ключи (через
        кэш) и вернуть значения. Хвост."""

    @classmethod
    def build(cls, size: int = 3) -> "Alpha":
        """Собрать альфу без точки"""

    def bare(self, x, y=2):
        pass

    def checked(self) -> bool:
        """Проверить.

        Post: всегда True.
        """

    def _hidden(self) -> None:
        """Скрыт."""


class Beta:
    def only(self) -> None:
        """Один."""


class Quiet:
    """Тихий интерфейс."""


def make(size: int = 1) -> "Alpha":
    """Фабрика. Ещё."""


LIMIT = 5
'''

_F1_REF_M = [
    "Справочник модуля m — m/interfaces.py, интерфейсов 6",
    "Alpha — Контракт альфа — m/interfaces.py:9 — тестов 4, пример m/tests/test_b.py",
    "  name -> str  :16",
    "    Имя альфа",
    "  send(message: Msg | Dict[str, Any], priority: str = 'normal', *, retry: int | None = None) -> Msg | None  :19",
    "    Отправить сообщение",
    "    Pre: message не пустое. / Post: результат None при отказе.",
    "  async fetch(*keys: str, **opts: Any) -> List[str]  :34",
    "    Прочитать ключи (через кэш) и вернуть значения",
    "  build(size: int = 3) -> Alpha  :39",
    "    Собрать альфу без точки",
    "  bare(x, y=2)  :42",
    "    нет описания",
    "  checked() -> bool  :45",
    "    Проверить",
    "    Post: всегда True.",
    "Beta — нет описания — m/interfaces.py:55 — тестов 0",
    "  only() -> None  :56",
    "    Один",
    "Impl — реэкспорт из .core — m/interfaces.py:4 — тестов 0",
    "LIMIT — нет описания — m/interfaces.py:68 — тестов 0",
    "Quiet — Тихий интерфейс — m/interfaces.py:60 — тестов 1, пример n/tests/test_n.py",
    "make(size: int = 1) -> Alpha — Фабрика — m/interfaces.py:64 — тестов 0",
]


def _f1_files(repo: GitRepo) -> None:
    _put(repo, "m/interfaces.py", _M_INTERFACES)
    _put(
        repo,
        "m/tests/test_m.py",
        "from m.interfaces import Alpha\n\n\ndef test_a1():\n    Alpha()\n\n\ndef test_a2():\n    Alpha()\n\n\n"
        "class TestMore:\n    def test_a3(self):\n        Alpha()\n",
    )
    _put(repo, "m/tests/test_b.py", "# Alpha\nBetaX = 1\n\n\ndef test_b1():\n    pass\n")
    _put(repo, "n/tests/test_n.py", "from m.interfaces import Quiet\n\n\ndef test_q():\n    Quiet\n")


def _f1_repo(factory: RepoFactory, mp: pytest.MonkeyPatch, name: str = "f1") -> GitRepo:
    repo = _new_repo(factory, name)
    repo.write("modules.yaml", _modules([("m", ["m/"], "core", []), ("n", ["n/"], None, [])]))
    _f1_files(repo)
    _commit(repo, mp, "2026-10-01", "init")
    return repo


def test_ref_signatures_types_docs_and_tests(
    repo_factory: RepoFactory, atlas: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _f1_repo(repo_factory, monkeypatch)
    first = _lines(atlas(repo, "ref", "m", *_REFS))
    assert first == _F1_REF_M
    assert _lines(atlas(repo, "ref", "m", *_REFS)) == first


# ---------------------------------------------------------------- Ф2: крайние случаи ref

_F2_REF_R = [
    "Справочник модуля r — r/interfaces.py, интерфейсов 5",
    "Engine — реэкспорт из .core.base — r/interfaces.py:1 — тестов 0",
    "Ghost — нет описания — r/interfaces.py:5 — тестов 0",
    "Worker — реэкспорт из .core.base — r/interfaces.py:1 — тестов 0",
    "helpers — реэкспорт из . — r/interfaces.py:2 — тестов 0",
    "osp — нет описания — r/interfaces.py:3 — тестов 0",
]
_F2_REF_AB = [
    "Справочник модуля a_b — a_b/interfaces.py, интерфейсов 1",
    "P — Пэ — a_b/interfaces.py:4 — тестов 0",
    "  go() -> None  :7",
    "    Идти",
]
_F2_REF_AXB = [
    "Справочник модуля axb — axb/interfaces.py, интерфейсов 1",
    "Q — нет описания — axb/interfaces.py:4 — тестов 0",
    "  stop() -> None  :5",
    "    нет описания",
]


def test_ref_edges_reexport_function_assign_and_empty(
    repo_factory: RepoFactory, atlas: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _new_repo(repo_factory, "f2")
    repo.write(
        "modules.yaml",
        _modules([(i, [f"{i}/"], None, []) for i in ("r", "idle", "a_b", "axb")]),
    )
    _put(
        repo,
        "r/interfaces.py",
        'from .core.base import Engine, Tool as Worker\nfrom . import helpers\nimport os.path as osp\n\n'
        '__all__ = ["Engine", "Worker", "helpers", "osp", "Ghost"]\n',
    )
    _put(repo, "idle/x.py", "x = 1\n")
    _put(
        repo,
        "a_b/interfaces.py",
        '__all__ = ["P"]\n\n\nclass P:\n    """Пэ."""\n\n    def go(self) -> None:\n        """Идти."""\n',
    )
    _put(repo, "axb/interfaces.py", '__all__ = ["Q"]\n\n\nclass Q:\n    def stop(self) -> None:\n        pass\n')
    _commit(repo, monkeypatch, "2026-10-01", "init")
    assert _lines(atlas(repo, "ref", "r", *_REFS)) == _F2_REF_R
    assert _lines(atlas(repo, "ref", "idle", *_REFS)) == ["Справочник модуля idle — интерфейсов нет"]
    assert _lines(atlas(repo, "ref", "a_b", *_REFS)) == _F2_REF_AB
    assert _lines(atlas(repo, "ref", "axb", *_REFS)) == _F2_REF_AXB


# ---------------------------------------------------------------- Ф3: index

_ZETA_COUNTS = {"B1": 3, "A2": 3, "C": 5, "D": 0, "E": 1, "F": 2, "G": 4}
_F3_ROWS: list[tuple[Any, ...]] = [
    ("zeta", ["zeta/"], None, [], "Зета делает зетовое дело"),
    ("alpha", ["alpha/"], None, ["alpha/README.md"]),
    ("mid", ["mid/"], None, [], "Середина с пустым интерфейсом"),
    ("omega", ["omega/"], None, [], "Омега"),
]
_F3_INDEX = [
    _HEADER,
    "zeta — Зета делает зетовое дело",
    "  C (5), G (4), A2 (3), B1 (3), F (2), … ещё 2",
    "alpha — нет purpose в modules.yaml",
    "  X (2)",
    "mid — Середина с пустым интерфейсом",
    "  Z (0)",
    "omega — Омега",
    "  Q, S",
]


def _f3_files(repo: GitRepo) -> None:
    classes = ""
    for name, count in _ZETA_COUNTS.items():
        body = "".join(f"    def m{k}(self) -> None:\n        pass\n\n" for k in range(count)) or "    pass\n"
        classes += f"\n\nclass {name}:\n{body}"
    _put(repo, "zeta/interfaces.py", '__all__ = ["B1", "A2", "C", "D", "E", "F", "G"]\n' + classes)
    _put(repo, "alpha/README.md", "Описание из README, которое не используется.\n")
    _put(
        repo,
        "alpha/interfaces.py",
        '__all__ = ["X"]\n\n\nclass X:\n    def a(self) -> None:\n        pass\n\n'
        "    def b(self) -> None:\n        pass\n\n    def _p(self) -> None:\n        pass\n",
    )
    _put(repo, "mid/interfaces.py", '__all__ = ["Z"]\n\n\nclass Z:\n    pass\n')
    _put(repo, "omega/interfaces.py", 'from .a import S, Q\n\n__all__ = ["S", "Q"]\n')


def _f3_repo(factory: RepoFactory, mp: pytest.MonkeyPatch, name: str = "f3") -> GitRepo:
    repo = _new_repo(factory, name)
    repo.write("modules.yaml", _modules(_F3_ROWS))
    _f3_files(repo)
    _commit(repo, mp, "2026-10-01", "init")
    return repo


def _file_bytes(lines: list[str]) -> bytes:
    return ("\n".join(lines) + "\n").encode("utf-8")


def test_index_shape_order_ranking_and_write_flag(
    repo_factory: RepoFactory, atlas: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _f3_repo(repo_factory, monkeypatch)
    assert _lines(atlas(repo, "index", *_REFS)) == _F3_INDEX
    target = repo.path / "docs" / "atlas" / "INDEX.md"
    assert not target.exists()

    sub = repo.path / "zeta"
    assert sub.is_dir()
    res = atlas(repo, "index", "--write", *_REFS, cwd=sub)
    assert _lines(res) == ["atlas index: docs/atlas/INDEX.md, 9 строк"]
    assert not (sub / "docs").exists(), "файл пишется от корня репозитория, а не от cwd"
    assert target.read_bytes() == _file_bytes(_F3_INDEX)
    assert b"\r" not in target.read_bytes()

    again = atlas(repo, "index", "--write", *_REFS, cwd=sub)
    assert _lines(again) == ["atlas index: docs/atlas/INDEX.md, 9 строк"]
    assert target.read_bytes() == _file_bytes(_F3_INDEX)


# ---------------------------------------------------------------- Ф4: purpose в card и index

_P_PURPOSE = "я" * 120
_F4_ROWS: list[tuple[Any, ...]] = [
    ("p1", ["p1/"], None, [], "Один"),
    ("p2", ["p2/"], None, [], _P_PURPOSE),
    ("p3", ["p3/"], None, ["p3/README.md"]),
    ("p4", ["p4/"], None, [], ""),
    ("p5", ["p5/"], None, [], "**жирный** и `код`."),
    ("p6", ["p6/"], None, [], 5),
]
_F4_INDEX = [
    _HEADER,
    "p1 — Один",
    f"p2 — {_P_PURPOSE}",
    "p3 — нет purpose в modules.yaml",
    "p4 — нет purpose в modules.yaml",
    "p5 — **жирный** и `код`.",
    "p6 — нет purpose в modules.yaml",
]


def test_purpose_comes_only_from_modules_yaml(
    repo_factory: RepoFactory, atlas: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _new_repo(repo_factory, "f4")
    repo.write("modules.yaml", _modules(_F4_ROWS))
    _put(repo, "p3/README.md", "Из README, не используется.\n")
    _commit(repo, monkeypatch, "2026-10-01", "init")
    assert _lines(atlas(repo, "index", *_REFS)) == _F4_INDEX  # index — ПЕРВЫЙ вызов на свежей базе
    assert "Назначение: Один" in _lines(atlas(repo, "card", "p1", *_REFS))
    card3 = _lines(atlas(repo, "card", "p3", *_REFS))
    assert "Назначение: нет purpose в modules.yaml" in card3
    assert not any("Из README" in line for line in card3)
    assert "Назначение: **жирный** и `код`." in _lines(atlas(repo, "card", "p5", *_REFS))


# ---------------------------------------------------------------- формы, ошибки, ленивая сборка


def test_ref_index_forms_errors_and_lazy_build(
    repo_factory: RepoFactory, atlas: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _f1_repo(repo_factory, monkeypatch)
    db = repo.path / "data" / "atlas.sqlite"
    assert _builds_count(repo) == 0
    assert atlas(repo, "ref", "m", *_REFS).code == 0
    assert _builds_count(repo) == 1
    before = db.read_bytes()
    assert atlas(repo, "ref", "m", *_REFS).code == 0
    assert db.read_bytes() == before, "второй ref не должен менять базу"

    res = atlas(repo, "ref", "nosuch", *_REFS)
    assert (res.code, res.out, res.err) == (2, "", "atlas: module not found\n")

    assert atlas(repo, "--json", "ref", "m", *_REFS).code == 2
    assert atlas(repo, "--json", "index", *_REFS).code == 2
    assert atlas(repo, "ref", *_REFS).code == 2
    assert atlas(repo, "ref", "m", "--write", *_REFS).code == 2
    assert atlas(repo, "ref", "m", "--check", *_REFS).code == 2

    repo3 = _f3_repo(repo_factory, monkeypatch, "f3_lazy")
    assert _builds_count(repo3) == 0
    assert atlas(repo3, "index", *_REFS).code == 0
    assert _builds_count(repo3) == 1


# ---------------------------------------------------------------- index --write / --check


def test_index_write_and_check_on_scratch_repo(
    repo_factory: RepoFactory, atlas: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _f3_repo(repo_factory, monkeypatch, "f3_check")
    target = repo.path / "docs" / "atlas" / "INDEX.md"
    fresh = _file_bytes(_F3_INDEX)

    res = atlas(repo, "index", "--check", *_REFS)
    assert (res.code, res.out, res.err) == (1, "", _STALE_ERR)
    assert not target.exists(), "--check не создаёт файл"

    assert _lines(atlas(repo, "index", "--write", *_REFS)) == ["atlas index: docs/atlas/INDEX.md, 9 строк"]
    assert target.read_bytes() == fresh

    res = atlas(repo, "index", "--check", *_REFS)
    assert _lines(res) == ["atlas index: docs/atlas/INDEX.md свежий, 9 строк"]
    assert target.read_bytes() == fresh, "--check не пишет файл"

    stale = fresh + "лишняя строка\n".encode("utf-8")
    target.write_bytes(stale)
    res = atlas(repo, "index", "--check", *_REFS)
    assert (res.code, res.out, res.err) == (1, "", _STALE_ERR)
    assert target.read_bytes() == stale, "--check никогда не пишет"

    assert _lines(atlas(repo, "index", "--write", *_REFS)) == ["atlas index: docs/atlas/INDEX.md, 9 строк"]
    assert target.read_bytes() == fresh
    assert atlas(repo, "index", "--check", *_REFS).code == 0

    changed = [(*row[:4], "Другое назначение середины") if row[0] == "mid" else row for row in _F3_ROWS]
    repo.write("modules.yaml", _modules(changed))
    _commit(repo, monkeypatch, "2026-10-02", "purpose mid")
    res = atlas(repo, "index", "--check", *_REFS)
    assert (res.code, res.out, res.err) == (1, "", _STALE_ERR), "вход индекса изменился — файл отстал"
    assert _lines(atlas(repo, "index", "--write", *_REFS)) == ["atlas index: docs/atlas/INDEX.md, 9 строк"]
    updated = [line.replace("Середина с пустым интерфейсом", "Другое назначение середины") for line in _F3_INDEX]
    assert target.read_bytes() == _file_bytes(updated)
    assert atlas(repo, "index", "--check", *_REFS).code == 0

    assert atlas(repo, "index", "--write", "--check", *_REFS).code == 2


# ---------------------------------------------------------------- стабильность под PYTHONHASHSEED

_F5_INDEX = [
    _HEADER,
    "m — нет purpose в modules.yaml",
    "  Alpha (6), Beta (1), Impl, LIMIT, Quiet (0), … ещё 1",
    "n — нет purpose в modules.yaml",
    *_F3_INDEX[1:],
]


def _run_cli(repo: GitRepo, seed: str, *argv: str) -> list[str]:
    env = {**os.environ, "PYTHONHASHSEED": seed, "PYTHONPATH": str(_ROOT), "PYTHONUTF8": "1"}
    proc = run_with_deadline(
        lambda: subprocess.run(
            [sys.executable, "-m", "scripts.atlas", *argv],
            cwd=repo.path,
            env=env,
            capture_output=True,
            check=False,
        )
    )
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
    assert proc.stderr == b""
    return proc.stdout.decode("utf-8").splitlines()


def test_ref_index_output_is_stable_under_hash_seeds(
    repo_factory: RepoFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _new_repo(repo_factory, "seeds")
    repo.write(
        "modules.yaml",
        _modules([("m", ["m/"], None, []), ("n", ["n/"], None, []), *_F3_ROWS]),
    )
    _f1_files(repo)
    _f3_files(repo)
    _commit(repo, monkeypatch, "2026-10-01", "init")
    got: dict[str, tuple[list[str], list[str]]] = {}
    for seed in ("0", "1", "2", "3", "4"):
        shutil.rmtree(repo.path / "data", ignore_errors=True)  # каждый процесс — на свежей базе
        ref_m = _run_cli(repo, seed, "ref", "m", *_REFS)  # ref — ПЕРВЫЙ вызов
        index = _run_cli(repo, seed, "index", *_REFS)
        got[seed] = (ref_m, index)
    assert got == {seed: (_F1_REF_M, _F5_INDEX) for seed in got}
