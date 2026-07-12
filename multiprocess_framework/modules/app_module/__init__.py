"""``app_module`` — «рыба-шаблон» приложения: generic composition root (ярус 2, Ф5.11).

Верхний композиционный ярус framework. Код, который сегодня одинаков для любого
многопроцессного приложения (сборка, discover, манифест, env-нейтральность),
собран под одну крышу — второе приложение становится «данные + декларации +
тонкий bootstrap» (``run_app("app.yaml")``).

**Инвариант яруса** (enforce ``.sentrux/rules.toml``): ``app_module`` — только
композиция, ноль механизмов; **внутри framework никто его не импортирует** (он —
верх). Импортируют только прикладной слой (прототип / ``examples/*``).

Внутренние импорты модуля — относительные (``.manifest`` и т.п.): sentrux не
резолвит relative → boundary «framework → app_module» ловит только чужие absolute-
импорты, не ложно-срабатывая на self.

Публичный API — только через этот файл и ``interfaces.py``.
"""

from __future__ import annotations

from .builder import (
    AppSpec,
    BlueprintError,
    SystemBuilder,
    assemble_proc_dicts,
    default_blueprint_loader,
)
from .discovery import DiscoveryResult, ServiceManifest, discover, discover_services
from .entry import build_app, run_app
from .env import ENV_ALIAS_PAIRS, apply_env_aliases
from .interfaces import (
    BlueprintLoader,
    LauncherFactory,
    ManifestStoreProtocol,
    ProcDictsBuilder,
    StateBootstrap,
)
from .manifest import AppManifest, DiscoverySpec, load_manifest
from .store import ManifestStore

__all__ = [
    # entry
    "run_app",
    "build_app",
    # manifest
    "AppManifest",
    "DiscoverySpec",
    "load_manifest",
    "ManifestStore",
    # discovery
    "discover",
    "discover_services",
    "DiscoveryResult",
    "ServiceManifest",
    # builder
    "AppSpec",
    "SystemBuilder",
    "assemble_proc_dicts",
    "default_blueprint_loader",
    "BlueprintError",
    # env
    "apply_env_aliases",
    "ENV_ALIAS_PAIRS",
    # interfaces (Protocol'ы)
    "BlueprintLoader",
    "ProcDictsBuilder",
    "StateBootstrap",
    "LauncherFactory",
    "ManifestStoreProtocol",
]
