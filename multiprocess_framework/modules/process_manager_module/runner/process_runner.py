"""
Top-level entry для запуска процесса внутри OS-процесса (spawn-safe).

Connection bundle: только picklable (queues, config, custom).
"""

import os
import threading
import time
import traceback
from multiprocessing import Event
from typing import Any, Dict, Optional, Union

from multiprocess_framework.modules.shared_resources_module import SharedResourcesManager

from ..._fallback import emergency_log
from ...logger_module.adapters.std_facade import StdLoggerFacade, get_std_logger
from .class_loader import _load_process_class
from .bundle_builder import _build_shared_resources_from_bundle


# ADR-PMM-032: сторож смерти родителя (ProcessManager'а). Бюджет приёмки — 2.0с от
# гибели родителя до исчезновения ребёнка: опрос 0.25 + grace 1.5 = 1.75 < 2.0
# (остаток 0.25с — на os._exit и реап ядром).
_PARENT_POLL_S = 0.25
_PARENT_DEATH_GRACE_S = 1.5
# Код выхода принудительной ветки: отличим от 0 (штатный стоп), 1 (исключение)
# и -N (убит сигналом) — по нему видно, что ребёнка добил сторож, а не lifecycle.
_PARENT_DEATH_EXIT_CODE = 75


def _on_parent_death(
    parent_pid: int,
    stop_event: Optional[Event],
    system_stop_event: Optional[Event],
    process_name: str,
    grace_s: float,
) -> None:
    """Родитель умер: взвести стоп, дать штатному lifecycle ``grace_s``, затем добить.

    Лог — только emergency_log: LoggerManager мог умереть вместе с родителем.
    ``os._exit`` не выполняет ``finally``, поэтому всё, что должно случиться, — до него.
    """
    emergency_log(
        __name__,
        "warning",
        "%s: родитель pid=%s умер — взвожу stop_event/system_stop_event, принудительный выход через %.1fс",
        process_name,
        parent_pid,
        grace_s,
    )
    # Каждое событие — в своём try: Manager-прокси/семафор родителя может быть уже битым.
    # system_stop_event — общий путь стопа: гаснут и соседи, их PM всё равно мёртв.
    for evt in (stop_event, system_stop_event):
        if evt is None:
            continue
        try:
            evt.set()
        except Exception:  # noqa: BLE001 — лучшее, что можем; дальше всё равно os._exit
            pass
    # Кооперативный ребёнок выйдет сам за это время (lifecycle → stop() → release_queues_at_exit).
    if grace_s > 0:
        time.sleep(grace_s)
    os._exit(_PARENT_DEATH_EXIT_CODE)


def _watch_parent(
    parent_pid: int,
    stop_event: Optional[Event],
    system_stop_event: Optional[Event],
    process_name: str,
) -> None:
    """Тело daemon-потока: опрос ``os.getppid()`` до смены родителя (ADR-PMM-032).

    Смерть родителя на POSIX = переродительство к init/subreaper → getppid меняется.
    """
    if os.getppid() != parent_pid:
        try:
            os.kill(parent_pid, 0)
        except ProcessLookupError:
            # Классическая гонка: родитель умер ДО старта сторожа. grace=0: сторож — первая
            # инструкция run_process_function, ребёнок ещё ничего не сделал, беречь нечего.
            _on_parent_death(parent_pid, stop_event, system_stop_event, process_name, 0.0)
            return
        except Exception:  # noqa: BLE001 — EPERM и т.п.: процесс существует → не наш прямой родитель
            pass
        # ponytail: родитель жив, но не наш прямой родитель (напр. будущий start method
        # forkserver — родителем будет сервер). Не взводимся — без ложных срабатываний;
        # потолок: при forkserver защиты нет. Апгрейд — передавать pid сервера/сторожить по pidfd.
        emergency_log(
            __name__,
            "warning",
            "%s: getppid()=%s != parent_pid=%s при живом parent_pid — сторож смерти родителя НЕ взведён",
            process_name,
            os.getppid(),
            parent_pid,
        )
        return
    while True:
        time.sleep(_PARENT_POLL_S)
        if os.getppid() != parent_pid:
            _on_parent_death(parent_pid, stop_event, system_stop_event, process_name, _PARENT_DEATH_GRACE_S)
            return


