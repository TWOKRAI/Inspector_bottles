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
from multiprocess_prototype.domain.entities import Process, WorkerSpec
from multiprocess_prototype.frontend.bridge.worker_bridge import WorkerBridge

if TYPE_CHECKING:
    from multiprocess_prototype.frontend.bridge.command_sender import CommandSender
    from multiprocess_prototype.frontend.bridge.topology_bridge import TopologyBridge

from .data import (  # noqa: F401  (реэкспорт констант для обратной совместимости)
    DEFAULT_MAIN_WORKER,
    WORKER_EXECUTION_MODES,
    WORKER_PRIORITIES,
    ProcessInfo,
)


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
        # Мост CRUD воркеров (live-IPC в процесс-владелец). None-safe.
        self._worker_bridge = WorkerBridge(command_sender)

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

        # Fallback: прямой CommandSender (обратная совместимость).
        # process.* — команды ProcessManager, шлём системным конвертом (НЕ в процесс).
        if self._command_sender is None:
            return
        cmd_map = {
            "start": "process.start",
            "stop": "process.stop",
            "restart": "process.restart",
        }
        command = cmd_map.get(action_id, action_id)
        self._command_sender.send_system_command({"cmd": command, "process_name": process_name})

    # ---- Телеметрия: управляемая публикация (telemetry-publish-control Ф4.1) ----

    @staticmethod
    def telemetry_command(
        process_name: str,
        metric: str,
        *,
        enabled: bool | None = None,
        interval_sec: float | None = None,
    ) -> dict[str, Any]:
        """Построить system-конверт `telemetry.broadcast` для ОДНОЙ метрики (pure).

        Точечная правка publisher-gate одного процесса: `mode="merge"` (соседние
        метрики не тронуты), `target=process_name` (адресно через PM — cap-детекция
        на per-process пути, Task 1.4). ``None``-ось (enabled/interval) не кладётся в
        rule — меняется ровно то, что дёрнул пользователь. Форма publish идентична
        `BackendDriver.telemetry_set`: `{"metrics": {metric: {enabled?, interval_sec?}}}`.
        """
        rule: dict[str, Any] = {}
        if enabled is not None:
            rule["enabled"] = bool(enabled)
        if interval_sec is not None:
            rule["interval_sec"] = float(interval_sec)
        return {
            "cmd": "telemetry.broadcast",
            "publish": {"metrics": {metric: rule}},
            "telemetry_mode": "merge",
            "target": process_name,
        }

    def apply_telemetry_metric(
        self,
        process_name: str,
        metric: str,
        *,
        enabled: bool | None = None,
        interval_sec: float | None = None,
    ) -> dict[str, Any]:
        """Применить правку метрики через command-result-bridge (БЛОКИРУЮЩИЙ).

        Зовётся с worker-потока RequestRunner'а (не из Qt main — иначе фриз, запрещено
        планом): `request_system_command` ждёт ответ PM. Результат несёт охват
        (`reached`) и `capped_by_throttle` (Task 1.4) — владелец покажет их в UI.
        """
        if self._command_sender is None:
            return {"success": False, "error": "command_sender недоступен"}
        command = self.telemetry_command(process_name, metric, enabled=enabled, interval_sec=interval_sec)
        return self._command_sender.request_system_command(command)

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
                    "Циклов/с": f"{proc.fps:.1f}" if proc.fps else "—",
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
            "Циклов/с": f"{proc.fps:.1f}" if proc.fps else "—",
            "Uptime": "—",  # live через StateStore (processes.{name}.state.uptime)
            "Кадры": str(proc.frame_count) if proc.frame_count else "—",
            "Плагины": ", ".join(proc.plugins) or "—",
        }

    # ------------------------------------------------------------------ #
    #  Workers — read (config) — dict at boundary для GUI                 #
    # ------------------------------------------------------------------ #

    def get_workers(self, process_name: str) -> list[dict[str, Any]]:
        """Список воркеров процесса как dict'ы (GUI работает с dict, не SchemaBase).

        Если у процесса нет своего message_processor — добавляем синтетический
        protected-воркер первым (он всегда крутится в рантайме, но в конфиге
        топологии не персистится — это lifeline процесса, не артефакт настройки).
        """
        proc = self._find_domain_process(process_name)
        specs = list(proc.workers) if proc else []
        rows: list[dict[str, Any]] = []
        if not any(s.worker_name == DEFAULT_MAIN_WORKER for s in specs):
            rows.append(
                {
                    "worker_name": DEFAULT_MAIN_WORKER,
                    "priority": "NORMAL",
                    "execution_mode": "loop",
                    "target_interval_ms": None,
                    "worker_class": None,
                    "protected": True,
                    "description": "Системный воркер IPC (RouterManager polling)",
                    "config": {},
                }
            )
        rows.extend(s.to_dict() for s in specs)
        return rows

    def is_worker_protected(self, process_name: str, worker_name: str) -> bool:
        """Защищён ли воркер от удаления/настройки (message_processor или WorkerSpec.protected)."""
        if worker_name == DEFAULT_MAIN_WORKER:
            return True
        proc = self._find_domain_process(process_name)
        if proc is None:
            return False
        for spec in proc.workers:
            if spec.worker_name == worker_name:
                return bool(spec.protected)
        return False

    # ------------------------------------------------------------------ #
    #  Workers — mutate (config persist + live IPC)                       #
    # ------------------------------------------------------------------ #

    def add_worker(
        self,
        process_name: str,
        *,
        worker_name: str,
        priority: str = "NORMAL",
        execution_mode: str = "loop",
        target_interval_ms: int | None = None,
    ) -> bool:
        """Добавить воркер: персист в топологию + live-IPC спавн в живой процесс."""
        worker_name = worker_name.strip()
        if not worker_name or worker_name == DEFAULT_MAIN_WORKER:
            return False
        proc = self._find_domain_process(process_name)
        if proc is not None and any(w.worker_name == worker_name for w in proc.workers):
            return False  # дубликат

        spec = WorkerSpec(
            worker_name=worker_name,
            priority=priority,  # type: ignore[arg-type]
            execution_mode=execution_mode,  # type: ignore[arg-type]
            target_interval_ms=target_interval_ms,
        )
        self._mutate_process_workers(process_name, lambda ws: ws + (spec,))
        self._worker_bridge.worker_create(
            process_name,
            worker_name=worker_name,
            priority=priority,
            execution_mode=execution_mode,
            target_interval_ms=target_interval_ms,
        )
        return True

    def remove_worker(self, process_name: str, worker_name: str) -> bool:
        """Удалить воркер: персист в топологию + live-IPC remove. Protected — запрет."""
        if self.is_worker_protected(process_name, worker_name):
            return False
        self._mutate_process_workers(
            process_name,
            lambda ws: tuple(w for w in ws if w.worker_name != worker_name),
        )
        self._worker_bridge.worker_remove(process_name, worker_name)
        return True

    def update_worker(
        self,
        process_name: str,
        worker_name: str,
        *,
        priority: str | None = None,
        execution_mode: str | None = None,
        target_interval_ms: int | None = None,
    ) -> bool:
        """Перенастроить воркер: персист (model_copy) + live-IPC update. Protected — запрет."""
        if self.is_worker_protected(process_name, worker_name):
            return False
        updates: dict[str, Any] = {}
        if priority is not None:
            updates["priority"] = priority
        if execution_mode is not None:
            updates["execution_mode"] = execution_mode
        if target_interval_ms is not None:
            updates["target_interval_ms"] = target_interval_ms
        if not updates:
            return False

        def _apply(ws: tuple[WorkerSpec, ...]) -> tuple[WorkerSpec, ...]:
            return tuple(w.model_copy(update=updates) if w.worker_name == worker_name else w for w in ws)

        self._mutate_process_workers(process_name, _apply)
        self._worker_bridge.worker_update(
            process_name,
            worker_name,
            priority=priority,
            execution_mode=execution_mode,
            target_interval_ms=target_interval_ms,
        )
        return True

    # ------------------------------------------------------------------ #
    #  Workers — lifecycle (live-IPC, без правки топологии)               #
    # ------------------------------------------------------------------ #

    def start_worker(self, process_name: str, worker_name: str) -> bool:
        """Запустить остановленный воркер (live-IPC, без пересоздания).

        Старт безопасен — protected-проверка не нужна. Конфиг не меняется.
        """
        if not worker_name:
            return False
        return self._worker_bridge.worker_start(process_name, worker_name)

    def stop_worker(self, process_name: str, worker_name: str) -> bool:
        """Остановить воркер (live-IPC, без удаления). Protected — запрет."""
        if self.is_worker_protected(process_name, worker_name):
            return False
        return self._worker_bridge.worker_stop(process_name, worker_name)

    def restart_worker(self, process_name: str, worker_name: str) -> bool:
        """Перезапустить воркер (live-IPC). Protected — запрет."""
        if self.is_worker_protected(process_name, worker_name):
            return False
        return self._worker_bridge.worker_restart(process_name, worker_name)

    # ------------------------------------------------------------------ #
    #  Processes — create / delete (config persist + live для delete)     #
    # ------------------------------------------------------------------ #

    def create_process(self, name: str, category: str | None = None) -> bool:
        """Создать процесс-контейнер: персист в топологию (запуск — при launch рецепта).

        Пустой процесс (без плагинов) не hot_add'ится в рантайм сразу — ему нечего
        исполнять; он становится живым при следующем launch активного рецепта.
        Воркеры можно добавлять в УЖЕ работающие процессы (live-IPC).
        """
        name = name.strip()
        if not name:
            return False
        topology = self._services.topology.load()
        if topology.find_process(name) is not None:
            return False
        new_proc = Process(process_name=name, category=category)
        new_topo = topology.model_copy(update={"processes": topology.processes + (new_proc,)})
        self._services.topology.save(new_topo)
        return True

    def delete_process(self, name: str) -> bool:
        """Удалить процесс: персист (remove из топологии) + live hot_remove. Protected — запрет."""
        if self.is_protected(name):
            return False
        topology = self._services.topology.load()
        if topology.find_process(name) is None:
            return False
        new_procs = tuple(p for p in topology.processes if p.process_name != name)
        new_topo = topology.model_copy(update={"processes": new_procs})
        self._services.topology.save(new_topo)
        if self._topology_bridge is not None:
            try:
                self._topology_bridge.hot_remove_process(name)
            except Exception:  # nosec B110 — рантайм может быть недоступен, конфиг уже сохранён
                pass
        return True

    # ------------------------------------------------------------------ #
    #  Internal                                                            #
    # ------------------------------------------------------------------ #

    def _find_domain_process(self, process_name: str) -> Process | None:
        """Найти domain.Process в текущей топологии."""
        return self._services.topology.load().find_process(process_name)

    def _mutate_process_workers(
        self,
        process_name: str,
        fn: "Any",
    ) -> None:
        """Пересобрать workers процесса через fn(workers)->workers и сохранить топологию.

        Process и Topology — frozen, поэтому пересборка через model_copy.
        save() публикует TopologyReplaced → все вкладки реагируют.
        """
        topology = self._services.topology.load()
        changed = False
        new_procs: list[Process] = []
        for proc in topology.processes:
            if proc.process_name == process_name:
                proc = proc.model_copy(update={"workers": tuple(fn(proc.workers))})
                changed = True
            new_procs.append(proc)
        if not changed:
            return
        new_topo = topology.model_copy(update={"processes": tuple(new_procs)})
        self._services.topology.save(new_topo)
