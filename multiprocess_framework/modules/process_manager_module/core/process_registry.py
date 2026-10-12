"""
ProcessRegistry — реестр процессов ОС + lifecycle + создание.

Per-process stop_event: остановка одного процесса не трогает остальные.
"""

import math
import os
import threading
from typing import Any, Callable, Dict, List, Optional

from multiprocessing import Event, Process, RawArray

from .bundle_contract import build_bundle
from .child_process_stop import ChildProcessStop
from .stop_budget import DEFAULT_SHUTDOWN_TIMEOUT_S, KILL_RESERVE_S
from ..runner import run_process_function
from ...base_manager import open_scope
from ...shared_resources_module.queues.core.reader_gone import set_reader_gone

# Окна эскалации стопа детей (STOP_POLL_S, TERMINATE_GRACE_S, KILL_CONFIRM_S) и формула
# бюджета живут в ``core/stop_budget.py`` (Task 1.1, ADR-PMM-035): реестр, спавнер и
# ребёнок читают одни числа.


class ProcessRegistry:
    """Реестр процессов ОС: хранение + lifecycle + создание."""

    def __init__(
        self,
        logger=None,
        queue_registry=None,
        config_manager=None,
        shared_resources=None,
        system_stop_event: Optional[Event] = None,
        routing_meta_fn: Optional[Callable[[], Dict[str, Any]]] = None,
        system_ready_event: Optional[Event] = None,
        child_stop_budget: Optional[Dict[str, float]] = None,
    ) -> None:
        self.logger = logger
        # Task 1.1 (ADR-PMM-035): словарь ``stop_budget(shutdown_timeout PM)`` — каждый ребёнок
        # получает его копию в конфиге под ключом ``stop_budget`` (явный ключ процесса сильнее).
        # Только числа: объекты стопа не пиклятся и в конфиг не едут.
        self._child_stop_budget: Optional[Dict[str, float]] = (
            dict(child_stop_budget) if child_stop_budget is not None else None
        )
        self.queue_registry = queue_registry
        self.config_manager = config_manager
        self.shared_resources = shared_resources
        self.os_processes: List[Process] = []
        self._stop_events: Dict[str, Event] = {}
        # Ф3.2 (self-reported ready): per-process mp.Event готовности. PM создаёт
        # event при спавне, кладёт его в bundle custom (inheritance при spawn, как
        # stop_event) и хранит ссылку у себя. Ребёнок ставит event сразу после
        # успешного initialize() → барьер PM видит готовность НЕМЕДЛЕННО, не
        # message-loop'ом (дедлок message_processor исключён). См. DECISIONS.md.
        self._ready_events: Dict[str, Event] = {}
        # Task 1.6 (ADR-PMM-033): слот разделяемой памяти на ВОПЛОЩЕНИЕ — итог хука
        # выхода ребёнка (release_queues_at_exit) для PM. Свежий на каждый (пере)спавн,
        # как и ready_event: старый инстанс не может подложить отчёт новому.
        self._exit_reports: Dict[str, Any] = {}
        # ОБЩИЙ system-wide stop: кладётся в bundle КАЖДОГО ребёнка → его lifecycle
        # наблюдает общий event наравне со своим per-process stop_event.
        self._system_stop_event: Optional[Event] = system_stop_event
        # Task 5.4 (ADR-PMM-034): событие готовности системы — его взводит ТОЛЬКО PM
        # (_announce_ready). Ребёнок получает то же событие и только читает: источники
        # (SourceProducer) ждут его перед первым produce(). Едет Process-kwargs
        # (inheritance при spawn), не в bundle custom и не позиционно.
        self._system_ready_event: Optional[Event] = system_ready_event
        # Ф3.1 (routing-epoch): поставщик routing_meta для bundle нового ребёнка
        # ({"epoch": N, "incarnations": {...}}). None → пустой meta (совместимость).
        self._routing_meta_fn: Optional[Callable[[], Dict[str, Any]]] = routing_meta_fn

    def add_process(self, process: Process) -> None:
        self.os_processes.append(process)

    def get_process_by_name(self, name: str) -> Optional[Process]:
        for p in self.os_processes:
            if p.name == name:
                return p
        return None

    def remove_process(self, name: str) -> None:
        # B-5 (RS-2): мутация СПИСКА НА МЕСТЕ (slice-assign), а НЕ ребиндинг
        # `self.os_processes = [...]`. ProcessStatusMonitor захватывает ссылку на
        # ЭТОТ list-объект в конструкторе (PM: ProcessStatusMonitor(registry.os_processes));
        # ребиндинг оставлял монитору стейл-алиас старого списка → он перечислял
        # процессы, снесённые давно (ghost в get_all_status). Slice-assign сохраняет
        # объект → все держатели алиаса (монитор и пр.) видят снятие немедленно.
        self.os_processes[:] = [p for p in self.os_processes if p.name != name]
        self._stop_events.pop(name, None)
        # Ф3.2: снять ссылку на ready_event. При restart create_and_register
        # создаст СВЕЖИЙ event (новый объект, а не .clear() — у старого ребёнка
        # могла остаться ссылка на прежний).
        self._ready_events.pop(name, None)
        # Task 1.6: снять ссылку на слот отчёта выхода — тем же доводом, что у ready_event:
        # свежий слот на каждый спавн, а не переживший .clear() старый.
        self._exit_reports.pop(name, None)

    def _set_reader_gone(self, name: str, gone: bool) -> None:
        """ADR-PMM-030: взвести/снять метку «читатель ушёл» на очередях ``name``.

        Никогда не бросает: сбой метки не должен ломать stop/spawn (худшее — писатель
        ждёт на выходе, как до ADR-PMM-030)."""
        if self.queue_registry is None:
            return
        try:
            set_reader_gone(self.queue_registry.get_process_queues(name).values(), gone)
        except Exception as e:  # noqa: BLE001 — метка вторична к факту остановки/спавна
            if self.logger:
                self.logger._log_warning(f"reader_gone={gone} для '{name}' не выставлен: {e}")

    def _mark_confirmed_dead(self, name: str, observed: Optional[Process]) -> None:
        """Метка за воплощение, чья смерть подтверждена (итерация 3 Task 1.2).

        Метит, только если под именем сейчас зарегистрирован этот же объект, никого нет или
        зарегистрированный не жив. Живое воплощение с тем же именем (рестарт успел
        зарегистрировать преемника) — не метится: это живой читатель. Зарегистрированный,
        но ещё не запущенный (``pid is None``: между ``create_and_register`` и ``start()``)
        — тоже будущий живой читатель, мёртвым не считается."""
        current = self.get_process_by_name(name)
        if current is None or current is observed or (current.pid is not None and not current.is_alive()):
            self._set_reader_gone(name, True)

    def get_ready_event(self, name: str) -> Optional[Event]:
        """Ф3.2: event готовности процесса (``None`` — процесс не создавался).

        Ставится ребёнком после успешного ``initialize()``; барьеры switch/boot
        читают ``is_set()`` для раннего выхода без ожидания settle-window.
        """
        return self._ready_events.get(name)

    def exit_report(self, name: str) -> Dict[str, Any]:
        """Task 1.6 (ADR-PMM-033): итог хука выхода ребёнка ``name`` — слот разделяемой памяти.

        Слот — [reported(0/1), released, buffered_dropped]; ``runner`` пишет ``reported``
        ПОСЛЕДНИМ (см. ``run_process_function``), поэтому ребёнок, умерший посреди записи,
        читается как «не знаю», а не как ложные нулевые числа. Нет слота (имя не создавалось
        через ``_create_process``) или ``reported`` не выставлен — то же «не знаю».
        Никогда не бросает: зовётся из ``PM.shutdown()``, где отказ недопустим.
        """
        slot = self._exit_reports.get(name)
        if slot is None:
            return {"released": 0, "buffered_dropped": 0, "reported": False}
        try:
            if not int(slot[0]):
                return {"released": 0, "buffered_dropped": 0, "reported": False}
            return {"released": int(slot[1]), "buffered_dropped": int(slot[2]), "reported": True}
        except Exception:  # noqa: BLE001 — отчёт вторичен к самой остановке
            return {"released": 0, "buffered_dropped": 0, "reported": False}

    def _create_process(
        self,
        name: str,
        class_path: str,
        config: Dict[str, Any],
        priority: str,
        stop_event: Event,
        ready_event: Optional[Event] = None,
    ) -> Optional[Process]:
        try:
            if self.logger:
                self.logger._log_info(f"Creating process '{name}' from '{class_path}'")

            process_config = dict(config or {})
            process_config["name"] = name
            process_config["class"] = class_path
            if self._child_stop_budget is not None:
                process_config.setdefault("stop_budget", dict(self._child_stop_budget))

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
                                "memory_coll",
                            )
                        }
                        if mem:
                            all_process_memory[pname] = mem
            custom["_all_process_memory"] = all_process_memory

            # Ф3.1: снимок epoch/incarnations на момент спавна — новый ребёнок
            # рождается с актуальными значениями соседей (сверка с routing.refresh).
            routing_meta: Dict[str, Any] = {}
            if self._routing_meta_fn is not None:
                try:
                    routing_meta = self._routing_meta_fn() or {}
                except Exception as e:  # noqa: BLE001 — meta не критична для спавна
                    if self.logger:
                        self.logger._log_warning(f"routing_meta_fn для '{name}' упал: {e}")

            # Ф3.2: ready_event кладём в bundle custom ПОСЛЕ pop-фильтра выше.
            # Легально в отличие от stop_event/system_stop_event: bundle целиком
            # передаётся Process-аргументом (inheritance при spawn) и НИКОГДА не
            # ре-сериализуется на стороне PM. Ключ занесён в EXCLUDE монитора
            # (process_monitor.py) — при broadcast'е состояния он не пиклится.
            if ready_event is not None:
                custom["ready_event"] = ready_event

            bundle = build_bundle(
                queues=queues,
                config=process_config,
                custom=custom,
                routing_map=routing_map,
                routing_meta=routing_meta,
            )

            # Task 1.6 (ADR-PMM-033): слот отчёта выхода — свежий на ВОПЛОЩЕНИЕ, как и
            # ready_event/stop_event выше. RawArray, не Value: три поля одним блоком,
            # без отдельного lock — пишет ровно один процесс (runner этого ребёнка),
            # читает PM уже ПОСЛЕ подтверждённой смерти (гонки записи нет).
            exit_report_slot = RawArray("q", 3)
            self._exit_reports[name] = exit_report_slot

            process = Process(
                target=run_process_function,
                # system_stop_event — отдельным аргументом (inheritance), НЕ в bundle custom.
                args=(class_path, name, stop_event, bundle, self._system_stop_event),
                # ADR-PMM-032: единственная точка, взводящая сторожа смерти родителя.
                # os.getpid() здесь — pid PM (Process() создаётся в нём при любом потоке).
                # ADR-PMM-033: exit_report — тем же путём (inheritance), что и parent_pid.
                # Task 5.4 (ADR-PMM-034): system_ready_event — тем же путём; в bundle custom
                # его нет (см. pop-фильтр выше), позиционно нельзя (шестой — new_session).
                kwargs={
                    "parent_pid": os.getpid(),
                    "exit_report": exit_report_slot,
                    "system_ready_event": self._system_ready_event,
                },
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
        # ADR-PMM-030 (итерация 3): единая точка отказа в спавне после системного стопа.
        # Проверки PM на входе start/restart/create дешевле (не делают бесполезный стоп),
        # но гарантией не являются: рестарт доходит сюда через 0.1–7 с своей stop-фазы.
        if self._system_stop_event is not None and self._system_stop_event.is_set():
            if self.logger:
                self.logger._log_warning(f"create_and_register('{name}'): отказ — системный стоп уже взведён")
            return None
        process_stop_event = Event()
        self._stop_events[name] = process_stop_event
        # Ф3.2: свежий ready_event на каждый (пере)спавн. При restart старый
        # инстанс мог держать ссылку на прежний event — новый объект её обнуляет.
        process_ready_event = Event()
        self._ready_events[name] = process_ready_event
        # ADR-PMM-030: снять метку ДО спавна — новое воплощение на переиспользованных
        # очередях есть живой читатель (в его bundle едет та же Event). Новые очереди
        # создаются внутри _create_process уже без метки — здесь их ещё нет, no-op.
        self._set_reader_gone(name, False)
        process = self._create_process(
            name, class_path, config or {}, priority, process_stop_event, process_ready_event
        )
        if process:
            self.add_process(process)
        else:
            self._stop_events.pop(name, None)
            self._ready_events.pop(name, None)
            self._exit_reports.pop(name, None)
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

    def stop_one(
        self, name: str, timeout: float = DEFAULT_SHUTDOWN_TIMEOUT_S, *, mark_reader_gone: bool = True
    ) -> bool:
        """Остановить один процесс с подтверждением смерти («ensure stopped»).

        Идемпотентная семантика: процесса нет в реестре или он не жив —
        уже остановлен → ``True``. Иначе эскалация stop_event → graceful-срок
        ``timeout`` → terminate → kill (Task 1.1: тот же путь, что ``stop_many``,
        через ``ChildProcessStop`` и область ``pm/stop``). Результат — ФАКТ
        смерти, а не «сигнал подан»: cleanup/unlink SHM безопасен только по
        подтверждённой остановке.

        ``mark_reader_gone`` (ADR-PMM-030): при ``True`` подтверждённо мёртвому
        (результат ``True``) ребёнку взводится метка «читатель ушёл» на его очередях —
        писатели не зависнут на выходе. Выживший не маркируется. Рестарт передаёт
        ``False``: очереди переиспользуются новым воплощением.
        """
        return self._stop_many([name], timeout, mark_reader_gone)[name]

    def stop_many(
        self, names: List[str], timeout: float = DEFAULT_SHUTDOWN_TIMEOUT_S, *, mark_reader_gone: bool = True
    ) -> Dict[str, bool]:
        """Остановить НЕСКОЛЬКО процессов ПАРАЛЛЕЛЬНО (один общий дедлайн).

        В отличие от ``stop_one`` в цикле (N×timeout ≈ 35с для 7 процессов),
        взводит все ``stop_event`` разом, затем ждёт graceful-выхода с ОБЩИМ
        дедлайном ``time.monotonic()+timeout`` → суммарно ~timeout. Стрэгглеры —
        ``terminate`` → ``kill`` (тоже параллельно) с confirmed-death. ``stop_all``
        делегирует сюда (shutdown-дорога тоже подтверждает смерть).

        Args:
            names: имена процессов для остановки.
            timeout: общий дедлайн graceful-остановки (секунды). ≤ 0 — сразу эскалация;
                NaN, ±inf, ``bool``, ``None`` и нечисловое — ``DEFAULT_SHUTDOWN_TIMEOUT_S``
                с предупреждением в лог (новых исключений на пути стопа нет).

        Returns:
            Карта ``{name: stopped}`` — семантика «ensure stopped»:
            ``True`` — процесса нет в реестре / он не был жив (идемпотентно:
            «нечего останавливать» — успех) ИЛИ смерть ПОДТВЕРЖДЕНА
            (graceful/terminate/kill);
            ``False`` — процесс всё ещё жив после полной эскалации
            (cleanup для него небезопасен).

        ``mark_reader_gone``: см. ``stop_one`` — маркируются только имена с ``True``, каждое
        в момент подтверждения ЕГО смерти, а не после всей эскалации (ADR-PMM-030).
        """
        return self._stop_many(names, timeout, mark_reader_gone)

    def _stop_timeout_s(self, timeout: object) -> float:
        """Привести graceful-срок стопа: путь стопа не бросает (Task 1.1, DESIGN 7).

        Конечное > 0 — как есть; ≤ 0 — ``0.0`` (сразу эскалация, как прежде с отрицательным);
        NaN, ±inf, ``bool``, ``None`` и нечисловое — умолчание с предупреждением: ``inf`` не
        превращается в немедленный terminate, который оборвал бы graceful-выход.
        """
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout):
            if self.logger:
                self.logger._log_warning(
                    f"stop: timeout типа {type(timeout).__name__} не конечное число секунд — "
                    f"взято умолчание {DEFAULT_SHUTDOWN_TIMEOUT_S}s"
                )
            return DEFAULT_SHUTDOWN_TIMEOUT_S
        return float(timeout) if timeout > 0 else 0.0

    def _build_child_stop(
        self, names: List[str], mark_reader_gone: bool
    ) -> tuple[Dict[str, bool], ChildProcessStop | None]:
        """Шаг (а) стопа и сборка группы живых (шов для Task 1.2: область ``children``).

        Нет в реестре / уже мёртв → ``True`` и метка СРАЗУ (идемпотентность, паритет
        ``PM.stop_process``: «призрак» в конфигах не валит switch). Живые — в одну группу
        ``ChildProcessStop``; ``None`` — живых нет.
        """
        result: Dict[str, bool] = {}
        procs: Dict[str, Process] = {}
        for name in names:
            process = self.get_process_by_name(name)
            if process is None:
                if self.logger:
                    self.logger._log_info(f"stop_many: '{name}' нет в реестре — считается остановленным")
                result[name] = True
                if mark_reader_gone:
                    self._mark_confirmed_dead(name, None)
                continue
            if not process.is_alive():
                result[name] = True
                if mark_reader_gone:
                    self._mark_confirmed_dead(name, process)
                continue
            procs[name] = process
        if not procs:
            return result, None
        stop = ChildProcessStop(
            procs,
            self._stop_events,
            on_confirmed_dead=self._mark_confirmed_dead if mark_reader_gone else None,
            logger=self.logger,
        )
        return result, stop

    def children_stop(self, *, mark_reader_gone: bool) -> "_ChildrenGroupStop":
        """Stoppable всех детей для области ``children`` корня PM (Task 1.2a, ADR-PMM-036).

        Ленивый: группа строится в ``request_stop()`` (дети создаются и удаляются на
        лету — смена топологии), не при вызове. ``result()`` — карта ``{имя: остановлен}``
        после закрытия области (как ``_stop_many`` после ``scope.close()``).
        """
        return _ChildrenGroupStop(self, mark_reader_gone)

    def _stop_many(self, names: List[str], timeout: object, mark_reader_gone: bool) -> Dict[str, bool]:
        """Единственный путь стопа детей: группа ``ChildProcessStop`` во временной области.

        Порядок фаз (stop_event → graceful ``timeout`` → terminate → ``TERMINATE_GRACE_S`` →
        kill → ``KILL_CONFIRM_S``) живёт один раз — в ``Scope``; метка ставится в момент
        подтверждения смерти каждого имени (``on_confirmed_dead``), выжившие — без метки.
        """
        timeout_s = self._stop_timeout_s(timeout)
        result, stop = self._build_child_stop(names, mark_reader_gone)
        if stop is None:
            return result

        group = [name for name in dict.fromkeys(names) if name not in result]
        if self.logger:
            self.logger._log_info(f"Stopping {len(group)} processes in parallel (timeout={timeout_s}s): {list(group)}")
        scope = open_scope("pm/stop", budget_s=timeout_s, kill_reserve_s=KILL_RESERVE_S)
        try:
            scope.own(stop, name="children", kind="process")
        finally:
            report = scope.close()
        if self.logger:
            for path, error in report.errors:
                self.logger._log_error(f"stop_many: {path}: {error}")

        survivors = stop.survivors()
        for name in group:
            result[name] = name not in survivors
        for name in survivors:
            if self.logger:
                self.logger._log_error(f"stop_many: '{name}' всё ещё жив после kill — остановка НЕ подтверждена")
        return result

    def stop_all(
        self, timeout: float = DEFAULT_SHUTDOWN_TIMEOUT_S, *, mark_reader_gone: bool = True
    ) -> Dict[str, bool]:
        """Остановить ВСЕ процессы с ПОДТВЕРЖДЕНИЕМ смерти (Ж-4, RS-3).

        Прежняя версия после ``kill`` НЕ делала финальный join и НЕ проверяла факт
        смерти — на shutdown это оставляло живого ребёнка (наблюдалось дважды за
        сессию). Теперь делегирует в ``stop_many`` (тот же confirmed-death путь,
        что switch-дорога B-1): graceful → terminate → kill → ФИНАЛЬНЫЙ join →
        сверка ``is_alive()``. Возвращает карту ``{name: stopped}`` — caller
        (``PM.shutdown``) обязан проверить выживших и заявить громко.
        """
        if self.logger:
            self.logger._log_info(f"Stopping all processes (timeout={timeout}s)...")
        # Делегируем в stop_many (per-process stop_event + confirmed-death). НЕ трогаем
        # ОБЩИЙ system_stop_event: он system-wide, в PM не сбрасывается, а stop_all
        # зовётся и вне shutdown (stop_process(None)) — его установка заглушила бы
        # последующий start. Подтверждения смерти достаточно per-process эскалации.
        names = [p.name for p in self.os_processes]
        results = self.stop_many(names, timeout, mark_reader_gone=mark_reader_gone)
        survivors = sorted(n for n, stopped in results.items() if not stopped)
        if survivors and self.logger:
            self.logger._log_error(
                f"stop_all: процессы ВЫЖИЛИ после полной эскалации (graceful→terminate→kill): "
                f"{survivors} — смерть НЕ подтверждена"
            )
        elif self.logger:
            self.logger._log_info("All processes stopped (смерть подтверждена)")
        return results


