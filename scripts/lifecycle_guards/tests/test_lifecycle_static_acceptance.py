"""Слепая приёмка статических стражей G2, G6, G10 (lifecycle-owner-scope, 0.5a).

Контракт — пакет ``scripts.lifecycle_guards`` (его на момент написания нет, тесты RED).
Каждый тест строит своё временное дерево (``tmp_path``, без ``.git``) и передаёт свои
таблицы; реальные таблицы пакета затрагивает только CLI-тест, и только на чужом дереве.
Импорт пакета — внутри теста: до реализации падает каждый тест, а не сбор.
Ожидаемые значения — литералы.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]

# Номер строки, на которой стоит нарушение во всех «одностроковых» источниках ниже.
_HEADER = "# header\n\n"
_VIOLATION_LINE = 3

LIFETIME_PATH = "multiprocess_framework/modules/base_manager/core/lifetime.py"
BASE_MANAGER_DIR = "multiprocess_framework/modules/base_manager"


def _write_tree(root: Path, files: dict[str, str]) -> Path:
    for rel, text in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return root


def _text(finding: object) -> str:
    return f"{finding.rule} {finding.message}".lower()  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# G2
# ---------------------------------------------------------------------------

_BUS_PREFIX = "class Bus:\n"


def _bus(sig: str) -> str:
    return f"{_BUS_PREFIX}    def subscribe({sig}):\n        pass\n"


@pytest.mark.parametrize(
    ("case_id", "source", "qualname", "expected_findings"),
    [
        ("clean-kw-only", _bus("self, topic, cb, *, owner: IScope"), "Bus.subscribe", 0),
        ("clean-kw-after-other-kw", _bus("self, cb, *, extra=None, owner: IScope"), "Bus.subscribe", 0),
        (
            "clean-toplevel-function",
            "def subscribe(topic, cb, *, owner: IScope):\n    pass\n",
            "subscribe",
            0,
        ),
        ("bad-annotation-scope", _bus("self, topic, cb, *, owner: Scope"), "Bus.subscribe", 1),
        ("bad-default-none-no-annotation", _bus("self, topic, cb, *, owner=None"), "Bus.subscribe", 1),
        (
            "bad-annotation-with-default",
            _bus("self, topic, cb, *, owner: IScope = None"),
            "Bus.subscribe",
            1,
        ),
        ("bad-annotation-union", _bus("self, topic, cb, *, owner: IScope | None"), "Bus.subscribe", 1),
        ("bad-positional", _bus("self, topic, owner: IScope, cb"), "Bus.subscribe", 1),
        ("bad-absent", _bus("self, topic, cb"), "Bus.subscribe", 1),
    ],
)
def test_g2_signature_injections(tmp_path, case_id, source, qualname, expected_findings):
    from scripts.lifecycle_guards.g2 import check_g2
    from scripts.lifecycle_guards.tables import Publisher

    _write_tree(tmp_path, {"pkg/pub.py": source})
    publishers = [Publisher(path="pkg/pub.py", qualname=qualname, status="migrated")]

    findings = check_g2(tmp_path, publishers)

    assert len(findings) == expected_findings, (case_id, findings)
    for f in findings:
        assert f.guard == "G2"
        assert f.path == "pkg/pub.py"


_ALL_CENSUS_NAMES = [
    "subscribe",
    "add_callback",
    "add_change_callback",
    "add_post_execute_callback",
    "add_push_listener",
    "add_tap",
    "register_message_handler",
    "register_handler",
]


def _bus_with_all_names() -> str:
    body = "".join(f"    def {name}(self):\n        pass\n" for name in _ALL_CENSUS_NAMES)
    return _BUS_PREFIX + body


def test_g2_census_flags_every_listed_name_when_table_is_empty(tmp_path):
    from scripts.lifecycle_guards.g2 import check_g2

    _write_tree(tmp_path, {"pkg/bus.py": _bus_with_all_names()})

    findings = check_g2(tmp_path, [])

    assert len(findings) == 8
    assert {f.line for f in findings} == {2, 4, 6, 8, 10, 12, 14, 16}
    assert all(f.guard == "G2" and f.path == "pkg/bus.py" for f in findings)
    assert all("unlisted publisher" in _text(f) for f in findings)


def test_g2_census_listed_in_table_with_any_status_is_not_a_finding(tmp_path):
    from scripts.lifecycle_guards.g2 import check_g2
    from scripts.lifecycle_guards.tables import Publisher

    _write_tree(tmp_path, {"pkg/bus.py": _bus_with_all_names()})
    statuses = ["pending:todo", "exempt:reason text"] * 4
    publishers = [
        Publisher(path="pkg/bus.py", qualname=f"Bus.{name}", status=status)
        for name, status in zip(_ALL_CENSUS_NAMES, statuses, strict=True)
    ]

    assert check_g2(tmp_path, publishers) == []


def test_g2_census_one_name_missing_from_table_is_exactly_one_finding(tmp_path):
    from scripts.lifecycle_guards.g2 import check_g2
    from scripts.lifecycle_guards.tables import Publisher

    _write_tree(tmp_path, {"pkg/bus.py": _bus_with_all_names()})
    publishers = [
        Publisher(path="pkg/bus.py", qualname=f"Bus.{name}", status="pending:todo")
        for name in _ALL_CENSUS_NAMES
        if name != "add_tap"
    ]

    findings = check_g2(tmp_path, publishers)

    assert len(findings) == 1
    assert findings[0].line == 12  # def add_tap: 6-е определение -> строка 2 + 2*5
    assert "unlisted publisher" in _text(findings[0])


def test_g2_census_ignores_calls_and_lookalike_names(tmp_path):
    from scripts.lifecycle_guards.g2 import check_g2

    source = (
        "def unsubscribe(x):\n"
        "    pass\n"
        "\n"
        "def subscribe_all(x):\n"
        "    pass\n"
        "\n"
        "def run(bus):\n"
        "    bus.subscribe('t', cb)\n"
        "    bus.add_tap(cb)\n"
    )
    _write_tree(tmp_path, {"pkg/use.py": source})

    assert check_g2(tmp_path, []) == []


@pytest.mark.parametrize(
    ("rel_path", "flagged"),
    [
        # производственные
        ("pkg/a.py", True),
        ("Services/a/tools/y.py", True),
        ("pkg/tools/z.py", True),
        ("pkg/robot/r.py", True),
        ("backend_ctl/other.py", True),
        # не производственные
        ("tests/x.py", False),
        ("pkg/tests/x.py", False),
        ("testing/x.py", False),
        ("scripts/x.py", False),
        ("a/b/scripts/x.py", False),
        (".claude/x.py", False),
        ("docs/x.py", False),
        ("plans/x.py", False),
        ("workspace/x.py", False),
        ("examples/x.py", False),
        ("tools/x.py", False),
        ("robot/x.py", False),
        ("backend_ctl/probes/p.py", False),
        ("pkg/test_foo.py", False),
        ("pkg/conftest.py", False),
    ],
)
def test_g2_census_flags_unlisted_publisher(tmp_path, rel_path, flagged):
    from scripts.lifecycle_guards.g2 import check_g2

    _write_tree(tmp_path, {rel_path: "def add_tap(cb):\n    pass\n"})

    findings = check_g2(tmp_path, [])

    if flagged:
        assert len(findings) == 1, (rel_path, findings)
        assert findings[0].guard == "G2"
        assert findings[0].path == rel_path
        assert findings[0].line == 1
        assert "unlisted publisher" in _text(findings[0])
    else:
        assert findings == [], (rel_path, findings)


_BUS_HELPER_ONLY = "class Bus:\n    def helper(self):\n        pass\n"
_BUS_SUBSCRIBE_OK = _bus("self, cb, *, owner: IScope")


@pytest.mark.parametrize(
    ("case_id", "files", "row", "expected_markers", "expected_total"),
    [
        # гнилые строки: любой статус, файла нет
        ("rot-migrated-no-file", {}, ("pkg/gone.py", "Bus.subscribe", "migrated"), ("гнилая строка",), 1),
        ("rot-pending-no-file", {}, ("pkg/gone.py", "Bus.subscribe", "pending:todo"), ("гнилая строка",), 1),
        ("rot-exempt-no-file", {}, ("pkg/gone.py", "Bus.subscribe", "exempt:reason text"), ("гнилая строка",), 1),
        # гнилые строки: файл есть, метода нет
        (
            "rot-migrated-no-method",
            {"pkg/pub.py": _BUS_HELPER_ONLY},
            ("pkg/pub.py", "Bus.subscribe", "migrated"),
            ("гнилая строка",),
            1,
        ),
        (
            "rot-pending-no-method",
            {"pkg/pub.py": _BUS_HELPER_ONLY},
            ("pkg/pub.py", "Bus.subscribe", "pending:todo"),
            ("гнилая строка",),
            1,
        ),
        (
            "rot-exempt-no-method",
            {"pkg/pub.py": _BUS_HELPER_ONLY},
            ("pkg/pub.py", "Bus.subscribe", "exempt:reason text"),
            ("гнилая строка",),
            1,
        ),
        # метод под другим классом: строка гнилая, а настоящий publisher не перечислен
        (
            "rot-wrong-class",
            {"pkg/pub.py": _BUS_SUBSCRIBE_OK},
            ("pkg/pub.py", "Other.subscribe", "pending:todo"),
            ("гнилая строка", "unlisted publisher"),
            2,
        ),
        # парные чистые случаи: строка указывает на живой метод — нечего ловить
        (
            "live-pending",
            {"pkg/pub.py": _bus("self, cb")},
            ("pkg/pub.py", "Bus.subscribe", "pending:todo"),
            (),
            0,
        ),
        (
            "live-exempt",
            {"pkg/pub.py": _bus("self, cb")},
            ("pkg/pub.py", "Bus.subscribe", "exempt:reason text"),
            (),
            0,
        ),
        (
            "live-migrated",
            {"pkg/pub.py": _BUS_SUBSCRIBE_OK},
            ("pkg/pub.py", "Bus.subscribe", "migrated"),
            (),
            0,
        ),
    ],
)
def test_g2_table_rows_must_exist(tmp_path, case_id, files, row, expected_markers, expected_total):
    from scripts.lifecycle_guards.g2 import check_g2
    from scripts.lifecycle_guards.tables import Publisher

    _write_tree(tmp_path, files)
    publishers = [Publisher(path=row[0], qualname=row[1], status=row[2])]

    findings = check_g2(tmp_path, publishers)

    assert len(findings) == expected_total, (case_id, findings)
    for marker in expected_markers:
        assert any(marker in _text(f) for f in findings), (case_id, marker, findings)
    assert all(f.guard == "G2" for f in findings)


# ---------------------------------------------------------------------------
# G6
# ---------------------------------------------------------------------------

_ALLOWED_IMPORTS_LIFETIME = (
    "from __future__ import annotations\n"
    "import collections\n"
    "import dataclasses\n"
    "import itertools\n"
    "import logging\n"
    "import math\n"
    "import threading\n"
    "import time\n"
    "import typing\n"
    "import weakref\n"
    "from collections.abc import Callable\n"
    "from ..interfaces import IScope\n"
)


def _p(body: str) -> str:
    """Источник с нарушением на строке 3."""
    return _HEADER + body


# (case_id, rule, путь нарушения, источник, чистые файлы для парного случая)
_G6_CASES = [
    # R1: потоки только в Plugins/ и Services/
    (
        "R1-threading.Thread",
        "R1",
        "Plugins/p/a.py",
        _p("t = threading.Thread(target=f)\n"),
        {"pkg/a.py": _p("t = threading.Thread(target=f)\n")},
    ),
    (
        "R1-Thread",
        "R1",
        "Plugins/p/a.py",
        _p("t = Thread(target=f)\n"),
        {"pkg/a.py": _p("t = Thread(target=f)\n")},
    ),
    (
        "R1-threading.Timer",
        "R1",
        "Services/s/a.py",
        _p("t = threading.Timer(1.0, f)\n"),
        {"pkg/a.py": _p("t = threading.Timer(1.0, f)\n")},
    ),
    (
        "R1-Timer",
        "R1",
        "Services/s/a.py",
        _p("t = Timer(1.0, f)\n"),
        {
            "pkg/a.py": _p("t = Timer(1.0, f)\n"),
            # ловушка подстроки: QTimer(self) не Timer(
            "Plugins/p/q.py": _p("t = QTimer(self)\n"),
        },
    ),
    (
        "R1-ThreadPoolExecutor",
        "R1",
        "Plugins/p/a.py",
        _p("pool = ThreadPoolExecutor(max_workers=2)\n"),
        {"pkg/a.py": _p("pool = ThreadPoolExecutor(max_workers=2)\n")},
    ),
    # R2: QTimer без родителя
    (
        "R2-no-args",
        "R2",
        "pkg/a.py",
        _p("t = QTimer()\n"),
        {
            "pkg/a.py": _p("t = QTimer(self)\n"),
            "pkg/b.py": _p("t = QTimer(parent=x)\n"),
        },
    ),
    (
        "R2-first-arg-None",
        "R2",
        "pkg/a.py",
        _p("t = QTimer(None)\n"),
        {"pkg/a.py": _p("t = QTimer(self)\n")},
    ),
    # R3: join с числовым сроком
    (
        "R3-positional-int",
        "R3",
        "pkg/a.py",
        _p("t.join(5)\n"),
        {
            "pkg/a.py": _p("t.join()\n"),
            "pkg/b.py": _p("t.join(timeout=t0)\n"),
            "pkg/c.py": _p("s = ','.join(parts)\n"),
        },
    ),
    (
        "R3-positional-float",
        "R3",
        "pkg/a.py",
        _p("t.join(2.5)\n"),
        {"pkg/a.py": _p("t.join(budget)\n")},
    ),
    (
        "R3-keyword-literal",
        "R3",
        "pkg/a.py",
        _p("t.join(timeout=5)\n"),
        {"pkg/a.py": _p("t.join(timeout=t0)\n")},
    ),
    # R4: terminate()/kill() без аргументов вне child_process_stop.py
    (
        "R4-terminate",
        "R4",
        "pkg/a.py",
        _p("p.terminate()\n"),
        {"pkg/child_process_stop.py": _p("p.terminate()\n")},
    ),
    (
        "R4-kill",
        "R4",
        "pkg/a.py",
        _p("p.kill()\n"),
        {
            "pkg/child_process_stop.py": _p("p.kill()\n"),
            "pkg/b.py": _p("os.kill(pid, 9)\n"),
        },
    ),
    # R5: строка shutdown_timeout вне stop_budget.py
    (
        "R5-string-constant",
        "R5",
        "pkg/a.py",
        _p('KEY = "shutdown_timeout"\n'),
        {
            "pkg/stop_budget.py": _p('KEY = "shutdown_timeout"\n'),
            "pkg/b.py": _p('# "shutdown_timeout" упомянут только в комментарии\n'),
        },
    ),
    # R6: deleteLater вне qt_lifetime.py
    (
        "R6-deleteLater",
        "R6",
        "pkg/a.py",
        _p("x.deleteLater()\n"),
        {"pkg/qt_lifetime.py": _p("x.deleteLater()\n")},
    ),
    # R7: импорт base_manager.core.lifetime снаружи base_manager/
    (
        "R7-import",
        "R7",
        "pkg/a.py",
        _p("import multiprocess_framework.modules.base_manager.core.lifetime\n"),
        {
            f"{BASE_MANAGER_DIR}/x.py": _p("import multiprocess_framework.modules.base_manager.core.lifetime\n"),
        },
    ),
    (
        "R7-from-import-lifetime",
        "R7",
        "pkg/a.py",
        _p("from multiprocess_framework.modules.base_manager.core import lifetime\n"),
        {
            f"{BASE_MANAGER_DIR}/x.py": _p("from multiprocess_framework.modules.base_manager.core import lifetime\n"),
        },
    ),
    (
        "R7-from-lifetime-import",
        "R7",
        "pkg/a.py",
        _p("from multiprocess_framework.modules.base_manager.core.lifetime import Scope\n"),
        {
            f"{BASE_MANAGER_DIR}/x.py": _p(
                "from multiprocess_framework.modules.base_manager.core.lifetime import Scope\n"
            ),
        },
    ),
    # R8: lifetime.py импортирует только разрешённое
    (
        "R8-import-os",
        "R8",
        LIFETIME_PATH,
        "from __future__ import annotations\n\nimport os\n",
        {
            LIFETIME_PATH: _ALLOWED_IMPORTS_LIFETIME,
            # R8 касается только lifetime.py: тот же import в соседе — не нарушение
            f"{BASE_MANAGER_DIR}/core/other.py": "from __future__ import annotations\n\nimport os\n",
        },
    ),
    (
        "R8-third-party",
        "R8",
        LIFETIME_PATH,
        "from __future__ import annotations\n\nfrom PySide6 import QtCore\n",
        {LIFETIME_PATH: _ALLOWED_IMPORTS_LIFETIME},
    ),
    (
        "R8-relative-not-interfaces",
        "R8",
        LIFETIME_PATH,
        "from __future__ import annotations\n\nfrom ..other import X\n",
        {LIFETIME_PATH: _ALLOWED_IMPORTS_LIFETIME},
    ),
]


@pytest.mark.parametrize(
    ("case_id", "rule", "path", "source", "clean_files"),
    _G6_CASES,
    ids=[c[0] for c in _G6_CASES],
)
def test_g6_rule_injections(tmp_path_factory, case_id, rule, path, source, clean_files):
    from scripts.lifecycle_guards.g6 import check_g6

    bad_root = _write_tree(tmp_path_factory.mktemp("bad"), {path: source})
    clean_root = _write_tree(tmp_path_factory.mktemp("clean"), clean_files)

    bad = check_g6(bad_root, {})
    clean = check_g6(clean_root, {})

    assert len(bad) == 1, (case_id, bad)
    assert bad[0].guard == "G6"
    assert bad[0].rule == rule
    assert bad[0].path == path
    assert bad[0].line == _VIOLATION_LINE
    assert clean == [], (case_id, clean)


@pytest.mark.parametrize(
    ("rel_path", "counted"),
    [
        ("pkg/a.py", True),
        ("Services/a/tools/y.py", True),
        ("pkg/tools/z.py", True),
        ("tools/x.py", False),
        ("robot/x.py", False),
        ("tests/x.py", False),
    ],
)
def test_g6_scope_exclusions(tmp_path, rel_path, counted):
    from scripts.lifecycle_guards.g6 import check_g6

    _write_tree(tmp_path, {rel_path: _p("x.deleteLater()\n")})

    findings = check_g6(tmp_path, {})

    if counted:
        assert len(findings) == 1, (rel_path, findings)
        assert findings[0].rule == "R6"
        assert findings[0].path == rel_path
    else:
        assert findings == [], (rel_path, findings)


_TWO_R6 = "a.deleteLater()\nb.deleteLater()\n"


@pytest.mark.parametrize(
    ("case_id", "files", "allow", "expected_total", "expected_markers"),
    [
        # ровно count и содержательная причина — чисто
        ("exact", {"pkg/a.py": _TWO_R6}, {("R6", "pkg/a.py"): (2, "legacy shim until 0.6")}, 0, ()),
        # причина ровно 10 знаков — граница, ещё чисто
        ("reason-exactly-10", {"pkg/a.py": _TWO_R6}, {("R6", "pkg/a.py"): (2, "0123456789")}, 0, ()),
        # причина 9 знаков, пустая, короткая — finding
        ("reason-9", {"pkg/a.py": _TWO_R6}, {("R6", "pkg/a.py"): (2, "012345678")}, 1, ()),
        ("reason-empty", {"pkg/a.py": _TWO_R6}, {("R6", "pkg/a.py"): (2, "")}, 1, ()),
        ("reason-short", {"pkg/a.py": _TWO_R6}, {("R6", "pkg/a.py"): (2, "short")}, 1, ()),
        # нарушений больше count
        (
            "new-violation",
            {"pkg/a.py": _TWO_R6},
            {("R6", "pkg/a.py"): (1, "legacy shim until 0.6")},
            1,
            ("новое нарушение",),
        ),
        # нарушений меньше count — запись устарела
        (
            "stale-count-too-high",
            {"pkg/a.py": _TWO_R6},
            {("R6", "pkg/a.py"): (3, "legacy shim until 0.6")},
            1,
            ("запись устарела",),
        ),
        # запись на правило, которое в файле не нарушено
        (
            "stale-other-rule",
            {"pkg/a.py": _TWO_R6},
            {
                ("R6", "pkg/a.py"): (2, "legacy shim until 0.6"),
                ("R3", "pkg/a.py"): (1, "legacy join until 0.6"),
            },
            1,
            ("запись устарела",),
        ),
        # путь записи не существует — гнилая
        (
            "rotten-path",
            {"pkg/a.py": _TWO_R6},
            {
                ("R6", "pkg/a.py"): (2, "legacy shim until 0.6"),
                ("R6", "pkg/missing.py"): (1, "legacy shim until 0.6"),
            },
            1,
            ("запись гнилая",),
        ),
        # (правило, путь) независимы: второй файл без записи — новое нарушение
        (
            "other-file-not-covered",
            {"pkg/a.py": _TWO_R6, "pkg/b.py": "c.deleteLater()\n"},
            {("R6", "pkg/a.py"): (2, "legacy shim until 0.6")},
            1,
            ("новое нарушение",),
        ),
    ],
)
def test_g6_allowlist_ratchet(tmp_path, case_id, files, allow, expected_total, expected_markers):
    from scripts.lifecycle_guards.g6 import check_g6
    from scripts.lifecycle_guards.tables import AllowEntry

    _write_tree(tmp_path, files)
    allowlist = {key: AllowEntry(count=count, reason=reason) for key, (count, reason) in allow.items()}

    findings = check_g6(tmp_path, allowlist)

    assert len(findings) == expected_total, (case_id, findings)
    assert all(f.guard == "G6" for f in findings)
    for marker in expected_markers:
        assert any(marker in _text(f) for f in findings), (case_id, marker, findings)


# ---------------------------------------------------------------------------
# G10
# ---------------------------------------------------------------------------

_MARK = "# lifecycle-shim: временный мост до 0.6\n"


@pytest.mark.parametrize(
    ("case_id", "files", "allowed", "expected_total"),
    [
        # маркеров нет — чисто
        ("no-markers-empty-table", {"pkg/a.py": "x = 1\n"}, {}, 0),
        ("no-markers-with-entry", {"pkg/a.py": "x = 1\n"}, {"pkg/a.py": 1}, 0),
        # маркер в разрешённом файле в пределах бюджета — чисто
        ("one-marker-allowed", {"pkg/a.py": _MARK}, {"pkg/a.py": 1}, 0),
        ("inline-comment-allowed", {"pkg/a.py": "x = 1  # lifecycle-shim: tmp\n"}, {"pkg/a.py": 1}, 0),
        # маркер в файле вне таблицы
        ("marker-outside-table", {"pkg/a.py": _MARK}, {}, 1),
        # маркеров больше разрешённого
        ("marker-over-budget", {"pkg/a.py": _MARK + _MARK}, {"pkg/a.py": 1}, 1),
        # сумма таблицы > 1, даже если маркеров нет
        ("table-sum-over-one", {"pkg/a.py": "x = 1\n", "pkg/b.py": "y = 1\n"}, {"pkg/a.py": 1, "pkg/b.py": 1}, 1),
        # по маркеру в каждом из двух разрешённых файлов: суммарный бюджет превышен
        (
            "two-files-one-marker-each",
            {"pkg/a.py": _MARK, "pkg/b.py": _MARK},
            {"pkg/a.py": 1, "pkg/b.py": 1},
            1,
        ),
        # подстрока вне комментария (строковый литерал) — не маркер
        ("string-literal-is-not-marker", {"pkg/a.py": 'x = "lifecycle-shim: not a comment"\n'}, {}, 0),
        # не производственный файл — не считается
        ("test-file-ignored", {"tests/t.py": _MARK}, {}, 0),
    ],
)
def test_g10_marker_budget(tmp_path, case_id, files, allowed, expected_total):
    from scripts.lifecycle_guards.g10 import check_g10

    _write_tree(tmp_path, files)

    findings = check_g10(tmp_path, allowed)

    assert len(findings) == expected_total, (case_id, findings)
    assert all(f.guard == "G10" for f in findings)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

_SUMMARY_RE = (
    r"^lifecycle-guards: {n} findings \(G2 {g2}, G6 {g6}, G10 {g10}\); "
    r"G2 pending: \d+; allowlist: \d+ entries$"
)


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    return subprocess.run(
        [sys.executable, "-m", "scripts.lifecycle_guards", "check", *args],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
    )


def _summary_pattern(n: int, g2: int, g6: int, g10: int) -> str:
    return _SUMMARY_RE.format(n=n, g2=g2, g6=g6, g10=g10)


@pytest.mark.timeout(120)
@pytest.mark.parametrize(
    ("case_id", "files", "extra_args", "exit_code", "line_pattern", "counts"),
    [
        # нарушение R6 в чужом дереве: код 1, строка по формату, итог G6 1
        (
            "g6-violation",
            {"pkg/a.py": _p("x.deleteLater()\n")},
            [],
            1,
            r"^G6 R6 pkg/a\.py:3 — .+$",
            (1, 0, 1, 0),
        ),
        # пустое дерево: код 0, 0 findings
        ("empty-tree", {}, [], 0, None, (0, 0, 0, 0)),
        # чистое дерево с файлом: код 0
        ("clean-tree", {"pkg/a.py": "x = 1\n"}, [], 0, None, (0, 0, 0, 0)),
        # неперечисленный publisher: G2
        (
            "g2-unlisted-publisher",
            {"pkg/b.py": "def add_tap(cb):\n    pass\n"},
            [],
            1,
            r"^G2 \S+ pkg/b\.py:1 — .+$",
            (1, 1, 0, 0),
        ),
        # маркер shim вне таблицы: G10
        (
            "g10-marker",
            {"pkg/s.py": _MARK},
            [],
            1,
            r"^G10 \S+ pkg/s\.py:1 — .+$",
            (1, 0, 0, 1),
        ),
        # --only g6: G2-нарушение не запускается — код 0
        (
            "only-g6-skips-g2",
            {"pkg/b.py": "def add_tap(cb):\n    pass\n"},
            ["--only", "g6"],
            0,
            None,
            (0, 0, 0, 0),
        ),
        # --only g2: G6-нарушение не запускается — код 0
        (
            "only-g2-skips-g6",
            {"pkg/a.py": _p("x.deleteLater()\n")},
            ["--only", "g2"],
            0,
            None,
            (0, 0, 0, 0),
        ),
        # --only g2,g10 — запускаются оба
        (
            "only-g2-g10-runs-both",
            {"pkg/b.py": "def add_tap(cb):\n    pass\n", "pkg/s.py": _MARK, "pkg/a.py": _p("x.deleteLater()\n")},
            ["--only", "g2,g10"],
            1,
            r"^G10 \S+ pkg/s\.py:1 — .+$",
            (2, 1, 0, 1),
        ),
    ],
)
def test_cli_exit_codes_and_summary(tmp_path, case_id, files, extra_args, exit_code, line_pattern, counts):
    # проверяем, что пакет вообще есть: иначе -m даст «No module named», а не код 0/1
    import scripts.lifecycle_guards  # noqa: F401

    _write_tree(tmp_path, files)

    proc = _run_cli("--root", str(tmp_path), *extra_args)

    assert proc.returncode == exit_code, (case_id, proc.returncode, proc.stdout, proc.stderr)
    if line_pattern is not None:
        assert re.search(line_pattern, proc.stdout, re.MULTILINE), (case_id, proc.stdout)
    n, g2, g6, g10 = counts
    assert re.search(_summary_pattern(n, g2, g6, g10), proc.stdout, re.MULTILINE), (case_id, proc.stdout)
    if n == 0:
        assert "lifecycle-guards: 0 findings" in proc.stdout
