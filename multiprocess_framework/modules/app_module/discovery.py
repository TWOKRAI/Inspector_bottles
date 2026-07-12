"""``discover`` — единый helper авто-скана плагинов И сервисов (A6, Ф5.11).

До Ф5.11 плагины сканировались в ДВУХ местах (boot ``launch.py`` + switch
``orchestrator``), а сервисы объявлялись вручную в топологии. Этот helper —
одна точка:

  - **плагины** — рекурсивный поиск ``plugin.py`` (делегируется
    ``PluginRegistry.discover``; ``@register_plugin`` наполняет каталог при импорте);
  - **сервисы** — по маркер-файлу ``service.yaml`` в каталоге сервиса (директива
    владельца 2026-07-11; симметрично ``plugin.py`` / манифесту плагина). Маркер
    парсится в :class:`ServiceManifest` (``name``/``version``/``extras`` — тот же
    ``version+extras``-контракт, что у ``app.yaml`` и манифеста плагина).

Границы слоёв: helper НЕ импортирует Plugins/Services статически — плагины
подгружаются динамически (``importlib`` внутри ``PluginRegistry.discover``), сервисы
читаются как YAML-данные. Framework остаётся независим от прикладных слоёв.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

#: Имя маркер-файла, по которому каталог распознаётся как сервис.
SERVICE_MARKER = "service.yaml"


@dataclass(frozen=True)
class ServiceManifest:
    """Манифест сервиса, прочитанный из маркер-файла ``service.yaml``.

    Attributes:
        name:    Имя сервиса (по умолчанию — имя каталога).
        path:    Каталог сервиса (где лежит ``service.yaml``).
        version: Версия схемы манифеста (задел движка миграций).
        extras:  App/service-специфика pass-through (framework не интерпретирует).
        marker:  Путь к самому ``service.yaml``.
    """

    name: str
    path: Path
    version: int = 1
    extras: dict[str, Any] = field(default_factory=dict)
    marker: Path | None = None


@dataclass
class DiscoveryResult:
    """Результат авто-скана: сколько плагинов зарегистрировано + найденные сервисы.

    Attributes:
        plugins_discovered: Число НОВЫХ плагинов, зарегистрированных этим вызовом
            (``PluginRegistry.discover`` кэширует — повторный скан вернёт 0).
        services:           Найденные сервисы (по маркеру ``service.yaml``).
        failed_imports:     ``module_path -> ошибка`` — плагины, не импортированные
            при скане (снимок ``PluginRegistry.failed_imports``).
    """

    plugins_discovered: int = 0
    services: list[ServiceManifest] = field(default_factory=list)
    failed_imports: dict[str, str] = field(default_factory=dict)

    def service_names(self) -> list[str]:
        return [s.name for s in self.services]


def discover_services(*service_paths: str) -> list[ServiceManifest]:
    """Найти сервисы по маркер-файлу ``service.yaml`` в указанных каталогах.

    Рекурсивно ищет ``service.yaml``; каждый найденный → :class:`ServiceManifest`.
    Битый/пустой маркер — сервис с дефолтами (``name`` = имя каталога), не падаем.

    Args:
        *service_paths: каталоги для поиска (абсолютные или относительные к cwd).

    Returns:
        Список :class:`ServiceManifest`, отсортированный по имени (детерминизм).
    """
    import yaml

    found: list[ServiceManifest] = []
    seen: set[Path] = set()
    for raw_dir in service_paths:
        root = Path(raw_dir).resolve()
        if not root.is_dir():
            continue
        for marker in sorted(root.rglob(SERVICE_MARKER)):
            svc_dir = marker.parent.resolve()
            if svc_dir in seen:
                continue
            seen.add(svc_dir)
            try:
                with open(marker, encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
            except (OSError, yaml.YAMLError):
                data = {}
            found.append(
                ServiceManifest(
                    name=str(data.get("name") or svc_dir.name),
                    path=svc_dir,
                    version=int(data.get("version", 1)),
                    extras=dict(data.get("extras") or {}),
                    marker=marker,
                )
            )
    found.sort(key=lambda s: s.name)
    return found


def discover(
    *,
    plugin_paths: list[str] | tuple[str, ...] = (),
    service_paths: list[str] | tuple[str, ...] = (),
    registry: Any | None = None,
) -> DiscoveryResult:
    """Авто-скан плагинов И сервисов из указанных путей — единый helper (A6).

    Args:
        plugin_paths:  каталоги для поиска ``plugin.py`` (→ ``PluginRegistry.discover``).
        service_paths: каталоги для поиска маркера ``service.yaml``.
        registry:      ``PluginRegistry`` для наполнения; по умолчанию — глобальный
            singleton (тот же, что читает ``SystemBlueprint.check``).

    Returns:
        :class:`DiscoveryResult` — счётчик плагинов + список сервисов + failed_imports.
    """
    if registry is None:
        from multiprocess_framework.modules.process_module.plugins.registry import (
            PluginRegistry,
        )

        registry = PluginRegistry

    plugins_discovered = registry.discover(*plugin_paths) if plugin_paths else 0
    services = discover_services(*service_paths) if service_paths else []
    failed = dict(registry.failed_imports()) if hasattr(registry, "failed_imports") else {}
    return DiscoveryResult(
        plugins_discovered=plugins_discovered,
        services=services,
        failed_imports=failed,
    )
