"""Контракт-тесты app_module (module-contract, Ф5.11).

1. Protocol'ы из interfaces.py — runtime_checkable, публичный API стабилен.
2. Инвариант яруса: НИ ОДИН другой framework-модуль не импортирует app_module
   (app_module — верхняя крыша; enforce также .sentrux/rules.toml boundary).
"""

from __future__ import annotations

import re
from pathlib import Path

import multiprocess_framework.modules.app_module as app_module
from multiprocess_framework.modules.app_module import (
    AppSpec,
    BlueprintLoader,
    ManifestStore,
    ManifestStoreProtocol,
    ProcDictsBuilder,
    StateBootstrap,
    assemble_proc_dicts,
    default_blueprint_loader,
)

_MODULES_ROOT = Path(app_module.__file__).resolve().parents[1]
_APP_MODULE_DIR = Path(app_module.__file__).resolve().parent


def test_public_api_surface() -> None:
    """__all__ покрывает ключевые экспорты и все они реально доступны."""
    for name in app_module.__all__:
        assert hasattr(app_module, name), f"экспорт {name} отсутствует"
    for essential in ("run_app", "build_app", "AppManifest", "ManifestStore", "discover", "AppSpec"):
        assert essential in app_module.__all__


def test_protocols_runtime_checkable() -> None:
    # default_blueprint_loader удовлетворяет BlueprintLoader
    assert isinstance(default_blueprint_loader, BlueprintLoader)
    # assemble_proc_dicts удовлетворяет ProcDictsBuilder
    assert isinstance(assemble_proc_dicts, ProcDictsBuilder)
    # ManifestStore удовлетворяет ManifestStoreProtocol
    assert isinstance(ManifestStore(Path("/x/app.yaml")), ManifestStoreProtocol)

    def _bootstrap(bp: dict) -> dict:
        return {}

    assert isinstance(_bootstrap, StateBootstrap)


def test_appspec_carries_di_hooks() -> None:
    spec = AppSpec(manifest_path=Path("/x/app.yaml"))
    # granular-хуки опциональны (generic-путь подставит framework-defaults)
    assert spec.blueprint_loader is None
    assert spec.proc_dicts_builder is None
    assert spec.state_bootstrap is None
    assert spec.launcher_factory is None
    assert spec.orchestrator_class_path is None


def test_no_other_framework_module_imports_app_module() -> None:
    """Инвариант: внутри framework 0 импортов app_module другими модулями (Ф5.11).

    app_module — верхний композиционный ярус: его импортирует только прикладной
    слой (прототип / examples). Любой framework-модуль, тянущий app_module, —
    нарушение направления импортов.
    """
    pattern = re.compile(r"^\s*(from|import)\s+multiprocess_framework\.modules\.app_module\b", re.M)
    offenders: list[str] = []
    for py in _MODULES_ROOT.rglob("*.py"):
        # Пропускаем сам app_module (его внутренние абсолютные ссылки, если появятся).
        if _APP_MODULE_DIR in py.parents or py.parent == _APP_MODULE_DIR:
            continue
        text = py.read_text(encoding="utf-8", errors="ignore")
        if pattern.search(text):
            offenders.append(str(py.relative_to(_MODULES_ROOT)))
    assert offenders == [], f"framework-модули импортируют app_module: {offenders}"