def _start_parent_watcher(
    parent_pid: Optional[int],
    stop_event: Optional[Event],
    system_stop_event: Optional[Event],
    process_name: str,
) -> Optional[threading.Thread]:
    """Взвести сторожа, если PM передал свой pid. None → не сторожим (SRM-режим, сам PM)."""
    # ponytail: Windows — no-op: getppid там не меняется при смерти родителя. Потолок:
    # на Windows ребёнок переживает PM (дерево держит Job Object launcher'а, не PM).
    if parent_pid is None or os.name == "nt":
        return None
    t = threading.Thread(
        target=_watch_parent,
        args=(parent_pid, stop_event, system_stop_event, process_name),
        name=f"parent-watch-{process_name}",
        daemon=True,
    )
    t.start()
    return t


def _run_lifecycle(
    process_instance,
    stop_event: Optional[Event],
    log: StdLoggerFacade,
    system_stop_event: Optional[Event] = None,
) -> None:
    """run() затем ожидание stop_event / system_stop_event / should_stop().

    Наблюдаются ДВА события: per-process ``stop_event`` (остановка одного процесса)
    и ОБЩИЙ ``system_stop_event`` (любой процесс взвёл → все гаснут параллельно).
    """
    if hasattr(process_instance, "run"):
        process_instance.run()

    while True:
        own = stop_event is not None and stop_event.is_set()
        system = system_stop_event is not None and system_stop_event.is_set()
        if own or system:
            log.info("Stop signal received (system-wide)" if system and not own else "Stop signal received")
            if hasattr(process_instance, "stop"):
                process_instance.stop()
            break
        if hasattr(process_instance, "should_stop") and process_instance.should_stop():
            break
        time.sleep(0.1)


def _log_exception_via_error_manager(
    shared_resources,
    exc: Exception,
    context: str,
) -> None:
    if not shared_resources:
        return
    try:
        from multiprocess_framework.modules.error_module import ErrorManager

        for process_name in shared_resources.process_state_registry.get_process_names():
            process_data = shared_resources.get_process_data(process_name)
            if process_data and process_data.custom:
                error_manager = process_data.custom.get("error_manager")
                if isinstance(error_manager, ErrorManager):
                    error_manager.log_exception(exc, context, module="process_runner")
                    return
    except Exception:
        pass


def _update_process_state(
    shared_resources,
    process_name: str,
    state: str,
) -> None:
    if not shared_resources:
        return
    try:
        psr = getattr(shared_resources, "process_state_registry", None)
        if psr is not None and hasattr(psr, "update_state"):
            psr.update_state(process_name, status=state)
    except Exception:
        pass


def _attach_stop_event_to_process_data(
    process_data: Any,
    stop_event: Optional[Event],
) -> None:
    """Spawner передаёт stop_event аргументом; ProcessManager читает из custom."""
    if stop_event is None or process_data is None:
        return
    custom = getattr(process_data, "custom", None)
    if custom is None:
        return
    if not isinstance(custom, dict):
        return
    custom["stop_event"] = stop_event


# Task 4.6: дефолт потоков OpenCV на процесс. Без него каждый процесс берёт все ядра
# (cv2.getNumThreads() == числу логических CPU), и N процессов душат друг друга.
DEFAULT_CV_THREADS = 2


