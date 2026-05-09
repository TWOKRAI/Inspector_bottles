"""ProcessesPresenter — бизнес-логика таба процессов.

Pure Python (без Qt импортов кроме TYPE_CHECKING).
"""
from __future__ import annotations
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from multiprocess_prototype_2.frontend.app_context import AppContext

from .data import ProcessInfo


class ProcessesPresenter:
    """Presenter для ProcessesTab.

    Работает через AppContext: читает topology, шлёт команды, подписывается на state.
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

    def __init__(self, ctx: "AppContext") -> None:
        self._ctx = ctx

    def get_processes(self) -> list[ProcessInfo]:
        """Получить список процессов из topology.

        Читает blueprint через TopologyPresenter или напрямую из config.
        Определяет category по первому плагину каждого процесса.
        """
        processes: list[ProcessInfo] = []

        # Получить topology данные из AppContext
        # AppContext может содержать topology в config или extras
        topology_data = self._ctx.config.get("topology", {})
        raw_processes = topology_data.get("processes", [])

        # Если topology не в config, пробуем extras
        if not raw_processes:
            topo = self._ctx.extras.get("topology", {})
            raw_processes = topo.get("processes", []) if isinstance(topo, dict) else []

        registry = self._ctx.plugin_registry()

        for proc_dict in raw_processes:
            if isinstance(proc_dict, dict):
                name = proc_dict.get("process_name", "unnamed")
                plugins_list = proc_dict.get("plugins", [])
                plugin_names: list[str] = []
                category = "utility"

                for p in plugins_list:
                    pname = p.get("plugin_name", "") if isinstance(p, dict) else ""
                    if pname:
                        plugin_names.append(pname)
                        # Определяем category по первому плагину
                        if category == "utility" and registry:
                            entry = registry.get(pname)
                            if entry and hasattr(entry, "category"):
                                category = entry.category

                processes.append(ProcessInfo(
                    name=name,
                    category=category,
                    plugins=plugin_names,
                ))
            else:
                # Если proc_dict — это Pydantic модель (ProcessConfig)
                name = getattr(proc_dict, "process_name", "unnamed")
                plugins = getattr(proc_dict, "plugins", [])
                plugin_names = []
                category = "utility"

                for p in plugins:
                    pname = (
                        p.get("plugin_name", "") if isinstance(p, dict)
                        else getattr(p, "plugin_name", "")
                    )
                    if pname:
                        plugin_names.append(pname)
                        if category == "utility" and registry:
                            entry = registry.get(pname)
                            if entry and hasattr(entry, "category"):
                                category = entry.category

                processes.append(ProcessInfo(
                    name=name,
                    category=category,
                    plugins=plugin_names,
                ))

        return processes

    def on_process_action(self, process_name: str, action_id: str) -> None:
        """Обработать действие пользователя (Start/Stop/Restart).

        Phase 12: если TopologyBridge доступен — использует его
        (валидация + маршрутизация). Иначе — прямой CommandSender.
        """
        bridge = self._ctx.extras.get("topology_bridge")

        if bridge is not None:
            bridge_methods = {
                "start": bridge.start_process,
                "stop": bridge.stop_process,
                "restart": bridge.restart_process,
            }
            method = bridge_methods.get(action_id)
            if method is not None:
                method(process_name)
                return

        # Fallback: прямой CommandSender (обратная совместимость)
        cmd_map = {
            "start": "process.start",
            "stop": "process.stop",
            "restart": "process.restart",
        }
        command = cmd_map.get(action_id, action_id)
        self._ctx.command_sender.send_command(process_name, command, {})

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
            "active": 0,        # обновляется через state_delta
            "broken_wires": 0,  # обновляется через WireStatusMonitor
            "avg_fps": 0.0,     # обновляется через state_delta
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

    def get_process_names(self) -> list[str]:
        """Упорядоченный список имён процессов для навигации."""
        return [p.name for p in self.get_processes()]

    def get_table_rows(self) -> list[dict[str, str]]:
        """Плоские данные всех процессов для таблицы."""
        rows: list[dict[str, str]] = []
        for proc in self.get_processes():
            rows.append({
                "Имя": proc.name,
                "Категория": self.category_title(proc.category),
                "Статус": proc.status,
                "FPS": f"{proc.fps:.1f}" if proc.fps else "—",
                "Плагины": ", ".join(proc.plugins) or "—",
            })
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