class _ChildrenGroupStop:
    """Stoppable над шагом (а) и группой ``ChildProcessStop`` всех детей реестра (Task 1.2a).

    Группа строится один раз, в ``request_stop()`` (или в ``join_until``, если фаза 1
    не звалась): имена берутся из ``os_processes`` В ЭТОТ момент. Сборка и сигнал детям
    идут под одним локом, ``_group`` виден только после успешной сборки; ``join_until``
    из другого потока ждёт этот лок. Пустая группа — ``join_until`` ``True``,
    ``kill``/``close`` ничего не делают. Сбой сборки — fail-closed: ``join_until`` ``False``,
    ``result()`` ``False`` по всем именам ``os_processes`` (смерть не подтверждена).
    """

    def __init__(self, registry: "ProcessRegistry", mark_reader_gone: bool) -> None:
        self._registry = registry
        self._mark_reader_gone = mark_reader_gone
        self._lock = threading.Lock()
        self._requested = False
        self._build_failed = False
        self._failed_names: List[str] = []
        self._done: Dict[str, bool] = {}
        self._group: ChildProcessStop | None = None
        self._names: List[str] = []

    def request_stop(self) -> None:
        with self._lock:
            if self._requested or self._build_failed:
                return
            names: List[str] = []
            try:
                names = [p.name for p in self._registry.os_processes]
                done, group = self._registry._build_child_stop(list(names), self._mark_reader_gone)
            except Exception:
                self._build_failed = True
                self._failed_names = list(dict.fromkeys(names))
                raise
            self._done, self._group = done, group
            self._names = [name for name in dict.fromkeys(names) if name not in done]
            self._requested = True
            if group is not None:
                group.request_stop()

    def join_until(self, deadline: float) -> bool:
        self.request_stop()  # ждёт лок чужой сборки; после сбоя сборки — тихий возврат
        with self._lock:
            group, failed = self._group, self._build_failed
        if failed:
            return False
        if group is None:
            return True
        return group.join_until(deadline)

    def kill(self) -> None:
        if self._group is not None:
            self._group.kill()

    def close(self) -> None:
        if self._group is not None:
            self._group.close()

    def result(self) -> Dict[str, bool]:
        """Карта шага (а) + для имён группы ``False``, если имя среди выживших.

        Не опирается на ``close()``: область выжившему ``close()`` не зовёт.
        """
        if self._build_failed:
            return {name: False for name in self._failed_names}
        result = dict(self._done)
        if self._group is None:
            return result
        survivors = set(self._group.survivors())
        for name in self._names:
            result[name] = name not in survivors
        return result
