# -*- coding: utf-8 -*-
"""Гейт волны C (Ф2 Task 2.5): в Plugins/ нет молчаливых error-swallow.

Принцип **contain → report → degrade**: каждый ``except``-handler обязан либо
кормить health-плоскость (``report_error``), либо пробрасывать ошибку дальше
(``raise``), либо быть явно классифицирован как легитимный swallow тегом
``# no-health: <причина>`` (control-flow, optional-import gate, defensive
teardown, чистые утилиты без ctx).

AST-скан всех ``Plugins/**/*.py`` (кроме tests): комментарии в AST не видны,
поэтому тег ищется в исходнике по диапазону строк handler'а.

Зелёный тест = acceptance «grep swallow-без-report в Plugins/ = 0» enforced
навсегда: новый swallow без report/тега валит CI.
"""

from __future__ import annotations

import ast
from pathlib import Path

# Корень слоя Plugins/ (этот файл: Plugins/tests/test_no_silent_swallows.py)
_PLUGINS_ROOT = Path(__file__).resolve().parents[1]
_REPO_ROOT = _PLUGINS_ROOT.parent

#: Тег-конвенция волны C для легитимных swallow без report_error.
_TAG = "# no-health:"

#: Временный skip-список: зону Plugins/sources/ параллельно правит Task 2.4 —
#: снимается при merge 2.4 (файлы перечислены по срезу на момент Task 2.5).
_WAVE_C_PART1: list[str] = [
    "Plugins/sources/camera_service/backends/hikvision.py",
    "Plugins/sources/camera_service/backends/webcam.py",
    "Plugins/sources/camera_service/backends/webcam_controls.py",
    "Plugins/sources/camera_service/plugin.py",
    "Plugins/sources/capture/plugin.py",
]


def _iter_plugin_files() -> list[Path]:
    """Все .py слоя Plugins/, кроме тестов (сами тесты гейту не подчиняются)."""
    return sorted(
        p
        for p in _PLUGINS_ROOT.rglob("*.py")
        if "tests" not in p.relative_to(_PLUGINS_ROOT).parts
    )


def _handler_reports(handler: ast.ExceptHandler) -> bool:
    """Есть ли в теле handler'а вызов ``*.report_error(...)`` (кормит health)."""
    for node in ast.walk(handler):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "report_error"
        ):
            return True
    return False


def _handler_reraises(handler: ast.ExceptHandler) -> bool:
    """Есть ли в теле handler'а ``raise`` — ошибка не глотается, идёт дальше."""
    return any(isinstance(node, ast.Raise) for node in ast.walk(handler))


def _handler_tagged(handler: ast.ExceptHandler, lines: list[str]) -> bool:
    """Есть ли тег ``# no-health:`` на строках handler'а (except..конец тела)."""
    start = handler.lineno
    end = handler.body[-1].end_lineno or handler.body[-1].lineno
    return any(_TAG in lines[i - 1] for i in range(start, min(end, len(lines)) + 1))


def _scan_file(path: Path) -> list[str]:
    """Вернуть список нарушений файла (пусто = файл чист)."""
    source = path.read_text(encoding="utf-8")
    lines = source.splitlines()
    tree = ast.parse(source, filename=str(path))
    rel = path.relative_to(_REPO_ROOT)

    violations: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler):
            continue
        if _handler_reports(node) or _handler_reraises(node) or _handler_tagged(node, lines):
            continue
        violations.append(f"{rel}:{node.lineno} — swallow без report_error / raise / '{_TAG}'")
    return violations


def test_no_silent_swallows_in_plugins() -> None:
    """Каждый except-handler в Plugins/: report_error ИЛИ raise ИЛИ тег no-health."""
    all_violations: list[str] = []
    for path in _iter_plugin_files():
        rel = str(path.relative_to(_REPO_ROOT))
        if rel in _WAVE_C_PART1:
            continue  # снимается при merge 2.4 (Plugins/sources — параллельный агент)
        all_violations.extend(_scan_file(path))

    assert not all_violations, (
        "Найдены молчаливые error-swallow (волна C, contain → report → degrade):\n"
        + "\n".join(all_violations)
        + "\nЛибо добавь ctx.health.report_error(exc, context=...), либо пометь "
        f"легитимный swallow тегом '{_TAG} <причина>'."
    )


def test_wave_c_skip_list_shrinks() -> None:
    """Skip-список — временный: файлы без нарушений обязаны из него уходить.

    Если файл из _WAVE_C_PART1 уже чист (Task 2.4 смержен) — тест требует
    убрать его из списка, чтобы skip не пережил свою причину.
    """
    stale = [
        rel
        for rel in _WAVE_C_PART1
        if not (_REPO_ROOT / rel).exists() or not _scan_file(_REPO_ROOT / rel)
    ]
    assert not stale, (
        "Файлы из skip-списка _WAVE_C_PART1 уже чисты (или удалены) — убери их из списка:\n"
        + "\n".join(stale)
    )
