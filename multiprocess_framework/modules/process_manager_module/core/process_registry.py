"""
ProcessRegistry — реестр процессов ОС + lifecycle + создание.

Per-process stop_event: остановка одного процесса не трогает остальные.
"""

import time
from typing import Any, Dict, List, Optional

from multiprocessing import Event, Process

from .bundle_contract import build_bundle
from ..runner import run_process_function


class ProcessRegistry:
    """Реестр процессов ОС: хранение + lifecycle + создание."""

    def __init__(
        self,
        logger=None,
        queue_registry=None,
        config_manager=None,
        shared_resources=None,
        system_stop_event: Optional[Event] = None,
    ) -> None:
        self.logger = logger
        self.queue_registry = queue_registry
        self.config_manager = config_manager
        self.shared_resources = shared_resources
        self.os_processes: List[Process] = []
        self._stop_events: Dict[str, Event] = {}
        # ОБЩИЙ system-wide stop: кладётся в bundle КАЖДОГО ребёнка → его lifecycle
        # наблюдает общий event наравне со своим per-process stop_event.
        self._system_stop_event: Optional[Event] = system_stop_event

    def add_process(self, process: Process) -> None:
        self.os_processes.append(process)

    def get_process_by_name(self, name: str) -> Optional[Process]:
        for p in self.os_processes:
            if p.name == name:
                return p
        return None

    def remove_process(self, name: str) -> None:
        self.os_processes = [p for p in self.os_processes if p.name != name]
        self._stop_events.pop(name, None)

    def _create_process(
        self,
        name: str,
        class_path: str,
        config: Dict[str, Any],
        priority: str,
        stop_event: Event,
    ) -> Optional[Process]:
        try:
            if self.logger:
                self.logger._log_info(f"Creating process '{name}' from '{class_path}'")

            process_config = dict(config or {})
            process_config["name"] = name
            process_config["class"] = class_path

            if self.config_manager:
                try:
                    process_config_obj = self.config_manager.get_config("processes")
                    if process_config_obj:
                        processes_dict = process_config_obj.data.copy()
                        processes_dict[name] = process_config
                        process_config_obj.data.update(processes_dict)
                    else:
                        self.config_manager.create_config("processes", {name: process_config})
                except Exception as e:
                    if self.logger:
                        self.logger._log_error(f"ConfigManager update failed for '{name}': {e}")

            if self.queue_registry and not self.queue_registry.get_process_queues(name):
                queue_config = process_config.get("queues", {})
                self.queue_registry.create_and_register_queues(name, queue_config)

            queues = self.queue_registry.get_process_queues(name) if self.queue_registry else {}
            routing_map: Dict[str, Any] = {}
            if self.queue_registry:
                for pname in self.queue_registry.get_registered_processes():
                    routing_map[pname] = self.queue_registry.get_process_queues(pname)
            process_data = self.shared_resources.get_process_data(name) if self.shared_resources else None
            custom = dict(process_data.custom) if process_data and process_data.custom else {}
            custom.setdefault("process_config", process_config)
            # Сырые Event/менеджеры НЕ кладём в bundle custom: custom регистрируется в
            # process_state_registry и сериализуется через Queue внутри
            # _build_shared_resources_from_bundle (у детей есть очереди с feeder-потоками).
            # mp.Event/Condition на Windows-spawn пиклится только через inheritance →
            # иначе RuntimeError "should only be shared ... through inheritance".
            # system_stop_event передаётся отдельным Process-аргументом (см. ниже).
            for key in ("stop_event", "error_manager", "pause_event", "system_ready_event", "system_stop_event"):
                custom.pop(key, None)

            all_process_memory: Dict[str, Dict[str, Any]] = {}
            if self.shared_resources:
                for pname in self.shared_resources.get_process_names():
                    pd = self.shared_resources.get_process_data(pname)
                    if pd and pd.custom and pd.custom.get("memory_names"):
                        mem = {
                            k: v
                            for k, v in pd.custom.items()
                            if k
                            in (
                                "memory_names",
                                "memory_params",
                                "memory_index_usage",
                                "memory_coll",
                            )
                        }
                        if mem:
                            all_process_memory[pname] = mem
            custom["_all_process_memory"] = all_process_memory

            bundle = build_bundle(
                queues=queues,
                config=process_config,
                custom=custom,
                routing_map=routing_map,
            )

            process = Process(
                target=run_process_function,
                # system_stop_event — отдельным аргументом (inheritance), НЕ в bundle custom.
                args=(class_path, name, stop_event, bundle, self._system_stop_event),
                name=name,
            )
            if self.logger:
                self.logger._log_info(f"Process '{name}' created (priority: {priority})")
            return process
        except Exception as e:
            if self.logger:
                self.logger._log_error(f"Failed to create process '{name}': {e}")
            import traceback

            traceback.print_exc()
            return None

    def create_and_register(
        self,
        name: str,
        class_path: str,
        config: Optional[Dict[str, Any]] = None,
        priority: str = "normal",
    ) -> Optional[Process]:
        process_stop_event = Event()
        self._stop_events[name] = process_stop_event
        process = self._create_process(name, class_path, config or {}, priority, process_stop_event)
        if process:
            self.add_process(process)
        else:
            self._stop_events.pop(name, None)
        return process

    def start_all(self) -> None:
        if self.logger:
            self.logger._log_info("Starting all processes...")
        for process in self.os_processes:
            try:
                process.start()
                if self.logger:
                    self.logger._log_info(f"Started OS process: {process.name} (PID: {process.pid})")
            except Exception as e:
                if self.logger:
                    self.logger._log_error(f"Failed to start process {process.name}: {e}")

    def stop_one(self, name: str, timeout: float = 5.0) -> bool:
        """Остановить один процесс с подтверждением смерти («ensure stopped»).

        Идемпотентная семантика: процесса нет в реестре или он не жив —
        уже остановлен → ``True``. Иначе эскалация stop_event → join(timeout)
        → terminate → kill; после kill финальный join. Результат — ФАКТ
        смерти (``not is_alive()``), а не «сигнал подан»: cleanup/unlink SHM
        безопасен только по подтверждённой остановке.
        """
        process = self.get_process_by_name(name)
        if process is None:
            if self.logger:
                self.logger._log_info(f"stop_one('{name}'): нет в реестре — считается остановленным")
            return True
        if not process.is_alive():
            return True

        if self.logger:
            self.logger._log_info(f"Stopping process '{name}' (timeout={timeout}s)...")
        ev = self._stop_events.get(name)
        if ev is not None:
            ev.set()
            process.join(timeout=timeout)
        elif self.logger:
            self.logger._log_warning(f"stop_one('{name}'): нет stop_event — сразу terminate")

        if process.is_alive():
            if self.logger:
                self.logger._log_warning(f"Process '{name}' did not stop in {timeout}s, terminating...")
            try:
                process.terminate()
            except Exception as e:
                if self.logger:
                    self.logger._log_warning(f"Error terminating '{name}': {e}")
            process.join(timeout=1.0)

        if process.is_alive():
            if self.logger:
                self.logger._log_error(f"Force killing process '{name}'")
            try:
                process.kill()
            except Exception as e:
                if self.logger:
                    self.logger._log_error(f"Error killing '{name}': {e}")
            # Финальный join: подтвердить смерть ДО того, как caller начнёт cleanup
            process.join(timeout=1.0)

        alive = process.is_alive()
        if alive and self.logger:
            self.logger._log_error(f"Process '{name}' всё ещё жив после kill — остановка НЕ подтверждена")
        return not alive

    def stop_many(self, names: List[str], timeout: float = 5.0) -> Dict[str, bool]:
        """Остановить НЕСКОЛЬКО процессов ПАРАЛЛЕЛЬНО (один общий дедлайн).

        В отличие от ``stop_one`` в цикле (N×timeout ≈ 35с для 7 процессов),
        взводит все ``stop_event`` разом, затем ждёт graceful-выхода с ОБЩИМ
        дедлайном ``time.monotonic()+timeout`` → суммарно ~timeout. Стрэгглеры —
        ``terminate`` → ``kill`` (тоже параллельно). Паттерн ``stop_all``/``_join_all``,
        доведённый до hot-swap (``replace_blueprint``).

        Args:
            names: имена процессов для остановки.
            timeout: общий дедлайн graceful-остановки (секунды).

        Returns:
            Карта ``{name: stopped}`` — семантика «ensure stopped»:
            ``True`` — процесса нет в реестре / он не был жив (идемпотентно:
            «нечего останавливать» — успех) ИЛИ смерть ПОДТВЕРЖДЕНА
            (graceful/terminate/kill + финальный join);
            ``False`` — процесс всё ещё жив после полной эскалации
            (cleanup для него небезопасен).
        """
        result: Dict[str, bool] = {}
        procs: Dict[str, Process] = {}

        # (a) Взвести все stop_event разом — дети гаснут параллельно.
        #     Нет в реестре / уже мёртв → True: идемпотентность (паритет
        #     PM.stop_process), иначе «призрак» в конфигах валил бы весь switch.
        for name in names:
            process = self.get_process_by_name(name)
            if process is None:
                if self.logger:
                    self.logger._log_info(f"stop_many: '{name}' нет в реестре — считается остановленным")
                result[name] = True
                continue
            if not process.is_alive():
                result[name] = True
                continue
            ev = self._stop_events.get(name)
            if ev is not None:
                ev.set()
            elif self.logger:
                self.logger._log_warning(f"stop_many: у '{name}' нет stop_event — только terminate/kill")
            procs[name] = process

        if not procs:
            return result

        if self.logger:
            self.logger._log_info(f"Stopping {len(procs)} processes in parallel (timeout={timeout}s): {list(procs)}")

        # (b) Один общий дедлайн на graceful-выход всех
        deadline = time.monotonic() + timeout
        for process in procs.values():
            if process.is_alive():
                process.join(timeout=max(0.0, deadline - time.monotonic()))

        # (c) Terminate стрэгглеров (тоже разом), затем общий короткий join
        stragglers = [p for p in procs.values() if p.is_alive()]
        for process in stragglers:
            if self.logger:
                self.logger._log_warning(f"Process '{process.name}' did not stop in {timeout}s, terminating...")
            try:
                process.terminate()
            except Exception as e:
                if self.logger:
                    self.logger._log_warning(f"Error terminating '{process.name}': {e}")
        if stragglers:
            term_deadline = time.monotonic() + 1.0
            for process in stragglers:
                if process.is_alive():
                    process.join(timeout=max(0.0, term_deadline - time.monotonic()))

        # (d) Kill оставшихся + финальный join (подтверждение смерти)
        killed = [p for p in procs.values() if p.is_alive()]
        for process in killed:
            if self.logger:
                self.logger._log_error(f"Force killing process '{process.name}'")
            try:
                process.kill()
            except Exception as e:
                if self.logger:
                    self.logger._log_error(f"Error killing '{process.name}': {e}")
        if killed:
            kill_deadline = time.monotonic() + 1.0
            for process in killed:
                if process.is_alive():
                    process.join(timeout=max(0.0, kill_deadline - time.monotonic()))

        # (e) Результат — по ФАКТУ смерти, а не по «сигнал подан»
        for name, process in procs.items():
            alive = process.is_alive()
            result[name] = not alive
            if alive and self.logger:
                self.logger._log_error(f"stop_many: '{name}' всё ещё жив после kill — остановка НЕ подтверждена")

        return result

    def stop_all(self, timeout: float = 5.0) -> None:
        if self.logger:
            self.logger._log_info(f"Stopping all processes (timeout={timeout}s)...")
        for ev in self._stop_events.values():
            ev.set()
        self._join_all(timeout)

        for process in self.os_processes:
            if process.is_alive():
                if self.logger:
                    self.logger._log_warning(f"Process '{process.name}' did not stop in {timeout}s, terminating...")
                try:
                    process.terminate()
                    process.join(timeout=1.0)
                except Exception as e:
                    if self.logger:
                        self.logger._log_warning(f"Error terminating '{process.name}': {e}")

        for process in self.os_processes:
            if process.is_alive():
                if self.logger:
                    self.logger._log_error(f"Force killing process '{process.name}'")
                try:
                    process.kill()
                except Exception as e:
                    if self.logger:
                        self.logger._log_error(f"Error killing '{process.name}': {e}")

        if self.logger:
            self.logger._log_info("All processes stopped")

    def _join_all(self, timeout: float = 5.0) -> None:
        # ОБЩИЙ дедлайн на все процессы: stop_event'ы уже взведены (stop_all +
        # общий system_stop_event), дети гаснут ПАРАЛЛЕЛЬНО → ждём суммарно ~timeout,
        # а не N×timeout. Раньше join(timeout) на каждого по очереди давал 7×5с≈35с.
        deadline = time.monotonic() + timeout
        for process in self.os_processes:
            if process.is_alive():
                if self.logger:
                    self.logger._log_info(f"Waiting for process '{process.name}' (timeout={timeout}s)...")
                process.join(timeout=max(0.0, deadline - time.monotonic()))
                if process.is_alive() and self.logger:
                    self.logger._log_warning(f"Process '{process.name}' still alive after join")
