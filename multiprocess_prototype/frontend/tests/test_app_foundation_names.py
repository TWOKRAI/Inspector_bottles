# -*- coding: utf-8 -*-
"""Проводка Task 1.14b (C-30): имена процессов ``manifest.base`` -> ``TopologySession.foundation_names``.

Save не пишет в рецепт процессы фундамента; чьи они — известно там, где фундамент подмешивают к рецепту
(``frontend/app.py``). Тест берёт НАСТОЯЩИЙ манифест приложения и проверяет помощник, который app кладёт в сессию.
"""

from __future__ import annotations

from pathlib import Path

from multiprocess_prototype.backend.config.manifest import load_manifest
from multiprocess_prototype.main import resolve_manifest_path


class _Manifest:
    def __init__(self, base: list[Path]) -> None:
        self.base = base


def test_boot_foundation_names_from_real_manifest() -> None:
    """Реальный манифест приложения: фундамент = ``devices`` (``gui`` — узел рецепта, в ``base.yaml`` его нет)."""
    from multiprocess_prototype.frontend.app import _foundation_names

    warnings: list[str] = []

    names = _foundation_names(load_manifest(resolve_manifest_path()), warnings.append)

    assert names == frozenset({"devices"})
    assert warnings == []


def test_boot_foundation_names_broken_fragment_gives_empty_and_warns(tmp_path: Path) -> None:
    """Битый фрагмент фундамента: ``frozenset()`` и одно предупреждение (как у слияния)."""
    from multiprocess_prototype.frontend.app import _foundation_names

    fragment = tmp_path / "base_fragment.yaml"
    fragment.write_bytes(b"key: [unclosed\n")
    warnings: list[str] = []

    names = _foundation_names(_Manifest([fragment]), warnings.append)

    assert names == frozenset()
    assert len(warnings) == 1


def test_boot_foundation_names_skips_nameless_and_non_string_entries(tmp_path: Path) -> None:
    """В имена попадают только строковые ``process_name``; не-mapping и безымянные элементы пропускаются."""
    from multiprocess_prototype.frontend.app import _foundation_names

    fragment = tmp_path / "frag.yaml"
    fragment.write_text(
        "processes:\n  - process_name: devices\n  - process_name: [x]\n  - plugins: []\n  - just_a_string\n",
        encoding="utf-8",
    )

    assert _foundation_names(_Manifest([fragment]), lambda _msg: None) == frozenset({"devices"})
