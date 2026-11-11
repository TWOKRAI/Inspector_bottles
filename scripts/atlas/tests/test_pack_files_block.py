"""Приёмочные тесты `pack`: блок FILES файла задачи и неоднозначное голое имя файла (поправка к Task 1.6c).

Purpose: два дефекта `pack`, найденные на живых планах:
    Д1 — `pack dataset-sidecar-truth#1.1a` давал 0 файлов-кандидатов: строка `- Task {id}:` плана путей не
        называет, а блок `FILES (complete list …)` файла `tasks/<id>.md` не читался. Теперь он — часть источника
        «из текста задачи»: после коммитов задачи, вместе с однозначными путями строки плана
        (`views._text_files`; его же зовёт `brief`); пути берутся точно, как написаны (файла может не быть —
        «новый»), строки «Только читать» и продолжения пунктов не в счёт.
    Д2 (не принят, контракт 1.6c «неоднозначный путь -> все»): голое `controller.py` в строке плана без блока FILES
        по-прежнему даёт все совпадения; при блоке FILES голое имя с несколькими совпадениями из строки не берётся.
        Остаток: задача БЕЗ блока FILES с неоднозначным голым именем цепляет все совпадения (задокументировано).
Public API: тесты test_*; публичных имён нет.
Stability: lite

Ожидаемые значения выведены ВРУЧНУЮ из текста фикстур ниже, не из вывода `pack`.
"""

from __future__ import annotations

from typing import Any

import pytest

from scripts.atlas.tests.conftest import GitRepo, RepoFactory
from scripts.atlas.tests.test_ref_code import REFS, commit, lines_of, modules_yaml, new_repo, put

__all__: list[str] = []

_PLAN = """\
# Gamma

## Порядок выполнения

- Task 1.1: без путей в строке [PENDING]
- Task 1.2: без файла задачи [PENDING]
- Task 1.3: правка controller.py [PENDING]
- Task 1.4: правка n/X.py [PENDING]
- Task 1.5: правка b/controller.py и helper.py [PENDING]
- Task 1.6: правка controller.py [PENDING]
- Task 1.7: правка n/X.py [PENDING]
- Task 1.8: правка controller.py [PENDING]
- Task 1.9: объект без имени в строке [PENDING]
"""
_FILES_11 = """\
# Task 1.1

### FILES

FILES (complete list — nothing else; need another file -> stop and ask the lead):
  1. m/tools/helper.py — шаг 1
  2. `m/tests/test_helper.py` — новый
     продолжение пункта: n/X.py не файл задачи
  Только читать: n/X.py

### REDS

  1. n/Y.py — не из FILES
"""
_FILES_14 = """\
FILES (complete list — nothing else; need another file -> stop and ask the lead):
  1. m/tools/helper.py — шаг 1
"""
_FILES_16 = """\
FILES (complete list — nothing else; need another file -> stop and ask the lead):
  1. zzz/outside.py — вне модулей
"""
_FILES_17 = """\
FILES (complete list — nothing else; need another file -> stop and ask the lead):
  1. m/a.py — коммит этой задачи тоже трогал m/a.py
"""
_FILES_18 = """\
FILES (complete list — nothing else; need another file -> stop and ask the lead):
  1. m/a/controller.py — единственный нужный controller.py
  2. m/a/tests/test_controller.py — новый
"""
_FILES_19 = """\
FILES (complete list — nothing else; need another file -> stop and ask the lead):
  1. m/tests/test_widget.py — REDS
  2. m/widget.py — правка
"""
_WIDGET = 'class Widget:\n    """Виджет."""\n\n    def run(self) -> int:\n        return 1\n'
_HEAD = "Задача gamma#{id} — статус pending, план plans/2026-11-01_gamma/plan.md"
_TAIL = "Хвосты прошлых задач плана ("


def _repo(factory: RepoFactory, mp: pytest.MonkeyPatch, name: str = "pfb") -> GitRepo:
    repo = new_repo(factory, name)
    repo.write("modules.yaml", modules_yaml([("m", "scripts"), ("n", "scripts")]))
    put(repo, "plans/2026-11-01_gamma/plan.md", _PLAN)
    put(repo, "plans/2026-11-01_gamma/tasks/1.1.md", _FILES_11)
    put(repo, "plans/2026-11-01_gamma/tasks/1.4.md", _FILES_14)
    put(repo, "plans/2026-11-01_gamma/tasks/1.6.md", _FILES_16)
    put(repo, "plans/2026-11-01_gamma/tasks/1.7.md", _FILES_17)
    put(repo, "plans/2026-11-01_gamma/tasks/1.8.md", _FILES_18)
    put(repo, "plans/2026-11-01_gamma/tasks/1.9.md", _FILES_19)
    put(repo, "m/widget.py", _WIDGET)
    put(
        repo,
        "m/tests/test_widget.py",
        "".join(f"def test_{n}() -> None:\n    assert True\n\n\n" for n in "abc"),
    )
    for rel in ("m/tools/helper.py", "m/a.py", "n/X.py", "m/a/controller.py", "m/b/controller.py", "n/controller.py"):
        put(repo, rel, "x = 1\n")
    commit(repo, mp, "2026-10-30", "init")
    return repo


def _with_task_commit(repo: GitRepo, mp: pytest.MonkeyPatch) -> None:
    put(repo, "m/a.py", "x = 2\n")
    repo.git("add", ".")
    mp.setenv("GIT_AUTHOR_DATE", "2026-11-02T10:00:00+0000")
    mp.setenv("GIT_COMMITTER_DATE", "2026-11-02T10:00:00+0000")
    repo.git("commit", "-q", "-m", "m: a\n\nTask: gamma#1.7")


