"""Приёмочные тесты `card` (кто использует модуль, правила ADR-175), `pack` без коммитов, детерминизм (Task 1.6c, A).

Purpose: новые блоки `card` на Ф1/Ф2 и пине config_module (находки 3, доли 1 из 2 / 46 из 48 / 7 из 7 / 0 из 0),
    `pack` для задачи без коммитов на Ф3 (порядок источника --module > коммиты > текст задачи > запасной,
    токены текста: id, суффикс пути, неоднозначный путь, продолжение строки), пин `k0-framework-quality#1.2`,
    «Находки по модулям» и «Другие планы по модулям», байтовая детерминированность ref/card/pack под разными
    PYTHONHASHSEED, неизменность `index` и `index --check`, устойчивый отпечаток сборки с адаптером `rules`.
Public API: тесты test_*; публичных имён нет.
Stability: lite

Ожидаемые значения выведены ВРУЧНУЮ из текста фикстур по DESIGN п. 9-11 брифа plans/2026-10-04_atlas/tasks/1.6c.md;
вывод `index` — снимок поведения 1.6b (он не меняется). Хелперы и Ф1/Ф2 — из test_ref_code.py и test_rules.py.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from scripts.atlas.tests.conftest import GitRepo, RepoFactory, run_with_deadline
from scripts.atlas.tests.test_exam_k0 import _M, _PINNED, pin_db, pinned  # noqa: F401 - фикстуры пина
from scripts.atlas.tests.test_ref_code import (
    REFS,
    block,
    commit,
    f1_repo,
    lines_of,
    modules_yaml,
    new_repo,
    put,
)
from scripts.atlas.tests.test_rules import f2_repo

__all__: list[str] = []

_ROOT = Path(__file__).resolve().parents[3]
_MODULE_USAGE = (
    "Кто использует модуль (статика: импорты модуля целиком вне модуля; getattr, реестры, patch по строке и каналы"
    " роутера не видны): "
)
_RULES_FRAMEWORK = "Правила ADR-175 (храповик; framework — находки, services/plugins — рекомендация):"
_RULES_SERVICES = "Правила ADR-175 (рекомендация; находки не поднимаются):"
_P1 = "  П1 реализации с явным наследованием: "
_P2 = "  П2 docstring Google у публичного API: "
_P3 = "  П3 __all__ у interfaces.py и __init__.py: "
_P4 = "  П4 записи файла в функции с атомарным вызовом (форма записи, не назначение файла): "


# ---------------------------------------------------------------- card на Ф1


def test_card_f1_keeps_old_lines_and_adds_usage_and_rules_blocks(
    repo_factory: RepoFactory, atlas: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = f1_repo(repo_factory, monkeypatch)
    lines = lines_of(atlas(repo, "card", "m", *REFS))
    assert lines[:3] == [
        "Модуль m — framework, ярус —",
        "Назначение: нет purpose в modules.yaml",
        "API (4): IA, IP, IPlain, Sized",
    ]
    found = lines.index("Находки (3):")
    assert lines[found : found + 4] == [
        "Находки (3):",
        "  warning P1_IMPL_NOT_INHERITING module:m Duck>IA",
        "  info INTERFACE_WITHOUT_TEST interface:m:IPlain -",
        "  info INTERFACE_WITHOUT_TEST interface:m:Sized -",
    ]
    usage = lines.index(_MODULE_USAGE + "файлов 2, из них тестов 1")
    assert usage == found + 4, "блок «Кто использует модуль» идёт сразу после «Находки»"
    assert lines[usage + 1 : usage + 3] == ["  u/use.py:2", "  тесты: 1 файлов, первые 3: u/tests/test_use.py"]
    rules = lines.index(_RULES_FRAMEWORK)
    assert rules == usage + 3
    assert lines[rules + 1].startswith(_P1)
    assert lines[rules + 2].startswith(_P2)
    assert lines[rules + 3] == _P3 + "3 из 3"
    assert lines[rules + 4] == _P4 + "0 из 0"
    assert len(lines) == rules + 5


def test_card_of_an_imported_module_lists_the_importing_files(
    repo_factory: RepoFactory, atlas: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = f1_repo(repo_factory, monkeypatch)
    lines = lines_of(atlas(repo, "card", "b", *REFS))
    at = lines.index(_MODULE_USAGE + "файлов 1, из них тестов 0")
    assert lines[at + 1 : at + 3] == ["  m/interfaces.py:5", "  тесты: 0 файлов"]
    assert "Правила ADR-175: вне охвата (слой prototype)" in lines_of(atlas(repo, "card", "u", *REFS))


# ---------------------------------------------------------------- card на Ф2


def test_card_f2_framework_findings_and_shares(
    repo_factory: RepoFactory, atlas: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = f2_repo(repo_factory, monkeypatch)
    lines = lines_of(atlas(repo, "card", "f", *REFS))
    found = lines.index("Находки (16):")
    assert lines[found : found + 12] == [
        "Находки (16):",
        "  warning P1_IMPL_NOT_INHERITING module:f Structural>IGood",
        "  warning P2_DOCSTRING module:f IBad",
        "  warning P2_DOCSTRING module:f IBad.nodoc",
        "  warning P2_DOCSTRING module:f IBad.numpy",
        "  warning P2_DOCSTRING module:f IBad.sphinx",
        "  warning P2_DOCSTRING module:f INoDoc",
        "  warning P2_DOCSTRING module:f Thing.silent",
        "  warning P3_NO_ALL module:f f/__init__.py",
        "  warning P3_NO_ALL module:f f/sub/__init__.py",
        "  warning P4_DIRECT_WRITE module:f f/io.py::<module>",
        "  … ещё 6",
    ]
    rules = lines.index(_RULES_FRAMEWORK)
    assert lines[rules + 1 : rules + 5] == [_P1 + "1 из 2", _P2 + "6 из 12", _P3 + "3 из 5", _P4 + "2 из 6"]


def test_card_f2_services_share_without_findings_and_prototype_out_of_scope(
    repo_factory: RepoFactory, atlas: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = f2_repo(repo_factory, monkeypatch)
    lines = lines_of(atlas(repo, "card", "s", *REFS))
    assert "Находки (1):" in lines
    rules = lines.index(_RULES_SERVICES)
    assert lines[rules + 1 : rules + 5] == [_P1 + "0 из 1", _P2 + "2 из 3", _P3 + "1 из 1", _P4 + "0 из 1"]
    proto = lines_of(atlas(repo, "card", "p", *REFS))
    assert "Правила ADR-175: вне охвата (слой prototype)" in proto
    assert not any(line.startswith("  П") for line in proto)
    assert _RULES_FRAMEWORK not in proto


# ---------------------------------------------------------------- card на пине


def test_card_on_the_pin_for_config_module(pinned: GitRepo, atlas: Any) -> None:  # noqa: F811
    lines = lines_of(atlas(pinned, "card", "config_module", *_PINNED))
    found = lines.index("Находки (3):")
    assert lines[found : found + 4] == [
        "Находки (3):",
        "  warning P1_IMPL_NOT_INHERITING module:config_module Config>IConfig",
        "  warning P2_DOCSTRING module:config_module ConfigManager.initialize",
        "  warning P2_DOCSTRING module:config_module ConfigManager.shutdown",
    ]
    rules = lines.index(_RULES_FRAMEWORK)
    assert lines[rules + 1 : rules + 5] == [_P1 + "1 из 2", _P2 + "46 из 48", _P3 + "7 из 7", _P4 + "0 из 0"]
    assert any(line.startswith(_MODULE_USAGE) for line in lines)


# ---------------------------------------------------------------- pack на Ф3

ALPHA_PLAN = """\
# Alpha

