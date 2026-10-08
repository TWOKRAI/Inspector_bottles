"""Приёмочные тесты видов `card`, `pack`, `log` на пине origin/main (Task 1.6, RED до кода).

Purpose: числа и строки видов на реальной истории checkout (пин a5ae9657a): карточка router_module, хвосты и
    кандидаты `pack`, группы `log`.
Public API: тесты test_*; публичных имён нет.
Stability: lite

Реестр пина строится на СВЕЖЕЙ базе в каталоге pytest (module-scoped): data/atlas.sqlite checkout кэширует сборки
по sha и отпечатку и скрыл бы дефект. Нужен полный клон: предусловие проверяется утверждением, не skip.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from scripts.atlas.tests.conftest import GitRepo, run_with_deadline

__all__: list[str] = []

_ROOT = Path(__file__).resolve().parents[3]
_PIN = "a5ae9657a5bc3aacea61deaa01c1ac212e310ae5"
_PINNED = ("--ref", _PIN, "--main-ref", _PIN)
_CHECKED: list[bool] = []


def _git(*args: str) -> tuple[int, str]:
    import subprocess

    proc = run_with_deadline(lambda: subprocess.run(["git", "-C", str(_ROOT), *args], capture_output=True, check=False))
    return proc.returncode, proc.stdout.decode("utf-8", "replace").strip()


def _preconditions() -> None:
    if _CHECKED:
        return
    code, shallow = _git("rev-parse", "--is-shallow-repository")
    assert (code, shallow) == (0, "false"), "клон неполный: выполнить `git fetch --unshallow` перед тестом"
    code, kind = _git("cat-file", "-t", _PIN)
    assert (code, kind) == (0, "commit"), f"коммит {_PIN} не разрешается в этом клоне"
    _CHECKED.append(True)


@pytest.fixture(scope="module")
def pin_db(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("pin") / "atlas.sqlite"


@pytest.fixture
def pinned(monkeypatch: pytest.MonkeyPatch, pin_db: Path) -> GitRepo:
    """Корень checkout; store.connect открывает общую свежую базу модуля — пин строится один раз."""
    _preconditions()
    from scripts.atlas import store

    real = store.connect
    monkeypatch.setattr("scripts.atlas.store.connect", lambda _path: real(pin_db))
    return GitRepo(_ROOT)


def _ok(res: Any) -> list[str]:
    assert res.code == 0, res.err
    assert res.err == ""
    return res.out.splitlines()


def test_card_on_origin_main_pin(pinned: GitRepo, atlas: Any) -> None:
    lines = _ok(atlas(pinned, "card", "router_module", *_PINNED))
    assert lines[0] == "Модуль router_module — framework, ярус core"
    assert lines[1] == "Назначение: нет purpose в modules.yaml"
    assert lines[2] == "API (2): IMessageChannel, IRouterManager"
    assert lines[3].startswith("Открытые задачи")
    start = lines.index("Коммиты (79 всего, последние 5):")
    assert lines[start : start + 6] == [
        "Коммиты (79 всего, последние 5):",
        "  92fd045 2026-10-05 merge: main в feat/lifecycle-owner-scope перед T1 (spawn на всех ОС, Атлас 0.8)",
        "  9d8e5df 2026-10-05 merge: main в feat/lifecycle-owner-scope перед ревью Task 0.2 и стартом 0.3/0.4",
        "  68a8ba2 2026-10-03 merge: Task 5.5c — весь make gate зелёный (ruff, pyright, bandit -ll, корневой pytest,"
        " те…",
        "  fd906e4 2026-10-03 merge: Task 5.6 — стенд-гейт скриптом и счётчики тракта в телеметрии",
        "  68fb2e6 2026-10-02 chore(merge): Task 5.5 — зелёный набор фреймворка и гейт /dev:ship в main",
    ]
    findings = lines[start + 6 :]
    assert findings[0].startswith("Находки (")
    assert "  info INTERFACE_WITHOUT_TEST interface:router_module:IRouterManager -" in findings
    assert any(line.startswith("Кто использует модуль (") for line in findings)
    assert "Правила ADR-175 (храповик; framework — находки, services/plugins — рекомендация):" in findings
    assert len(lines) <= 60
    assert not any(line.startswith("Доказанность") for line in lines)

    from scripts.atlas.modules import parse_modules

    code, text = _git("show", f"{_PIN}:modules.yaml")
    assert code == 0
    ids = [row["id"] for row in parse_modules(text)]
    assert len(ids) == 87
    too_long: dict[str, int] = {}
    for module_id in ids:
        res = atlas(pinned, "card", module_id, *_PINNED)
        assert (res.code, res.err) == (0, ""), module_id
        if len(res.out.splitlines()) > 60:
            too_long[module_id] = len(res.out.splitlines())
    assert too_long == {}


_FILES_1_5A = [
    "scripts/atlas/DECISIONS.md",
    "scripts/atlas/adapters/code.py",
    "scripts/atlas/adapters/plans.py",
    "scripts/atlas/build.py",
    "scripts/atlas/store.py",
    "scripts/atlas/tests/test_adapters_code.py",
    "scripts/atlas/tests/test_adapters_modules.py",
    "scripts/atlas/tests/test_core_build_key.py",
    "scripts/atlas/tests/test_s2_gate_contract.py",
    "scripts/s2_gate.py",
]


def _blocks(lines: list[str]) -> dict[str, list[str]]:
    """Блоки хвостов: ключ — `slug#id` из заголовка с отступом 2 пробела; значение — строки блока (без заголовка)."""
    blocks: dict[str, list[str]] = {}
    current: list[str] | None = None
    for line in lines:
        if line.startswith("  atlas#") and line.endswith("):") and not line.startswith("   "):
            current = blocks.setdefault(line.strip().split(" ")[0], [])
        elif not line.startswith("  ") or (current is None):
            current = None
        elif current is not None:
            current.append(line)
    return blocks


def _part(block: list[str], title: str) -> list[str]:
    """Строки части блока (отступ 6) после заголовка части с отступом 4, начинающегося с `title`."""
    for index, line in enumerate(block):
        if line.startswith(f"    {title}") and not line.startswith("     "):
            rest: list[str] = []
            for tail in block[index + 1 :]:
                if not tail.startswith("      "):
                    break
                rest.append(tail)
            return rest
    return []


def test_pack_on_origin_main_pin(pinned: GitRepo, atlas: Any) -> None:
    lines = _ok(atlas(pinned, "pack", "atlas#1.5a", *_PINNED))
    assert "Модули: scripts (коммиты задачи)" in lines
    assert "Файлы-кандидаты в FILES (36):" in lines
    assert "  atlas#1.5a (pending):" not in lines
    blocks = _blocks(lines)
    keys = list(blocks)
    assert keys.index("atlas#1.2") + 1 == keys.index("atlas#1.3a")
    unchecked = [text.strip() for text in _part(blocks["atlas#1.2"], "Не проверено:")]
    assert any(
        text.startswith("- Ключ кэша (sha, main_ref, fingerprint) не включает `ctx.base`:") for text in unchecked
    )

    lines = _ok(atlas(pinned, "pack", "atlas#1.6", "--module", "scripts", *_PINNED))
    assert "Модули: scripts (--module)" in lines  # прежнее значение источника «запасной» заменено явным флагом
    for path in _FILES_1_5A:
        rows = [line for line in lines if line.startswith(f"  {path} — ")]
        assert len(rows) == 1, path
        assert "1.5a" in rows[0].split(" — ", 1)[1].split(", "), rows[0]
    assert "Хвосты прошлых задач плана (12 задач):" in lines
    blocks = _blocks(lines)
    mismatch = {"atlas#1.2": 1, "atlas#1.3a": 2, "atlas#1.3b": 3, "atlas#1.5a": 6}
    for key, count in mismatch.items():
        assert f"    Инъекции, где предсказано ≠ наблюдалось ({count}):" in blocks[key], key
    assert "      build.py:55 узлы без сортировки — предсказано 1, наблюдалось 0" in blocks["atlas#1.2"]
    for key, count in {"atlas#1.3b": 9, "atlas#1.3c": 9, "atlas#1.5a": 13}.items():
        assert f"    Открыто для лида ({count}):" in blocks[key], key
    assert blocks["atlas#0.8"] == ["    итог без разделов формы 0.7: plans/2026-10-04_atlas/tasks/0.8.result.md"]

    lines = _ok(atlas(pinned, "pack", "atlas#1.6", *_PINNED))
    modules = next(line for line in lines if line.startswith("Модули: "))
    # у задачи 1.6 нет коммитов; её текст называет router_module (`atlas card router_module`)
    assert modules.endswith("(из текста задачи)")
    assert "router_module" in modules

    lines = _ok(atlas(pinned, "pack", "atlas#1.3a", *_PINNED))
    blocks = _blocks(lines)
    unchecked = [text.strip() for text in _part(blocks["atlas#0.3"], "Не проверено:")]
    assert any(text.startswith("Набор tester не стережёт «точный файл против префикса»") for text in unchecked)


def test_log_on_origin_main_pin(pinned: GitRepo, atlas: Any) -> None:
    lines = _ok(atlas(pinned, "log", "scripts", "-n", "100", "--main-ref", _PIN))
    assert lines[0] == f"Лог модуля scripts — first-parent {_PIN}, записей 80"
    assert [line for line in lines[1:] if not line.startswith("  ")] == [
        "Task atlas#1.5a (1):",
        "Task atlas#1.1 (1):",
        "Task atlas#1.2 (1):",
        "Task atlas#1.3a (1):",
        "Task atlas#1.3b (1):",
        "Task atlas#2.4g (1):",
        "Task atlas#P1.1 (1):",
        "Task atlas#0.8 (1):",
        "Task atlas#0.3 (1):",
        "Task commit-mechanism#1.5 (1):",
        "Task commit-mechanism#2.1 (1):",
        "Task commit-mechanism#2.2 (1):",
        "Task commit-mechanism#2.3 (1):",
        "Task commit-mechanism#3.0 (1):",
        "(без Task) (76):",
    ]
    at = lines.index("Task atlas#1.5a (1):")
    assert lines[at + 1] == "  a5ae965 2026-10-07 merge: origin/main в feat/lifecycle-owner-scope (PR 13-14 Атласа)"
    assert len(lines) == 106
