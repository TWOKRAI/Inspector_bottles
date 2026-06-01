"""
Top-level entry для запуска процесса внутри OS-процесса (spawn-safe).

Connection bundle: только picklable (queues, config, custom).
"""

import time
import traceback
from multiprocessing import Event
from typing import Any, Dict, Optional, Union

from multiprocess_framework.modules.shared_resources_module import SharedResourcesManager

from .class_loader import _ProcessLogger, _load_process_class
from .bundle_builder import _build_shared_resources_from_bundle


def _run_lifecycle(
    process_instance,
    stop_event: Optional[Event],
    log: _ProcessLogger,
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


def run_process_function(
    class_path: str,
    process_name: str,
    stop_event: Optional[Event] = None,
    shared_resources_or_bundle: Optional[Union[SharedResourcesManager, Dict[str, Any]]] = None,
):
    """
    Top-level функция для запуска процесса внутри OS-процесса.

    Bundle mode: dict → SharedResourcesManager создаётся внутри процесса.
    SRM mode: готовый SharedResourcesManager (тесты).
    """
    log = _ProcessLogger(process_name)
    process_instance = None
    shared_resources = None

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

        process_config: Dict[str, Any] = {}
        if process_data:
            if hasattr(process_data, "config") and process_data.config and hasattr(process_data.config, "process"):
                process_config = process_data.config.process
            elif process_data.custom:
                process_config = process_data.custom.get("process_config", process_data.custom.copy())

        process_instance = process_class(
            name=process_name,
            shared_resources=shared_resources,
            config=process_config,
        )

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

        # ОБЩИЙ system-wide stop приходит через bundle custom (spawner→PM→дети).
        system_stop_event = None
        if process_data and getattr(process_data, "custom", None):
            system_stop_event = process_data.custom.get("system_stop_event")
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