## Порядок выполнения

- Task 1.1: правка m/tools/helper.py и zzz/none.py [PENDING]
- Task 1.2: смотри n/X.py [PENDING]
- Task 1.3: ничего конкретного [PENDING]
- Task 1.4: правим m и n вместе [PENDING]
- Task 1.5: поправить X.py везде [PENDING]
- Task 1.6: первая строка [PENDING]
  продолжение: см. m/tools/helper.py
- Task 1.7: после продолжения [PENDING]
"""
BETA_PLAN = "# Beta\n\n## Порядок выполнения\n\n- Task 1.1: b-first [PENDING]\n"
_HEAD = "Задача alpha#{id} — статус pending, план plans/2026-10-01_alpha/plan.md"
_TAIL = "Хвосты прошлых задач плана (0 задач):"


def f3_repo(factory: RepoFactory, mp: pytest.MonkeyPatch, name: str = "f3") -> GitRepo:
    repo = new_repo(factory, name)
    repo.write("modules.yaml", modules_yaml([("m", "scripts"), ("n", "scripts")]))
    put(repo, "plans/2026-10-01_alpha/plan.md", ALPHA_PLAN)
    put(repo, "plans/2026-10-02_beta/plan.md", BETA_PLAN)
    put(repo, "plans/2026-10-01_alpha/tasks/1.1.md", "заметка\n")
    put(repo, "m/interfaces.py", '__all__ = ["IM"]\n\n\nclass IM:\n    pass\n')
    for rel in ("m/tools/helper.py", "m/X.py", "n/X.py"):
        put(repo, rel, "x = 1\n")
    commit(repo, mp, "2026-09-30", "init")
    put(repo, "m/a.py", "x = 1\n")
    repo.git("add", ".")
    mp.setenv("GIT_AUTHOR_DATE", "2026-10-01T10:00:00+0000")
    mp.setenv("GIT_COMMITTER_DATE", "2026-10-01T10:00:00+0000")
    repo.git("commit", "-q", "-m", "m: a\n\nTask: alpha#1.2")
    put(repo, "m/b.py", "x = 2\n")
    repo.git("add", ".")
    mp.setenv("GIT_AUTHOR_DATE", "2026-10-02T10:00:00+0000")
    mp.setenv("GIT_COMMITTER_DATE", "2026-10-02T10:00:00+0000")
    repo.git("commit", "-q", "-m", "m: b\n\nRefs: plans/2026-10-02_beta/plan.md")
    return repo


def test_pack_without_commits_takes_modules_from_the_task_text(
    repo_factory: RepoFactory, atlas: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = f3_repo(repo_factory, monkeypatch)
    assert lines_of(atlas(repo, "pack", "alpha#1.1", *REFS)) == [
        _HEAD.format(id="1.1"),
        "Модули: m (из текста задачи)",
        "Файлы-кандидаты в FILES (1):",
        "  m/tools/helper.py — из текста задачи",
        _TAIL,
        "Находки по модулям (1):",
        "  info INTERFACE_WITHOUT_TEST interface:m:IM -",
        "Другие планы по модулям:",
        "  m: beta — 1: 1.1",
    ]


def test_pack_text_tokens_id_ambiguous_path_and_continuation(
    repo_factory: RepoFactory, atlas: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = f3_repo(repo_factory, monkeypatch)
    ids = lines_of(atlas(repo, "pack", "alpha#1.4", *REFS))
    modules = next(line for line in ids if line.startswith("Модули: "))
    assert modules.endswith("(из текста задачи)")
    assert "m" in modules.split(" (")[0] and "n" in modules.split(" (")[0]
    assert "Файлы-кандидаты в FILES (0):" in ids  # токены-идентификаторы дают модули, но не файлы
    others = ids.index("Другие планы по модулям:")
    assert ids[others + 1 : others + 3] == ["  m: beta — 1: 1.1", "  n: —"]

    ambiguous = lines_of(atlas(repo, "pack", "alpha#1.5", *REFS))
    start = ambiguous.index("Файлы-кандидаты в FILES (2):")
    assert ambiguous[start + 1 : start + 3] == ["  m/X.py — из текста задачи", "  n/X.py — из текста задачи"]

    continued = lines_of(atlas(repo, "pack", "alpha#1.6", *REFS))
    assert "Модули: m (из текста задачи)" in continued
    assert "  m/tools/helper.py — из текста задачи" in continued
    # строка следующей задачи в текст не входит
    after = lines_of(atlas(repo, "pack", "alpha#1.7", *REFS))
    assert not any(line.startswith("Модули: m (из текста задачи)") for line in after)


def test_pack_source_order_module_flag_commits_text_fallback(
    repo_factory: RepoFactory, atlas: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = f3_repo(repo_factory, monkeypatch)
    by_flag = lines_of(atlas(repo, "pack", "alpha#1.1", "--module", "n", *REFS))
    assert by_flag == [
        _HEAD.format(id="1.1"),
        "Модули: n (--module)",
        "Файлы-кандидаты в FILES (0):",
        _TAIL,
    ]
    # коммиты важнее текста: текст 1.2 называет n/X.py, но у задачи есть коммит в m
    by_commits = lines_of(atlas(repo, "pack", "alpha#1.2", *REFS))
    assert by_commits == [
        _HEAD.format(id="1.2"),
        "Модули: m (коммиты задачи)",
        "Файлы-кандидаты в FILES (1):",
        "  m/a.py — 1.2",
        _TAIL,
    ]
    # текст важнее запасного источника: у 1.6 коммитов нет, продолжение строки называет m/tools/helper.py
    text_wins = lines_of(atlas(repo, "pack", "alpha#1.6", *REFS))
    assert text_wins[1] == "Модули: m (из текста задачи)"
    # ни коммитов, ни токенов: запасной источник, как в 1.6b
    fallback = lines_of(atlas(repo, "pack", "alpha#1.3", *REFS))
    assert fallback == [
        _HEAD.format(id="1.3"),
        "Модули: m (последняя задача плана с модулями — 1.2)",
        "Файлы-кандидаты в FILES (1):",
        "  m/a.py — 1.2",
        _TAIL,
    ]


def test_pack_on_the_pin_for_a_task_without_commits(pinned: GitRepo, atlas: Any) -> None:  # noqa: F811
    lines = lines_of(atlas(pinned, "pack", "k0-framework-quality#1.2", *_PINNED))
    assert "Модули: config_module (из текста задачи)" in lines
    assert f"  {_M}/config_module/tools/watcher.py — из текста задачи" in lines
    start = lines.index("Находки по модулям (3):")
    assert lines[start + 1 : start + 4] == [
        "  warning P1_IMPL_NOT_INHERITING module:config_module Config>IConfig",
        "  warning P2_DOCSTRING module:config_module ConfigManager.initialize",
        "  warning P2_DOCSTRING module:config_module ConfigManager.shutdown",
    ]
    others = lines.index("Другие планы по модулям:")
    assert lines[others + 1].startswith("  config_module: ")
    assert not any(line.startswith("Модули: router_module") for line in lines)


# ---------------------------------------------------------------- детерминизм и неизменность index

_F1_INDEX = [
    "# Индекс проекта — собран командой `python -m scripts.atlas index --write`, руками не править",
    "m — нет purpose в modules.yaml",
    "  IA (3), IPlain (1), IP (0), Sized (0)",
    "b — нет purpose в modules.yaml",
    "  IBase (1)",
    "u — нет purpose в modules.yaml",
]


def _cli(repo: GitRepo, seed: str, *argv: str) -> bytes:
    shutil.rmtree(repo.path / "data", ignore_errors=True)  # каждый процесс — на свежей базе
    env = {**os.environ, "PYTHONHASHSEED": seed, "PYTHONPATH": str(_ROOT), "PYTHONUTF8": "1"}
    proc = run_with_deadline(
        lambda: subprocess.run(
            [sys.executable, "-m", "scripts.atlas", *argv], cwd=repo.path, env=env, capture_output=True, check=False
        )
    )
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
    assert proc.stderr == b""
    return proc.stdout


def test_ref_card_pack_are_byte_equal_twice_and_under_hash_seeds(
    repo_factory: RepoFactory, atlas: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    f1 = f1_repo(repo_factory, monkeypatch)
    f3 = f3_repo(repo_factory, monkeypatch)
    for repo, argv in (
        (f1, ("ref", "m", *REFS)),
        (f1, ("card", "m", *REFS)),
        (f3, ("pack", "alpha#1.1", *REFS)),
    ):
        first = atlas(repo, *argv)
        assert atlas(repo, *argv).out == first.out
        assert any(m in first.out for m in ("Кто использует", "Находки по модулям")), "нет блоков 1.6c"
        runs = {seed: _cli(repo, seed, *argv) for seed in ("0", "1", "2")}
        assert set(runs.values()) == {first.out.encode("utf-8")}, argv


def test_index_output_and_check_are_unchanged(
    repo_factory: RepoFactory, atlas: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = f1_repo(repo_factory, monkeypatch)
    assert lines_of(atlas(repo, "index", *REFS)) == _F1_INDEX
    target = repo.path / "docs" / "atlas" / "INDEX.md"
    res = atlas(repo, "index", "--check", *REFS)
    assert (res.code, res.out, res.err) == (1, "", "atlas index: INDEX.md отстал — запусти atlas index --write\n")
    assert lines_of(atlas(repo, "index", "--write", *REFS)) == ["atlas index: docs/atlas/INDEX.md, 6 строк"]
    assert target.read_bytes() == ("\n".join(_F1_INDEX) + "\n").encode("utf-8")
    assert lines_of(atlas(repo, "index", "--check", *REFS)) == ["atlas index: docs/atlas/INDEX.md свежий, 6 строк"]


def _fingerprints(repo: GitRepo) -> list[str]:
    con = sqlite3.connect(repo.path / "data" / "atlas.sqlite")
    try:
        return [row[0] for row in con.execute("SELECT fingerprint FROM builds ORDER BY build_id")]
    finally:
        con.close()


def test_build_with_the_rules_adapter_is_stable_across_builds(
    repo_factory: RepoFactory, atlas: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = f2_repo(repo_factory, monkeypatch)
    assert atlas(repo, "build", *REFS).code == 0
    first = _fingerprints(repo)
    assert len(first) == 1 and first[0]
    assert atlas(repo, "build", *REFS).code == 0
    assert _fingerprints(repo) == first, "повторная сборка того же ревизии не создаёт новую запись"
    shutil.rmtree(repo.path / "data")
    assert atlas(repo, "build", *REFS).code == 0
    assert _fingerprints(repo) == first, "отпечаток не зависит от прогона"
    assert block(lines_of(atlas(repo, "ref", "q", *REFS)), "IQ — ")[1].startswith("  вид: ABC")