# ---------------------------------------------------------------- Д1: блок FILES задачи


def test_files_block_of_task_file_gives_candidates(
    repo_factory: RepoFactory, atlas: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repo(repo_factory, monkeypatch)
    lines = lines_of(atlas(repo, "pack", "gamma#1.1", *REFS))
    assert lines[:5] == [
        _HEAD.format(id="1.1"),
        "Модули: m (из текста задачи)",
        "Файлы-кандидаты в FILES (2):",
        "  m/tests/test_helper.py — из текста задачи",
        "  m/tools/helper.py — из текста задачи",
    ]
    assert lines[5].startswith(_TAIL)
    assert not any("n/X.py" in line or "n/Y.py" in line for line in lines[:5])  # «Только читать», продолжение, REDS
    assert "Другие планы по модулям:" in lines  # те же блоки модулей, что у ветки «из текста задачи»


def test_files_block_extends_unambiguous_text_paths_but_commits_win(
    repo_factory: RepoFactory, atlas: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repo(repo_factory, monkeypatch)
    _with_task_commit(repo, monkeypatch)
    # у 1.4 текст строки называет n/X.py (путь с «/» однозначен), блок FILES — m/tools/helper.py: берутся оба
    by_block = lines_of(atlas(repo, "pack", "gamma#1.4", *REFS))
    assert by_block[1:5] == [
        "Модули: m, n (из текста задачи)",
        "Файлы-кандидаты в FILES (2):",
        "  m/tools/helper.py — из текста задачи",
        "  n/X.py — из текста задачи",
    ]
    # у 1.7 есть коммит и блок FILES: коммиты важнее
    by_commits = lines_of(atlas(repo, "pack", "gamma#1.7", *REFS))
    assert by_commits[1:4] == ["Модули: m (коммиты задачи)", "Файлы-кандидаты в FILES (1):", "  m/a.py — 1.7"]


def test_task_without_task_file_or_with_foreign_files_keeps_old_behaviour(
    repo_factory: RepoFactory, atlas: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repo(repo_factory, monkeypatch)
    # у 1.2 нет tasks/1.2.md, в строке нет путей: пусто, как было
    no_file = lines_of(atlas(repo, "pack", "gamma#1.2", *REFS))
    assert no_file[1:3] == ["Модули: — (у плана нет коммитов с модулями)", "Файлы-кандидаты в FILES (0):"]
    # у 1.6 блок FILES называет только путь вне модулей: источник не берётся, остаётся текст строки
    foreign = lines_of(atlas(repo, "pack", "gamma#1.6", *REFS))
    assert foreign[1:3] == ["Модули: m, n (из текста задачи)", "Файлы-кандидаты в FILES (3):"]


# ---------------------------------------------------------------- Д2 не принят: голое имя файла


def test_files_block_beats_ambiguous_bare_name_in_plan_line(
    repo_factory: RepoFactory, atlas: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repo(repo_factory, monkeypatch)
    # строка 1.8 называет голое `controller.py` (m/a/, m/b/, n/), блок FILES — один m/a/controller.py и новый тест
    lines = lines_of(atlas(repo, "pack", "gamma#1.8", *REFS))
    assert lines[1:5] == [
        "Модули: m (из текста задачи)",
        "Файлы-кандидаты в FILES (2):",
        "  m/a/controller.py — из текста задачи",
        "  m/a/tests/test_controller.py — из текста задачи",
    ]


def test_ambiguous_bare_name_without_files_block_still_matches_all(
    repo_factory: RepoFactory, atlas: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repo(repo_factory, monkeypatch)
    # у 1.3 нет tasks/1.3.md: контракт 1.6c «неоднозначный путь -> все совпадения» не тронут
    lines = lines_of(atlas(repo, "pack", "gamma#1.3", *REFS))
    assert lines[1:6] == [
        "Модули: m, n (из текста задачи)",
        "Файлы-кандидаты в FILES (3):",
        "  m/a/controller.py — из текста задачи",
        "  m/b/controller.py — из текста задачи",
        "  n/controller.py — из текста задачи",
    ]


def test_path_with_slash_and_unique_bare_name_match_as_before(
    repo_factory: RepoFactory, atlas: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repo(repo_factory, monkeypatch)
    # `b/controller.py` — суффикс пути с «/», `helper.py` — единственное совпадение: оба как раньше
    lines = lines_of(atlas(repo, "pack", "gamma#1.5", *REFS))
    assert lines[1:5] == [
        "Модули: m (из текста задачи)",
        "Файлы-кандидаты в FILES (2):",
        "  m/b/controller.py — из текста задачи",
        "  m/tools/helper.py — из текста задачи",
    ]


# ---------------------------------------------------------------- brief читает те же файлы, что pack


def test_brief_object_comes_from_files_block(
    repo_factory: RepoFactory, atlas: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PYTHONDONTWRITEBYTECODE", "1")
    repo = _repo(repo_factory, monkeypatch)
    # строка 1.9 имени символа и пути не содержит; блок FILES называет m/widget.py и тест m/tests/test_widget.py
    res = atlas(repo, "brief", "gamma#1.9")
    assert res.code == 0, res.err
    assert "объект задачи не найден" not in res.err
    out = res.out
    assert "файл объекта Widget" in out
    assert "m/widget.py" in out
    # три test_* из FILES идут в пути раньше m/widget.py: объекты «первые три» их бы заняли, Widget выпал бы