def _apply_cv_threads(process_config: Any, log: Any) -> None:
    """Применить ``cv_threads`` процесса к OpenCV этого OS-процесса (``cv2.setNumThreads``).

    В рецепте ключ задаётся ТОЛЬКО как ``extras: {cv_threads: N}`` (плоский ``cv_threads:``
    уходит в metadata и до процесса не доходит). Во вложенном ``config`` его кладёт
    ``GenericProcessConfig.build()``; плоский верхний уровень — запасной путь для
    не-Generic процессов. Нет ключа / None → ``DEFAULT_CV_THREADS``; не целое, bool или
    < 1 → предупреждение и тот же дефолт (в OpenCV 0 = один поток, отрицательное = все
    ядра — ровно то, от чего дефолт защищает). cv2 не установлен → тихо ничего:
    framework не зависит от OpenCV, поэтому импорт ленивый (здесь и в ``introspect.status``).

    Как подбирать (для будущих агентов): дефолт 2, потому что несколько занятых процессов
    порождают каждый свой пул OpenCV размером с число ядер и дерутся за них. Поднимать
    (4-8) — для одного тяжёлого процесса на крупных кадрах, пока остальные простаивают;
    1 — лёгким процессам на мелких кадрах. Правило: сумма ``cv_threads`` одновременно
    занятых процессов ≈ числу ядер. Действующее значение видно в ``introspect.status``
    (``cv_threads``). Выбирать замером (CPU процесса + время плагина), а не на глаз.
    """
    cfg = process_config if isinstance(process_config, dict) else {}
    nested = cfg.get("config")
    raw = nested.get("cv_threads") if isinstance(nested, dict) else None
    if raw is None:
        raw = cfg.get("cv_threads")
    n = DEFAULT_CV_THREADS
    if raw is not None:
        if isinstance(raw, int) and not isinstance(raw, bool) and raw >= 1:
            n = raw
        else:
            log.warning(f"cv_threads={raw!r} — нужно целое >= 1; применён дефолт {DEFAULT_CV_THREADS}")
    try:
        import cv2
    except ImportError:
        return
    cv2.setNumThreads(n)


