"""Авторский тест 1.6e: кэш видов сбрасывается правкой исходника Атласа (отпечаток кода, не версии адаптеров).

Purpose: `code_fingerprint()` читает *.py пакета (build._PKG); правка файла без бампа CORE_VERSION -> пересчёт.
Public API: тесты test_*; публичных имён нет.
Stability: lite
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import pytest

from scripts.atlas.tests.conftest import RepoFactory
from scripts.atlas.tests.test_cache_1_6e import _REFS, _call, _install_spy, _new_repo

__all__: list[str] = []


def test_source_edit_of_atlas_invalidates_view_cache(
    repo_factory: RepoFactory, atlas: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from scripts.atlas import build

    pkg = tmp_path / "atlas_copy"
    shutil.copytree(build._PKG, pkg, ignore=shutil.ignore_patterns("tests", "__pycache__"))
    monkeypatch.setattr(build, "_PKG", pkg)
    repo = _new_repo(repo_factory, "code")
    spy = _install_spy(monkeypatch)
    _call(atlas, spy, repo, "ref", "m", *_REFS)
    _, warm = _call(atlas, spy, repo, "ref", "m", *_REFS)
    assert warm == {"build_graph": 0, "checkout": 0}  # без правки — из кэша
    with (pkg / "codemap.py").open("a", encoding="utf-8") as f:
        f.write("\n# правка исходника\n")
    _, cold = _call(atlas, spy, repo, "ref", "m", *_REFS)
    assert cold["build_graph"] >= 1 and cold["checkout"] >= 1
    _, again = _call(atlas, spy, repo, "ref", "m", *_REFS)
    assert again == {"build_graph": 0, "checkout": 0}  # новый отпечаток тоже кэшируется
