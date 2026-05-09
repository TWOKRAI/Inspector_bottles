"""Валидация topology и плагинов при старте приложения.

Чистый Python — без Qt зависимостей.
Используется в app.py для диагностики перед инициализацией GUI.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class StartupReport:
    """Результат проверки при старте."""

    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """Нет ошибок (warnings допустимы)."""
        return len(self.errors) == 0

    def summary(self) -> str:
        """Краткая сводка для StatusBar."""
        if self.ok and not self.warnings:
            return ""
        parts = []
        if self.errors:
            parts.append(f"{len(self.errors)} ошибок")
        if self.warnings:
            parts.append(f"{len(self.warnings)} предупреждений")
        return f"Startup: {', '.join(parts)}"


class StartupChecker:
    """Валидатор topology и плагинов при старте.

    Все проверки — non-fatal: приложение запускается даже при ошибках.
    """

    def check_topology(self, topology: dict[str, Any]) -> list[str]:
        """Проверить структуру topology dict.

        Проверки:
        - processes не пуст
        - process_name уникальны
        - chain_targets ссылаются на существующие процессы
        - у каждого процесса есть plugins (list)

        Returns:
            Список строк с описанием найденных проблем.
        """
        issues: list[str] = []

        processes = topology.get("processes")
        if not processes:
            issues.append("Topology пуста: нет процессов")
            return issues

        if not isinstance(processes, list):
            issues.append(f"processes должен быть list, получен {type(processes).__name__}")
            return issues

        # Уникальность имён
        names: list[str] = []
        for proc in processes:
            name = proc.get("process_name", "")
            if not name:
                issues.append("Процесс без process_name")
                continue
            if name in names:
                issues.append(f"Дублирующееся имя процесса: '{name}'")
            names.append(name)

        name_set = set(names)

        # chain_targets и plugins
        for proc in processes:
            pname = proc.get("process_name", "?")
            for target in proc.get("chain_targets", []):
                if target not in name_set:
                    issues.append(
                        f"Процесс '{pname}': chain_target '{target}' не найден в topology"
                    )

            plugins = proc.get("plugins")
            if plugins is None:
                issues.append(f"Процесс '{pname}': отсутствует поле plugins")
            elif not isinstance(plugins, list):
                issues.append(f"Процесс '{pname}': plugins должен быть list")

        return issues

    def check_plugins(
        self,
        registry: Any,
        topology: dict[str, Any],
    ) -> list[str]:
        """Проверить что плагины из topology зарегистрированы в PluginRegistry.

        Args:
            registry: PluginRegistry с методом get_plugin(name) или list_plugins().
            topology: Topology dict.

        Returns:
            Список строк с описанием найденных проблем.
        """
        issues: list[str] = []

        # Получить список зарегистрированных плагинов
        registered: set[str] = set()
        if hasattr(registry, "list_plugins"):
            registered = set(registry.list_plugins())
        elif hasattr(registry, "_registry"):
            registered = set(registry._registry.keys())

        for proc in topology.get("processes", []):
            pname = proc.get("process_name", "?")
            for plugin_cfg in proc.get("plugins", []):
                plugin_name = plugin_cfg.get("plugin_name", "")
                if plugin_name and plugin_name not in registered:
                    issues.append(
                        f"Процесс '{pname}': плагин '{plugin_name}' "
                        f"не найден в PluginRegistry"
                    )

        return issues

    def check_all(
        self,
        topology: dict[str, Any],
        registry: Any = None,
    ) -> StartupReport:
        """Выполнить все проверки.

        Args:
            topology: Topology dict из YAML.
            registry: PluginRegistry (опционально).

        Returns:
            StartupReport с warnings и errors.
        """
        report = StartupReport()

        # Topology проверки → errors
        report.errors.extend(self.check_topology(topology))

        # Plugin проверки → warnings (плагин может быть не нужен GUI)
        if registry is not None:
            report.warnings.extend(self.check_plugins(registry, topology))

        return report
