"""Опасности и реальное дерево для стражей G2/G6/G10 (авторские тесты, 0.5a).

Слепая приёмка — ``test_lifecycle_static_acceptance.py``; здесь то, что она не трогает:
реальные таблицы, реальное дерево, worktree (``.git`` — ФАЙЛ). Ожидаемые числа — литералы
замера лида 2026-10-11 на 4381fe9d4, не выведенные из кода.
"""

from __future__ import annotations

import subprocess
from collections import Counter
from dataclasses import replace
from pathlib import Path

from scripts.lifecycle_guards import tables
from scripts.lifecycle_guards.__main__ import has_repo_tables, run_all
from scripts.lifecycle_guards.g2 import check_g2
from scripts.lifecycle_guards.g6 import check_g6, scan_file
from scripts.lifecycle_guards.g10 import check_g10
from scripts.lifecycle_guards.tables import AllowEntry, Publisher, list_py_files

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_real_publishers_table_shape() -> None:
    statuses = Counter(p.status.split(":", 1)[0] for p in tables.PUBLISHERS)

    assert len(tables.PUBLISHERS) == 52
    assert statuses == {"migrated": 1, "pending": 41, "exempt": 10}
    assert len({(p.path, p.qualname) for p in tables.PUBLISHERS}) == 52
    assert all("/" in p.path and "\\" not in p.path for p in tables.PUBLISHERS)


def test_real_allowlist_table_shape() -> None:
    per_rule_entries = Counter(rule for rule, _ in tables.ALLOWLIST)
    per_rule_violations: Counter[str] = Counter()
    for (rule, _), entry in tables.ALLOWLIST.items():
        per_rule_violations[rule] += entry.count

    assert len(tables.ALLOWLIST) == 71
    assert per_rule_entries == {"R1": 13, "R2": 8, "R3": 18, "R4": 10, "R5": 2, "R6": 20}
    assert per_rule_violations == {"R1": 16, "R2": 9, "R3": 20, "R4": 19, "R5": 5, "R6": 22}
    assert all(len(e.reason.strip()) >= 10 for e in tables.ALLOWLIST.values())
    assert all("\\" not in path for _, path in tables.ALLOWLIST)


def test_real_shims_ceiling() -> None:
    assert sum(tables.SHIMS.values()) <= 1


def test_real_tree_passes_every_guard() -> None:
    assert run_all(REPO_ROOT) == []


def test_real_tree_unlisted_publisher_turns_g2_red() -> None:
    dropped = tables.PUBLISHERS[0]
    findings = check_g2(REPO_ROOT, tables.PUBLISHERS[1:])

    assert [(f.rule, f.path) for f in findings] == [("census", dropped.path)]
    assert "unlisted publisher" in findings[0].message


def test_real_tree_migrated_row_with_wrong_signature_turns_g2_red() -> None:
    # pending-строка, объявленная migrated, но с неподходящей сигнатурой (owner нет в Config.subscribe)
    rows = [replace(p, status="migrated") if p.qualname == "Config.subscribe" else p for p in tables.PUBLISHERS]

    findings = check_g2(REPO_ROOT, rows)

    assert [f.rule for f in findings] == ["signature"]


def test_real_tree_changed_allowlist_count_turns_g6_red() -> None:
    key = ("R6", "multiprocess_prototype/frontend/widgets/tabs/recipes/tab.py")
    entry = tables.ALLOWLIST[key]

    too_high = check_g6(REPO_ROOT, {**tables.ALLOWLIST, key: AllowEntry(entry.count + 1, entry.reason)})
    too_low = check_g6(REPO_ROOT, {**tables.ALLOWLIST, key: AllowEntry(entry.count - 1, entry.reason)})

    assert [(f.rule, f.path) for f in too_high] == [("R6", key[1])]
    assert "запись устарела" in too_high[0].message
    assert [(f.rule, f.path) for f in too_low] == [("R6", key[1])]
    assert "новое нарушение" in too_low[0].message


def test_real_tree_empty_allowlist_turns_g6_red() -> None:
    findings = check_g6(REPO_ROOT, {})

    assert len(findings) == 91  # 16 + 9 + 20 + 19 + 5 + 22 нарушений замера, ни одного разрешённого


def test_shim_marker_outside_real_table_turns_g10_red(tmp_path: Path) -> None:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "a.py").write_text("x = 1  # lifecycle-shim: tmp\n", encoding="utf-8")

    assert [f.rule for f in check_g10(tmp_path, tables.SHIMS)] == ["shim"]


def test_foreign_root_gets_empty_tables(tmp_path: Path) -> None:
    assert has_repo_tables(REPO_ROOT)
    assert not has_repo_tables(tmp_path)
    assert run_all(tmp_path) == []


def test_bare_name_calls_are_not_method_calls() -> None:
    # lifetime.py зовёт ``kill()`` как локальное имя — это не ``.kill()`` у процесса
    source = "def f(kill, deleteLater):\n    kill()\n    deleteLater()\n    t = foo.Thread(target=f)\n"

    assert scan_file("Plugins/p/a.py", source) == []


def _git(cwd: Path, *args: str) -> None:
    cmd = ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args]
    subprocess.run(cmd, cwd=cwd, check=True, capture_output=True)


def test_worktree_dot_git_is_a_file_and_listing_still_works(tmp_path: Path) -> None:
    main = tmp_path / "main"
    main.mkdir()
    _git(main, "init", "-q")
    (main / "pkg").mkdir()
    (main / "pkg" / "a.py").write_text("x.deleteLater()\n", encoding="utf-8")
    (main / "pkg" / "untracked_later.py").write_text("y = 1\n", encoding="utf-8")
    _git(main, "add", "pkg/a.py")
    _git(main, "commit", "-q", "-m", "init")
    wt = tmp_path / "wt"
    _git(main, "worktree", "add", "-q", str(wt), "-b", "wt-branch")

    assert (wt / ".git").is_file()
    assert list_py_files(wt) == ["pkg/a.py"]
    findings = check_g6(wt, {})
    assert [(f.rule, f.path, f.line) for f in findings] == [("R6", "pkg/a.py", 1)]


def test_publisher_row_in_unparsable_file_is_rot_not_crash(tmp_path: Path) -> None:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "a.py").write_text("def subscribe(:\n", encoding="utf-8")

    findings = check_g2(tmp_path, [Publisher("pkg/a.py", "subscribe", "pending:x")])

    assert [f.rule for f in findings] == ["table-row"]
