"""ProcessesPresenter — бизнес-логика таба процессов.

Task E.2: мигрирован на AppServices DI. Принимает services: AppServices.
topology читается через services.topology.load() (TopologyRepository Protocol),
category — через services.plugins.resolve() (PluginCatalog Protocol).

command_sender и topology_bridge — runtime IPC, не покрыты AppServices Protocol'ами
(live runtime — Phase G aggregate). Передаются отдельными параметрами как bridge.

Pure Python (без Qt импортов кроме TYPE_CHECKING).
"""

from __future__ import annotations
from typing import TYPE_CHECKING, Any

from multiprocess_prototype.domain.app_services import AppServices

if TYPE_CHECKING:
    from multiprocess_prototype.frontend.bridge.command_sender import CommandSender
    from multiprocess_prototype.frontend.bridge.topology_bridge import TopologyBridge

from .data import ProcessInfo


class ProcessesPresenter:
    """Presenter для ProcessesTab.

    Читает topology через services.topology (read-only consumer),
    шлёт команды управления через topology_bridge (предпочтительно) или
    command_sender (fallback) — оба runtime-зависимости вне scope AppServices.
    """

    # Маппинг категорий → русские названия
    CATEGORY_TITLES: dict[str, str] = {
        "source": "Источники",
        "processing": "Обработка",
        "output": "Вывод",
        "rendering": "Рендеринг",
        "control": "Управление",
        "utility": "Утилиты",
        "service": "Сервисы",
    }

    def __init__(
        self,
        services: AppServices,
        *,
        command_sender: "CommandSender | None" = None,
        topology_bridge: "TopologyBridge | None" = None,
    ) -> None:
        self._services = services
        # TODO Phase G: command_sender / topology_bridge — live-runtime IPC,
        # вынести в отдельный runtime-aggregate (см. Out of scope Phase E).
        self._command_sender = command_sender
        self._topology_bridge = topology_bridge

    def get_processes(self) -> list[ProcessInfo]:
        """Получить список процессов из topology.

        Читает domain.Topology через services.topology.load() (read-only).
        Определяет category по первому плагину через services.plugins.resolve().
        """
        topology = self._services.topology.load()
        catalog = self._services.plugins
        processes: list[ProcessInfo] = []

        for proc in topology.processes:
            plugin_names: list[str] = []
            category = "utility"

            for plugin in proc.plugins:
                pname = plugin.plugin_name
                if not pname:
                    continue
                plugin_names.append(pname)
                # Категория процесса — по первому плагину, который реестр знает.
                if category == "utility":
                    spec = catalog.resolve(pname)
                    if spec is not None and spec.category:
                        category = spec.category

            processes.append(
                ProcessInfo(
                    name=proc.process_name,
                    category=category,
                    plugins=plugin_names,
                    protected=proc.protected,
                )
            )

        return processes

    def on_process_action(self, process_name: str, action_id: str) -> None:
        """Обработать действие пользователя (Start/Stop/Restart).

        Phase 12: если TopologyBridge доступен — использует его
        (валидация + маршрутизация). Иначе — прямой CommandSender.
        """
        bridge = self._topology_bridge

        if bridge is not None:
            bridge_methods: dict[str, Any] = {
                "start": bridge.start_process,
                "stop": bridge.stop_process,
                "restart": bridge.restart_process,
            }
            method = bridge_methods.get(action_id)
            if method is not None:
                method(process_name)
                return

        # Fallback: прямой CommandSender (обратная совместимость)
        if self._command_sender is None:
            return
        cmd_map = {
            "start": "process.start",
            "stop": "process.stop",
            "restart": "process.restart",
        }
        command = cmd_map.get(action_id, action_id)
        self._command_sender.send_command(process_name, command, {})

    def get_health_summary(self) -> dict[str, Any]:
        """Сводка здоровья системы.

        Returns:
            dict с ключами: total, active, broken_wires, avg_fps.
            Все значения — начальные (обновляются через bindings).
        """
        processes = self.get_processes()
        total = len(processes)

        # Начальные значения — будут обновляться через bindings
        return {
            "total": total,
            "active": 0,  # обновляется через state_delta
            "broken_wires": 0,  # обновляется через WireStatusMonitor
            "avg_fps": 0.0,  # обновляется через state_delta
        }

    def group_by_category(self, processes: list[ProcessInfo]) -> dict[str, list[ProcessInfo]]:
        """Группировать процессы по категории."""
        groups: dict[str, list[ProcessInfo]] = {}
        for proc in processes:
            groups.setdefault(proc.category, []).append(proc)
        return groups

    def category_title(self, category: str) -> str:
        """Русское название категории."""
        return self.CATEGORY_TITLES.get(category, category.capitalize())

    def get_process_by_name(self, name: str) -> ProcessInfo | None:
        """Найти процесс по имени."""
        for proc in self.get_processes():
            if proc.name == name:
                return proc
        return None

    def is_protected(self, name: str) -> bool:
        """Проверить, является ли процесс защищённым."""
        proc = self.get_process_by_name(name)
        return bool(proc.protected) if proc else False

    def get_process_names(self) -> list[str]:
        """Упорядоченный список имён процессов для навигации."""
        return [p.name for p in self.get_processes()]

    def get_table_rows(self) -> list[dict[str, str]]:
        """Плоские данные всех процессов для таблицы."""
        rows: list[dict[str, str]] = []
        for proc in self.get_processes():
            rows.append(
                {
                    "Имя": proc.name,
                    "Категория": self.category_title(proc.category),
                    "Статус": proc.status,
                    "FPS": f"{proc.fps:.1f}" if proc.fps else "—",
                    "Плагины": ", ".join(proc.plugins) or "—",
                }
            )
        return rows

    def get_detail_metrics(self, name: str) -> dict[str, str]:
        """Полные метрики одного процесса для детальной карточки."""
        proc = self.get_process_by_name(name)
        if not proc:
            return {}
        return {
            "Категория": self.category_title(proc.category),
            "Статус": proc.status,
            "PID": str(proc.pid) if proc.pid else "—",
            "FPS": f"{proc.fps:.1f}" if proc.fps else "—",
            "Кадры": str(proc.frame_count) if proc.frame_count else "—",
            "Плагины": ", ".join(proc.plugins) or "—",
        }
