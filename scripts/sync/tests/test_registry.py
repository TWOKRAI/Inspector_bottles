"""Тесты для scripts/sync/registry.py.

Проверяют:
- replace_between_markers: успешная замена контента между маркерами.
- replace_between_markers: MarkerNotFound при отсутствии маркеров.
- apply_sync(check=True): возвращает 1 при дрифте и печатает diff в stderr.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from scripts.sync.registry import MarkerNotFound, apply_sync, replace_between_markers


# ---------------------------------------------------------------------------
# Тест 1: replace_between_markers — успешная замена
# ---------------------------------------------------------------------------


def test_replace_between_markers_ok():
    """replace_between_markers заменяет содержимое и сохраняет тег BEGIN."""
    text = "<!-- K:BEGIN -->\nold\n<!-- K:END -->\n"
    result = replace_between_markers(text, key="K", content="new")

    # Тег BEGIN сохранён
    assert "<!-- K:BEGIN -->" in result, "Тег BEGIN должен сохраниться"
    # Тег END сохранён
    assert "<!-- K:END -->" in result, "Тег END должен сохраниться"
    # Старое содержимое заменено
    assert "old" not in result, "Старое содержимое должно быть удалено"
    # Новое содержимое вставлено
    assert "new" in result, "Новое содержимое должно быть вставлено"


# ---------------------------------------------------------------------------
# Тест 2: replace_between_markers — MarkerNotFound
# ---------------------------------------------------------------------------


def test_marker_not_found():
    """Текст без маркеров → MarkerNotFound с понятным сообщением."""
    text = "no markers here"
    with pytest.raises(MarkerNotFound) as exc_info:
        replace_between_markers(text, key="K", content="new")

    msg = str(exc_info.value)
    assert "K" in msg, "Сообщение должно содержать имя ключа маркера"


# ---------------------------------------------------------------------------
# Тест 3: apply_sync(check=True) → 1 при дрифте, diff в stderr
# ---------------------------------------------------------------------------


@dataclass
class _StubModule:
    """Стаб sync-модуля для тестов."""

    name: str
    description: str
    _file: Path
    _key: str
    _content: str

    def render(self) -> dict[Path, dict[str, str]]:
        return {self._file: {self._key: self._content}}


def test_check_mode_drift_returns_1(tmp_path, capsys):
    """apply_sync(check=True) возвращает 1 при дрифте, печатает diff в stderr."""
    # Создаём временный файл с маркерами и старым контентом
    target = tmp_path / "DECISIONS.md"
    target.write_text(
        "# Header\n<!-- SYNC-TEST:BEGIN -->\nold content\n<!-- SYNC-TEST:END -->\n# Footer\n",
        encoding="utf-8",
    )

    stub = _StubModule(
        name="stub",
        description="stub для теста",
        _file=target,
        _key="SYNC-TEST",
        _content="new content",
    )

    exit_code = apply_sync([stub], check=True)

    assert exit_code == 1, f"Ожидался exit code 1, получен {exit_code}"

    # Diff должен попасть в stderr
    captured = capsys.readouterr()
    assert "old content" in captured.err or "new content" in captured.err, (
        "В stderr должен быть diff с изменёнными строками"
    )