def run_process_function(
    class_path: str,
    process_name: str,
    stop_event: Optional[Event] = None,
    shared_resources_or_bundle: Optional[Union[SharedResourcesManager, Dict[str, Any]]] = None,
    system_stop_event: Optional[Event] = None,
    new_session: bool = False,
    parent_pid: Optional[int] = None,
    exit_report: Optional[Any] = None,
    *,
    system_ready_event: Optional[Event] = None,
):
    """
    Top-level функция для запуска процесса внутри OS-процесса.

    Bundle mode: dict → SharedResourcesManager создаётся внутри процесса.
    SRM mode: готовый SharedResourcesManager (тесты).

    parent_pid: pid ProcessManager'а (ставит только ``ProcessRegistry._create_process``).
        Не None → POSIX-сторож смерти родителя (ADR-PMM-032): ребёнок не переживает PM.
        None → не сторожим (сам PM от spawner'а, SRM-режим тестов).

    exit_report: слот разделяемой памяти (ADR-PMM-033, Task 1.6) — [reported, released,
        buffered_dropped]; пишется в ``finally`` итогом ``release_queues_at_exit``, PM
        читает его в ``shutdown()`` через ``ProcessRegistry.exit_report(name)``. None —
        не сторожим (SRM-mode тестов, процесс без ``_create_process``).

    system_ready_event: событие готовности СИСТЕМЫ (Task 5.4, ADR-PMM-034) — только kwarg
        (шестой позиционный — ``new_session``). Кладётся атрибутом ``_sources_ready_event``
        на экземпляр ДО ``initialize()``; ребёнок его только читает (источники ждут
        перед первым produce()), взводит один PM. НЕ ``attach_ready_event``: тот — про
        СОБСТВЕННУЮ готовность ребёнка.

    new_session: POSIX — сделать setsid() (стать лидером новой сессии/группы),
        чтобы ВСЕ потомки этого процесса попали в одну process group. Тогда
        launcher гасит дерево через killpg(pgid), не трогая себя
        (см. ProcessTreeGuard). Ставится только для оркестратора. Windows — no-op
        (там дерево держит Job Object).
    """
    # ADR-PMM-032: сторож — САМОЕ первое, до setsid/register_self/загрузки класса:
    # смерть PM во время boot ребёнка тоже покрыта.
    _start_parent_watcher(parent_pid, stop_event, system_stop_event, process_name)

    # 2.2: именованный вид вместо собственного _ProcessLogger. Имя процесса
    # остаётся полем источника записи, а не только текстом сообщения (Ф2.1).
    log = get_std_logger(process_name)
    process_instance = None
    shared_resources = None

    # POSIX: новая сессия → отдельная process group для всего поддерева оркестратора.
    if new_session and os.name != "nt":
        try:
            os.setsid()
        except Exception:  # noqa: BLE001 — уже лидер группы / не критично
            pass

    # Самрегистрация в PID-реестре: при жёстком убийстве главного процесса (закрытие
    # окна терминала) finally→stop() не отрабатывает; реестр позволяет следующему старту
    # реапнуть осиротевшие хвосты. Путь — из env MULTIPROCESS_PID_FILE (ставит launcher).
    try:
        from ..launcher.pid_registry import register_self

        register_self()
    except Exception:  # noqa: BLE001 — реестр не критичен
        pass

    try:
        log.info("Process starting...")

        process_class = _load_process_class(class_path, log)
        if process_class is None:
            return

        if isinstance(shared_resources_or_bundle, dict):
            shared_resources = _build_shared_resources_from_bundle(process_name, shared_resources_or_bundle)
        else:
            shared_resources = shared_resources_or_bundle or SharedResourcesManager()
            process_data = shared_resources.get_process_data(process_name)
            if process_data is None:
                shared_resources.process_state_registry.register_process(process_name)

        process_data = shared_resources.get_process_data(process_name)
        _attach_stop_event_to_process_data(process_data, stop_event)
        # ОБЩИЙ system_stop_event держим АТРИБУТОМ на shared_resources, а НЕ в custom.
        # Причина: ProcessMonitor._broadcast_status_change рассылает весь state процесса
        # (включая custom) через Queue всем процессам — сырой mp.Event на Windows-spawn
        # пиклится только через inheritance, иначе RuntimeError. SRM-инстанс локален для
        # процесса и никогда не сериализуется в очередь. Событие приходит отдельным
        # Process-аргументом (inheritance); PM/GUI читают его через get_system_stop_event().
        if system_stop_event is not None and shared_resources is not None:
            shared_resources._system_stop_event = system_stop_event

        process_config: Dict[str, Any] = {}
        if process_data:
            if hasattr(process_data, "config") and process_data.config and hasattr(process_data.config, "process"):
                process_config = process_data.config.process
            elif process_data.custom:
                process_config = process_data.custom.get("process_config", process_data.custom.copy())

        # Task 4.6: потоки OpenCV — ДО создания класса процесса (плагины могут дёрнуть cv2
        # уже в __init__/initialize).
        _apply_cv_threads(process_config, log)

        process_instance = process_class(
            name=process_name,
            shared_resources=shared_resources,
            config=process_config,
        )

        # Task 5.4 (ADR-PMM-034): ДО initialize() — GenericProcess может строить
        # SourceProducer уже в initialize(), а не только в run().
        if system_ready_event is not None:
            process_instance._sources_ready_event = system_ready_event

        if hasattr(process_instance, "initialize"):
            try:
                if not process_instance.initialize():
                    log.error("Process initialization failed")
                    _update_process_state(shared_resources, process_name, "error")
                    return
                log.info("Process initialized")
            except Exception as init_err:
                log.error(f"Process initialization error: {init_err}")
                traceback.print_exc()
                _log_exception_via_error_manager(shared_resources, init_err, "initialization error")
                _update_process_state(shared_resources, process_name, "error")
                return

        # Ф3.2 (self-reported ready) + правка 5.11 (живой прогон 2026-07-29):
        # готовность объявляет САМ процесс в конце run() — там, где он уже умеет
        # принимать команды. Здесь событие только ПЕРЕДАЁТСЯ ему.
        #
        # Почему не как раньше («set сразу после initialize()»): message-loop
        # поднимается ВНУТРИ initialize() (шаг 7), а команды процесса регистрируются
        # позже, в run(). Кто верил прежнему сигналу, слал команду в это окно — и она
        # молча терялась: живой лог ребёнка показывал `No handler for key
        # 'observability.tail.subscribe'`, а отправитель (fire-and-forget) об этом
        # не узнавал никогда.
        #
        # Процесс без ``attach_ready_event`` (не-ProcessModule, mock) объявить себя не
        # умеет — за него сигналим здесь, по-старому: молчание лишило бы барьер
        # раннего выхода вовсе. Event приходит через bundle custom (inheritance при
        # spawn); в SRM-mode/старых bundle его нет — guard None, чистый death-watch.
        if isinstance(shared_resources_or_bundle, dict):
            ready_event = shared_resources_or_bundle.get("custom", {}).get("ready_event")
            if ready_event is not None:
                attach = getattr(process_instance, "attach_ready_event", None)
                try:
                    if callable(attach):
                        attach(ready_event)
                        log.info("ready_event передан процессу — объявит готовность сам (после run())")
                    else:
                        ready_event.set()
                        log.info("ready_event выставлен runner'ом — процесс не умеет объявлять готовность сам")
                except Exception as ready_err:  # noqa: BLE001 — сигнал не критичен
                    log.error(f"Не удалось передать/выставить ready_event: {ready_err}")

        # ОБЩИЙ system-wide stop приходит отдельным Process-аргументом (inheritance).
        # Fallback — атрибут на shared_resources (на случай SRM-mode без явного аргумента).
        if system_stop_event is None and shared_resources is not None:
            system_stop_event = getattr(shared_resources, "_system_stop_event", None)
        _run_lifecycle(process_instance, stop_event, log, system_stop_event)
        log.info("Process finished")

    except KeyboardInterrupt:
        log.info("Interrupted by user")
    except Exception as e:
        log.error(f"Process failed: {e}")
        traceback.print_exc()
        _log_exception_via_error_manager(shared_resources, e, "process failed")
        _update_process_state(shared_resources, process_name, "error")
    finally:
        if process_instance is not None:
            try:
                if hasattr(process_instance, "shutdown"):
                    process_instance.shutdown()
                elif hasattr(process_instance, "stop"):
                    process_instance.stop()
            except Exception as e:
                log.error(f"Error during cleanup: {e}")
        # L-2 Task 1.2 (ADR-SRM-016): отпустить feeder'ы очередей, чей читатель ушёл
        # навсегда (системный стоп), иначе выход интерпретатора ждёт их вечно.
        if shared_resources is not None:
            try:
                sys_evt = system_stop_event or getattr(shared_resources, "_system_stop_event", None)
                res = shared_resources.queue_registry.release_queues_at_exit(
                    process_name, system_stop=sys_evt is not None and sys_evt.is_set()
                )
                # Task 1.6 (ADR-PMM-033): итог — в слот PM. Свой try/except: сбой записи
                # слота вторичен к самому отпуску очередей и не должен маскировать/дублировать
                # emergency_log ниже. ``reported`` — ПОСЛЕДНИМ: ребёнок, убитый посреди записи
                # (kill между строками), обязан читаться PM как «не знаю», а не как ложный ноль.
                if exit_report is not None:
                    try:
                        exit_report[1] = res["released"]
                        exit_report[2] = res["buffered_dropped"]
                        exit_report[0] = 1
                    except Exception:  # noqa: BLE001 — слот вторичен к самому отпуску очередей
                        pass
                # Аварийный выход, а не ``log``: к этому моменту LoggerManager процесса уже
                # остановлен, и запись через вид не доходила ни до одного приёмника (ревью
                # Task 1.2). Тихо, если отпускать было нечего — не +1 строка на процесс.
                if res["released"]:
                    emergency_log(
                        __name__,
                        "warning",
                        "%s: queues released to gone readers: %d, buffered dropped: %d",
                        process_name,
                        res["released"],
                        res["buffered_dropped"],
                    )
            except Exception as e:  # noqa: BLE001 — хук выхода не роняет выход
                emergency_log(__name__, "error", "%s: queue release at exit failed: %r", process_name, e)
        elif exit_report is not None:
            # shared_resources остался None: класс процесса не загрузился (`_load_process_class`
            # вернул None, ранний return выше) либо сборка bundle из словаря бросила исключение
            # (ревью Task 1.6, it.1: SRM-режим сюда НЕ приводит — `shared_resources` там всегда
            # не-None, строка 273 выше). Отпускать нечего — очереди не поднимались, — но хук
            # ДОШЁЛ, и PM обязан видеть это как «знаем: 0/0», а не как «умер до finally».
            try:
                exit_report[1] = 0
                exit_report[2] = 0
                exit_report[0] = 1
            except Exception:  # noqa: BLE001 — слот вторичен
                pass
