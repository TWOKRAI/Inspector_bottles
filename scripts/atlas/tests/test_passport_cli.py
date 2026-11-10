"""Слепые приёмочные тесты CLI `ref <id>… --format` (Task 4.2a, stage 2, RED до кода): REDS 9-10.

Purpose: несколько id за один вызов (порядок, `not found`, `ambiguous`, коды выхода, ввод без `--format`) и запуск
    путём `python <repo>/scripts/atlas ref … --root … --exclude …` из каталога вне git. Контракт — докстринги
    `scripts/atlas/__main__.py` и `scripts/atlas/passport.py`; флаги парсер уже знает, красные идут от заглушек
    `passport` (NotImplementedError -> код 2 с `internal error`) и от запуска путём (нет кодового корня в `sys.path`).
Public API: тесты test_*; публичных имён нет.
Stability: lite

Фикстуры — мини-репозитории git (`repo` из conftest). Подпроцессы идут с `timeout`, без `PYTHONPATH` (запуск путём
должен находить кодовый корень сам). Ожидаемые значения — литералы.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from scripts.atlas.tests.conftest import GitRepo
from scripts.atlas.tests.test_links import _at

__all__: list[str] = []

_CODE_ROOT = Path(__file__).resolve().parents[3]
TIMEOUT_S = 120

_FILES = {
    "pkg/__init__.py": "",
    "pkg/m.py": '''\
class A:
    """Класс А."""


def run():
    return 1


def dup():
    return 2


class B:
    pass
''',
    "pkg/n.py": '''\
def dup():
    return 3


class Beta:
    """Бета."""
''',
}


def _seed(repo: GitRepo) -> None:
    for rel, text in _FILES.items():
        repo.write(rel, text)
    repo.commit("fixture")


def test_ref_many_ids_one_call(repo: GitRepo, atlas: Any) -> None:
    """Несколько id подряд: порядок как дан; голое имя -> полный id; `not found`, `ambiguous` + `candidates`; ошибочный
    id -> `atlas ref: id <номер>: <error>` в stderr, код 2, остальные паспорта печатаются; без `--format` больше
    одного id -> код 2; `--symbol` с `--format` -> код 2."""
    _seed(repo)

    ok = atlas(repo, "ref", "pkg/m.py::A", "pkg/m.py::run", "--format", "json")
    assert ok.code == 0, ok.err
    assert [r["id"] for r in json.loads(ok.out)] == ["pkg/m.py::A", "pkg/m.py::run"]
    back = atlas(repo, "ref", "pkg/m.py::run", "pkg/m.py::A", "--format", "json")
    assert back.code == 0, back.err
    assert [r["id"] for r in json.loads(back.out)] == ["pkg/m.py::run", "pkg/m.py::A"]  # порядок id, не пути

    mixed = atlas(repo, "ref", "pkg/m.py::A", "Beta", "missing", "dup", "pkg/m.py::run", "--format", "json")
    assert mixed.code == 2, mixed.err
    records = json.loads(mixed.out)
    assert len(records) == 5
    assert (records[0]["id"], records[0]["passport"], records[0]["kind"]) == ("pkg/m.py::A", 1, "class")
    assert (records[1]["id"], records[1]["passport"], records[1]["kind"]) == ("pkg/n.py::Beta", 1, "class")
    assert records[2] == {"id": "missing", "error": "not found"}
    assert records[3] == {"id": "dup", "error": "ambiguous", "candidates": ["pkg/m.py::dup", "pkg/n.py::dup"]}
    assert (records[4]["id"], records[4]["kind"]) == ("pkg/m.py::run", "function")  # после ошибок паспорта полные
    err_lines = mixed.err.splitlines()
    assert "atlas ref: id 3: not found" in err_lines and "atlas ref: id 4: ambiguous" in err_lines

    text = atlas(repo, "ref", "pkg/m.py::A", "missing", "dup", "--format", "passport")
    assert text.code == 2, text.err
    out_lines = text.out.splitlines()
    heads = [out_lines.index(h) for h in ("== pkg/m.py::A ==", "== missing ==", "== dup ==")]
    assert heads == sorted(heads)
    assert "not found" in out_lines[heads[1] + 1 : heads[2]]
    assert "ambiguous" in out_lines[heads[2] :]
    assert "pkg/m.py::dup" in out_lines and "pkg/n.py::dup" in out_lines  # candidates — путь::qualname в stdout
    assert "atlas ref: id 2: not found" in text.err.splitlines()

    two = atlas(repo, "ref", "pkg/m.py::A", "pkg/m.py::run")  # без --format один id
    assert two.code == 2 and two.out == "" and two.err.strip() != ""
    sym = atlas(repo, "ref", "pkg/m.py::A", "--symbol", "x", "--format", "json")
    assert sym.code == 2 and sym.out == "" and sym.err.strip() != ""
    lone = atlas(repo, "ref", "pkg/m.py::A", "--budget", "10")  # --budget без --format
    assert lone.code == 2 and lone.out == "" and lone.err.strip() != ""


_ROOT_FILES = {
    "pkg/__init__.py": "",
    "pkg/lib.py": "def used():\n    return 1\n",
    "pkg/app.py": "from pkg.lib import used\n\n\ndef main():\n    used()  # @app\n",
    "pkg/gen/__init__.py": "",
    "pkg/gen/auto.py": ("from pkg.lib import used\n\n\nclass Gen:\n    pass\n\n\ndef regen():\n    used()  # @gen\n"),
}


def _path_run(cwd: Path, git_ceiling: Path, *argv: str) -> subprocess.CompletedProcess[str]:
    """`python <кодовый корень>/scripts/atlas <argv>` из cwd вне git, без PYTHONPATH."""
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "PYTHONUTF8", "PYTHONIOENCODING")}
    env.update({"PYTHONUTF8": "1", "GIT_CEILING_DIRECTORIES": str(git_ceiling)})
    return subprocess.run(
        [sys.executable, str(_CODE_ROOT / "scripts" / "atlas"), *argv],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=TIMEOUT_S,
        check=False,
    )


def _wheres(proc: subprocess.CompletedProcess[str]) -> list[str]:
    return sorted(e["where"] for e in json.loads(proc.stdout)[0]["links"]["call_sites"])


def test_ref_root_exclude_and_path_run(repo: GitRepo, tmp_path: Path) -> None:
    """Запуск путём из каталога вне git: корень — от `--root` (подкаталог -> toplevel), не от cwd; `--exclude`
    выбрасывает файлы под префиксом и как символ, и как связь; ошибка id при `--exclude` -> код 2."""
    for rel, text in _ROOT_FILES.items():
        repo.write(rel, text)
    sha = repo.commit("fixture")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    sub = str(repo.path / "pkg")  # подкаталог: корень репозитория определяется git'ом

    plain = _path_run(elsewhere, tmp_path, "ref", "pkg/lib.py::used", "--format", "json", "--root", sub)
    assert plain.returncode == 0, plain.stderr
    assert json.loads(plain.stdout)[0]["sha"] == sha
    assert _wheres(plain) == sorted([_at(_ROOT_FILES, "pkg/app.py", "app"), _at(_ROOT_FILES, "pkg/gen/auto.py", "gen")])

    cut = _path_run(
        elsewhere, tmp_path, "ref", "pkg/lib.py::used", "--format", "json", "--root", sub, "--exclude", "pkg/gen/"
    )
    assert cut.returncode == 0, cut.stderr
    assert _wheres(cut) == [_at(_ROOT_FILES, "pkg/app.py", "app")]  # вызов из pkg/gen не связь

    found = _path_run(elsewhere, tmp_path, "ref", "Gen", "--format", "json", "--root", str(repo.path))
    assert found.returncode == 0, found.stderr
    assert json.loads(found.stdout)[0]["id"] == "pkg/gen/auto.py::Gen"
    gone = _path_run(
        elsewhere, tmp_path, "ref", "Gen", "--format", "json", "--root", str(repo.path), "--exclude", "pkg/gen/"
    )
    assert gone.returncode == 2
    assert json.loads(gone.stdout) == [{"id": "Gen", "error": "not found"}]  # символа в exclude нет
    assert "atlas ref: id 1: not found" in gone.stderr.splitlines()
