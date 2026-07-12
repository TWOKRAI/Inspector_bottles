"""Публичные контракты ``app_module`` (module-contract, Ф5.11).

``app_module`` — верхний композиционный ярус framework («рыба-шаблон»). Его
точки расширения — Protocol'ы (DI вместо наследования, app-template-idea §3.2).
Прикладной слой (прототип / minimal_app) реализует нужные и передаёт в ``AppSpec``.

Инвариант яруса: ``app_module`` — только композиция, ноль механизмов; внутри
framework никто его не импортирует (enforce ``.sentrux/rules.toml``).

Сорта хуков (следствие spawn + Dict-at-Boundary; формализованы в Ф5.12):
  - **build-time** (launcher-процесс, до spawn) — обычный callable:
    :class:`BlueprintLoader`, :class:`ProcDictsBuilder`, :class:`StateBootstrap`,
    :class:`ThrottleRules`. Выполняются в родителе; их РЕЗУЛЬТАТ (dict) пиклится
    в ``orchestrator_config`` → потребляется оркестратором child-side.
  - **runtime** (после spawn) — callable НЕ пиклится через spawn, поэтому паттерн
    ``orchestrator_class_path`` (import-path строка + dict, резолв на стороне
    ребёнка): приложение подставляет подкласс ``GenericProcessManagerApp`` и
    переопределяет seam'ы (``_configure_runtime`` / ``apply_topology``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, Mapping, Protocol, runtime_checkable

if TYPE_CHECKING:
    from multiprocess_framework.modules.process_manager_module.launcher.system_launcher import (
        SystemLauncher,
    )

    from .manifest import AppManifest


@runtime_checkable
class BlueprintLoader(Protocol):
    """Build-time хук: манифест → blueprint dict (base ⊕ pipeline, unwrap рецепта).

    Pre:  ``manifest.pipeline`` существует.
    Post: возвращён плоский blueprint dict (``processes``/``wires``/…), Dict-at-Boundary.
    """

    def __call__(self, manifest: "AppManifest") -> Dict[str, Any]: ...


@runtime_checkable
class ProcDictsBuilder(Protocol):
    """Build-time хук: blueprint dict → ``{process_name -> proc_dict}``.

    Universal-шов сборки proc_dict (E3/5.3). Прикладной слой может добавить свою
    нормализацию (per-category defaults) — она инкапсулирована здесь, за швом.

    Pre:  ``blueprint`` — валидный dict-контракт топологии.
    Post: dict готов к ``SystemLauncher.add_process`` (нормализован дефолтами).
    """

    def __call__(self, blueprint: Dict[str, Any]) -> Dict[str, Dict[str, Any]]: ...


@runtime_checkable
class StateBootstrap(Protocol):
    """Build-time хук: blueprint dict → начальное state-дерево (до spawn).

    Опционален: приложение без реактивного state (minimal_app) его не задаёт →
    ``initial_state = {}``.
    """

    def __call__(self, blueprint: Dict[str, Any]) -> Dict[str, Any]: ...


@runtime_checkable
class ThrottleRules(Protocol):
    """Build-time хук: blueprint dict → правила throttle для StateStore (до spawn).

    Опционален: приложение без реактивного state (minimal_app) его не задаёт →
    ThrottleMiddleware не подключается. Результат пиклится в ``orchestrator_config``
    (``state_throttle_rules``) и потребляется оркестратором child-side.
    """

    def __call__(self, blueprint: Dict[str, Any]) -> Dict[str, Any]: ...


@runtime_checkable
class LauncherFactory(Protocol):
    """Escape-hatch: приложение целиком собирает ``SystemLauncher`` само.

    Шов для инкрементальной миграции (прототип): его сложившийся ``build()`` пока
    остаётся источником истины, ``run_app`` оборачивает его generic-контуром
    (env-алиасы, банер из ``manifest.name``). Постепенно приложение переезжает на
    granular-хуки выше.

    Pre:  манифест загружен.
    Post: возвращён сконфигурированный (не запущенный) ``SystemLauncher``.
    """

    def __call__(self, manifest: "AppManifest", pipeline_override: str | None) -> "SystemLauncher": ...


@runtime_checkable
class ManifestStoreProtocol(Protocol):
    """Единственная точка read/write манифеста (закрывает гонку backend↔GUI, NEW-1)."""

    def read_raw(self) -> Dict[str, Any]: ...

    def update(self, updates: Mapping[str, Any]) -> Dict[str, Any]: ...
