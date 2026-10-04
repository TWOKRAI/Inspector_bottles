"""Task 1.4 (commit-mechanism) — приёмка: три хука правки сняты (FREEZE), регистрация и документы согласованы.

Контракт (из ТЗ `plans/2026-10-03_commit-mechanism/tasks/1.4.md`, ред. 3, REDS R1-R6; не из реализации):
  * `check-imports.sh` и `typecheck-changed.sh` убраны из PostToolUse в `.claude/settings.json` и в
    `lang-python/.claude-plugin/plugin.json`; живые `autoformat-python.sh` и `autofix-text.sh` остались,
    `semgrep-scan.sh` нигде не подключён;
  * три файла хуков остались на месте, в первых 6 строках каждого — шапка `# FROZEN 2026-10-04`;
  * `lint_settings.lint()` на копии settings.json без этих двух хуков не даёт `hook missing`;
    без `autoformat-python.sh` — по-прежнему даёт (сторож);
  * документы не называют снятые хуки подключёнными.

Тесты с пометкой `guard` проверяют то, что должно остаться верным и до, и после правки (зелёные сейчас);
остальные — красные до реализации.

Предупреждения lint_settings содержат U+2192 (стрелка): сравниваются как `str`, в сообщениях печатаются через
`!a`, чтобы не падать на консоли cp1251.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
CLAUDE = REPO_ROOT / ".claude"

SETTINGS_JSON = CLAUDE / "settings.json"
LANG_PYTHON_PLUGIN_JSON = CLAUDE / "plugins" / "lang-python" / ".claude-plugin" / "plugin.json"
LINT_SETTINGS_PY = CLAUDE / "plugins" / "core" / "scripts" / "lint_settings.py"

HOOK_FILES = [
    CLAUDE / "plugins" / "lang-python" / "hooks" / "check-imports.sh",
    CLAUDE / "plugins" / "lang-python" / "hooks" / "typecheck-changed.sh",
    CLAUDE / "plugins" / "security" / "hooks" / "semgrep-scan.sh",
]

LINT_SETTINGS_DOCS = [
    CLAUDE / "plugins" / "core" / "commands" / "quality" / "lint-settings.md",
    CLAUDE / "commands" / "core" / "quality" / "lint-settings.md",
]
SCAN_DOCS = [
    CLAUDE / "plugins" / "security" / "commands" / "scan.md",
    CLAUDE / "commands" / "security" / "scan.md",
]
BOOTSTRAP = CLAUDE / "BOOTSTRAP.md"
R6_DOCS = [
    CLAUDE / "STACK.md",
    CLAUDE / "plugins" / "lang-python" / "README.md",
    CLAUDE / "plugins" / "security" / "README.md",
    BOOTSTRAP,
]

_FROZEN_HEADER = "# FROZEN 2026-10-04"
_REMOVED_HOOKS = ("check-imports.sh", "typecheck-changed.sh")
_R6_NAMES = ("check-imports", "typecheck-changed", "semgrep-scan")
_R6_MARKERS = ("2026-10-04", "FROZEN", "1.4")
_HOOK_MISSING_AUTOFORMAT = "hook missing: PostToolUse → autoformat-python.sh"


# --------------------------------------------------------------------------- helpers


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _post_tool_use_commands(path: Path) -> list[str]:
    """Все `command` из `hooks.PostToolUse[*].hooks[*]` (любой matcher)."""
    groups = json.loads(_read(path))["hooks"]["PostToolUse"]
    return [h["command"] for group in groups for h in group.get("hooks", [])]


def _hits(commands: list[str], needle: str) -> list[str]:
    return [c for c in commands if needle in c]


def _settings_copy_without(tmp_path: Path, needles: tuple[str, ...]) -> Path:
    """Копия настоящего settings.json, из PostToolUse которой убраны команды с любым из `needles`."""
    data = json.loads(_read(SETTINGS_JSON))
    groups = data["hooks"]["PostToolUse"]
    kept_groups = []
    for group in groups:
        hooks = [h for h in group.get("hooks", []) if not any(n in h["command"] for n in needles)]
        if hooks:
            kept_groups.append({**group, "hooks": hooks})
    data["hooks"]["PostToolUse"] = kept_groups
    copy = tmp_path / "settings.json"
    copy.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return copy


def _load_lint_settings() -> ModuleType:
    spec = importlib.util.spec_from_file_location("_lint_settings_under_test", LINT_SETTINGS_PY)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --------------------------------------------------------------------------- R1: settings.json


def test_r1_settings_has_no_check_imports_or_typecheck_changed() -> None:
    commands = _post_tool_use_commands(SETTINGS_JSON)
    found = {needle: _hits(commands, needle) for needle in _REMOVED_HOOKS}
    assert found == {"check-imports.sh": [], "typecheck-changed.sh": []}


def test_r1_guard_settings_keeps_live_hooks_and_no_semgrep() -> None:
    commands = _post_tool_use_commands(SETTINGS_JSON)
    assert _hits(commands, "autoformat-python.sh"), "autoformat-python.sh must stay registered"
    assert _hits(commands, "autofix-text.sh"), "autofix-text.sh must stay registered"
    assert _hits(commands, "semgrep-scan.sh") == [], "semgrep-scan.sh must not be wired"


# --------------------------------------------------------------------------- R2: lang-python plugin.json


def test_r2_plugin_json_has_no_check_imports_or_typecheck_changed() -> None:
    commands = _post_tool_use_commands(LANG_PYTHON_PLUGIN_JSON)
    found = {needle: _hits(commands, needle) for needle in _REMOVED_HOOKS}
    assert found == {"check-imports.sh": [], "typecheck-changed.sh": []}


def test_r2_guard_plugin_json_keeps_autoformat() -> None:
    commands = _post_tool_use_commands(LANG_PYTHON_PLUGIN_JSON)
    assert _hits(commands, "autoformat-python.sh"), "autoformat-python.sh must stay registered"


# --------------------------------------------------------------------------- R3: FROZEN headers


def test_r3_hook_files_exist_with_frozen_header() -> None:
    problems = []
    for path in HOOK_FILES:
        if not path.is_file():
            problems.append(f"{path.name}: file is missing")
            continue
        head = _read(path).splitlines()[:6]
        if not any(line.startswith(_FROZEN_HEADER) for line in head):
            problems.append(f"{path.name}: no line starting with {_FROZEN_HEADER!r} in the first 6 lines")
    assert problems == []


# --------------------------------------------------------------------------- R4: lint_settings


def test_r4_lint_settings_no_hook_missing_after_removal(tmp_path: Path) -> None:
    lint_settings = _load_lint_settings()
    copy = _settings_copy_without(tmp_path, _REMOVED_HOOKS)

    _errors, warnings = lint_settings.lint(copy)

    missing = [w for w in warnings if w.startswith("hook missing")]
    assert missing == [], f"unexpected 'hook missing' warnings: {missing!a}"


def test_r4_guard_lint_settings_still_flags_missing_autoformat(tmp_path: Path) -> None:
    lint_settings = _load_lint_settings()
    copy = _settings_copy_without(tmp_path, ("autoformat-python.sh",))

    _errors, warnings = lint_settings.lint(copy)

    assert _HOOK_MISSING_AUTOFORMAT in warnings, f"warnings: {warnings!a}"


# --------------------------------------------------------------------------- R5: commands and BOOTSTRAP


def test_r5_lint_settings_docs_do_not_name_check_imports() -> None:
    offenders = [str(p.relative_to(REPO_ROOT)) for p in LINT_SETTINGS_DOCS if "check-imports" in _read(p)]
    assert offenders == []


def test_r5_bootstrap_required_hooks_line_has_no_check_imports() -> None:
    # строка со списком обязательных хуков: по именам, которые остаются в списке
    lines = [
        line for line in _read(BOOTSTRAP).splitlines() if "protect-branch" in line and "session-health-check" in line
    ]
    assert lines, "the required-hooks line was not found in BOOTSTRAP.md"
    assert [line for line in lines if "check-imports" in line] == []


def test_r5_scan_docs_mark_semgrep_scan_line() -> None:
    problems = []
    for path in SCAN_DOCS:
        lines = [line for line in _read(path).splitlines() if "semgrep-scan.sh" in line]
        if not lines:
            problems.append(f"{path.relative_to(REPO_ROOT)}: no line with semgrep-scan.sh")
        problems += [
            f"{path.relative_to(REPO_ROOT)}: {line[:80]!a}"
            for line in lines
            if "FROZEN" not in line and "1.4" not in line
        ]
    assert problems == []


def test_r5_guard_lint_settings_copies_are_identical() -> None:
    first, second = (p.read_bytes() for p in LINT_SETTINGS_DOCS)
    assert first == second


def test_r5_guard_scan_copies_are_identical() -> None:
    first, second = (p.read_bytes() for p in SCAN_DOCS)
    assert first == second


# --------------------------------------------------------------------------- R6: other docs


def test_r6_docs_mark_every_line_naming_a_frozen_hook() -> None:
    problems = []
    for path in R6_DOCS:
        for number, line in enumerate(_read(path).splitlines(), start=1):
            if any(name in line for name in _R6_NAMES) and not any(marker in line for marker in _R6_MARKERS):
                problems.append(f"{path.relative_to(REPO_ROOT)}:{number}: {line[:80]!a}")
    assert problems == []


@pytest.mark.parametrize("path", R6_DOCS, ids=lambda p: p.name)
def test_r6_guard_docs_exist(path: Path) -> None:
    assert path.is_file()
