"""Тесты для CLI scripts/sync/__main__.py.

Проверяют:
- --list печатает имена трёх зарегистрированных sync-модулей.
- --only фильтрует модули: render() второго НЕ вызывается.
- Идемпотентность: после write повторный check → exit 0.
- Ручная правка между маркерами → check → exit 1.
"""
from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from scripts.sync.registry import apply_sync

# Корень репозитория (4 уровня вверх: tests → sync → scripts → repo_root)
REPO_ROOT = Path(__file__).parent.parent.parent.parent


# ---------------------------------------------------------------------------
# Вспомогательный стаб модуля
# ---------------------------------------------------------------------------


@dataclass
class _CountingStub:
    """Стаб sync-модуля со счётчиком вызовов render()."""

    name: str
    description: str
    _file: Path
    _key: str
    _content: str
    render_calls: int = field(default=0, init=False)

    def render(self) -> dict[Path, dict[str, str]]:
        self.render_calls += 1
        return {self._file: {self._key: self._content}}


# ---------------------------------------------------------------------------
# Тест 1: --list показывает три модуля
# ---------------------------------------------------------------------------


def test_list_shows_three_modules():
    """python -m scripts.sync --list печатает 3 строки с именами."""
    result = subprocess.run(
        [sys.executable, "-m", "scripts.sync", "--list"],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )

    assert result.returncode == 0, (
        f"Ожидался exit code 0, получен {result.returncode}\nstderr: {result.stderr}"
    )
    assert "adr_modules" in result.stdout, "В выводе должно быть 'adr_modules'"
    assert "adr_toc" in result.stdout, "В выводе должно быть 'adr_toc'"
    assert "adr_obsolete" in result.stdout, "В выводе должно быть 'adr_obsolete'"


# ---------------------------------------------------------------------------
# Тест 2: --only изолирует модуль (render() второго НЕ вызывается)
# ---------------------------------------------------------------------------


def test_only_flag_isolates(tmp_path):
    """--only adr_toc не вызывает render() других модулей."""
    # Создаём файлы с маркерами для двух стабов
    file_a = tmp_path / "file_a.md"
    file_a.write_text(
        "<!-- STUB-A:BEGIN -->\nold_a\n<!-- STUB-A:END -->\n",
        encoding="utf-8",
    )

    file_b = tmp_path / "file_b.md"
    file_b.write_text(
        "<!-- STUB-B:BEGIN -->\nold_b\n<!-- STUB-B:END -->\n",
        encoding="utf-8",
    )

    stub_a = _CountingStub(
        name="adr_toc",
        description="stub A",
        _file=file_a,
        _key="STUB-A",
        _content="new_a",
    )
    stub_b = _CountingStub(
        name="other_module",
        description="stub B",
        _file=file_b,
        _key="STUB-B",
        _content="new_b",
    )

    apply_sync([stub_a, stub_b], check=False, only="adr_toc")

    assert stub_a.render_calls == 1, (
        f"render() модуля 'adr_toc' должен быть вызван 1 раз, вызван {stub_a.render_calls}"
    )
    assert stub_b.render_calls == 0, (
        f"render() модуля 'other_module' НЕ должен вызываться, вызван {stub_b.render_calls}"
    )


# ---------------------------------------------------------------------------
# Тест 3: после write повторный check → exit 0 (идемпотентность)
# ---------------------------------------------------------------------------


def test_check_after_write_exit0(tmp_path):
    """После apply_sync(check=False) повторный apply_sync(check=True) → 0 (идемпотентность)."""
    target = tmp_path / "doc.md"
    target.write_text(
        "<!-- SYNC:BEGIN -->\nold\n<!-- SYNC:END -->\n",
        encoding="utf-8",
    )

    stub = _CountingStub(
        name="stub",
        description="stub для теста идемпотентности",
        _file=target,
        _key="SYNC",
        _content="new content",
    )

    # Первый прогон — write
    write_code = apply_sync([stub], check=False)
    assert write_code == 0, f"Ожидался exit code 0 после write, получен {write_code}"

    # Второй прогон — check после write → должен быть 0
    check_code = apply_sync([stub], check=True)
    assert check_code == 0, (
        f"Ожидался exit code 0 при check после write (идемпотентность), получен {check_code}"
    )


# ---------------------------------------------------------------------------
# Тест 4: ручная правка между маркерами → check → exit 1
# ---------------------------------------------------------------------------


def test_check_after_manual_edit_exit1(tmp_path, capsys):
    """Ручная правка между маркерами → apply_sync(check=True) → 1."""
    target = tmp_path / "doc.md"
    target.write_text(
        "<!-- SYNC:BEGIN -->\noriginal\n<!-- SYNC:END -->\n",
        encoding="utf-8",
    )

    stub = _CountingStub(
        name="stub",
        description="stub для теста ручной правки",
        _file=target,
        _key="SYNC",
        _content="original",
    )

    # Первый прогон — write (синхронизируем)
    apply_sync([stub], check=False)

    # Ручная правка файла между маркерами
    target.write_text(
        "<!-- SYNC:BEGIN -->\nmanually edited content\n<!-- SYNC:END -->\n",
        encoding="utf-8",
    )

    # Check должен обнаружить дрифт
    check_code = apply_sync([stub], check=True)
    assert check_code == 1, (
        f"Ожидался exit code 1 после ручной правки, получен {check_code}"
    )
