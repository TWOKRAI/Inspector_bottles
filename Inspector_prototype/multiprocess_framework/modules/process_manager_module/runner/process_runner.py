"""
Функции-обёртки для запуска процессов (Top-level для сериализации).

Отвечает за:
- Создание процессов внутри целевого процесса ОС
- Правильную сериализацию для Windows (spawn)

Connection bundle: передаём только picklable (queues, config, custom),
избегая pickle SharedResourcesManager с RLock и др.
"""

import time
import importlib
import traceback
from multiprocessing import Event
from typing import Optional, Union, Dict, Any

from multiprocess_framework.modules.shared_resources_module import SharedResourcesManager
from multiprocess_framework.modules.process_module.configs.managers_normalize import (
    normalize_managers_view,
)


# ---------------------------------------------------------------------------
# Вспомогательный логгер (не требует инициализации LoggerManager)
# ---------------------------------------------------------------------------

class _ProcessLogger:
    """Лёгкий логгер: использует LoggerManager если доступен, иначе print."""

    def __init__(self, process_name: str, logger_manager=None):
        self._name = process_name
        self._lm = logger_manager

    def info(self, msg: str) -> None:
        if self._lm:
            self._lm.info(msg, module=self._name)
        else:
            print(f"[{self._name}] {msg}", flush=True)

    def warning(self, msg: str) -> None:
        if self._lm:
            self._lm.warning(msg, module=self._name)
        else:
            print(f"[{self._name}] WARNING: {msg}", flush=True)

    def error(self, msg: str) -> None:
        if self._lm:
            self._lm.error(msg, module=self._name)
        else:
            print(f"[{self._name}] ERROR: {msg}", flush=True)


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------

def _load_process_class(class_path: str, log: _ProcessLogger):
    """
    Загрузить класс процесса по пути.

    Args:
        class_path: Полный путь к классу (например, 'my_module.MyProcess').
        log: Логгер.

    Returns:
        Класс или None при ошибке.
    """
    try:
        module_path, class_name = class_path.rsplit(".", 1)
        module = importlib.import_module(module_path)
        return getattr(module, class_name)
    except (ImportError, AttributeError, ValueError) as e:
        log.error(f"Failed to load process class '{class_path}': {e}")
        traceback.print_exc()
        return None


def _normalize_memory_spec(spec: Any) -> Optional[tuple]:
    """
    Нормализует спецификацию памяти к формату (num_images, image_shape, dtype).

    Короткий формат: (h, w, c) → (1, (h,w,c), "uint8")
    Полный формат: (1, (h,w,c), "uint8") — без изменений
    """
    if not isinstance(spec, tuple):
        return None
    if len(spec) == 3:
        if isinstance(spec[1], tuple):
            return spec  # (num_images, (h,w,c), dtype)
        if all(isinstance(x, (int, float)) for x in spec):
            return (1, spec, "uint8")  # (h, w, c) short form
    return spec


def _normalize_memory_config(mem_cfg: Dict[str, Any]) -> tuple[Dict[str, tuple], int]:
    """
    Нормализует config["memory"] к (names, coll).

    Поддерживает:
    - Стандарт: {"names": {"x": (1,(h,w,c),"uint8")}, "coll": 2}
    - Короткий: {"names": {"x": (h,w,c)}, "coll": 2}
    - Плоский: {"x": (h,w,c)} — coll=2 по умолчанию
    """
    coll = mem_cfg.get("coll", 2)
    names_raw = mem_cfg.get("names")
    if names_raw is None:
        names_raw = {
            k: v for k, v in mem_cfg.items()
            if k != "coll" and isinstance(v, tuple)
        }
    normalized: Dict[str, tuple] = {}
    for name, spec in (names_raw or {}).items():
        ns = _normalize_memory_spec(spec)
        if ns:
            normalized[name] = ns
    return normalized, coll


def _build_shared_resources_from_bundle(
    process_name: str,
    bundle: Dict[str, Any],
) -> SharedResourcesManager:
    """
    Построить SharedResourcesManager из connection bundle внутри дочернего процесса.

    Args:
        process_name: Имя процесса.
        bundle: Dict с ключами queues, config, custom, routing_map.

    Returns:
        Инициализированный SharedResourcesManager.
    """
    shared_resources = SharedResourcesManager()
    queues = bundle.get("queues", {})
    process_config = bundle.get("config", {})
    custom = dict(bundle.get("custom", {}))
    custom.setdefault("process_config", process_config)

    shared_resources.process_state_registry.register_process(
        process_name,
        initial_state={"custom": custom},
    )
    # ADR-102: согласовать child SRM с get_process_config (pickle-safe срез, не полный proc_dict)
    _pc = process_config if isinstance(process_config, dict) else {}
    shared_resources.config_store.store(
        process_name,
        {
            "process": _pc,
            "managers": normalize_managers_view(_pc) if isinstance(_pc, dict) else {},
        },
    )

    all_process_memory = custom.pop("_all_process_memory", {})

    # Fallback: if bundle lacks memory_names (parent didn't create), create in child (owner)
    has_mem_names = bool(custom.get("memory_names"))
    has_mem_cfg = bool(process_config.get("memory"))
    if not has_mem_names and has_mem_cfg:
        mem_cfg = process_config["memory"]
        if isinstance(mem_cfg, dict):
            names, coll = _normalize_memory_config(mem_cfg)
            if names:
                ok = shared_resources.memory_manager.create_memory_dict(
                    process_name, names, coll
                )
                pd = shared_resources.get_process_data(process_name)
                mm = shared_resources.memory_manager
                # Явно синхронизировать pd.custom из _local_handles (на случай если PSR не обновился)
                if ok and pd and mm and hasattr(mm, "_local_handles"):
                    for shm_base_name, shm_list in mm._local_handles.get(process_name, {}).items():
                        if shm_list and shm_base_name in names:
                            pd.custom.setdefault("memory_names", {})[shm_base_name] = [s.name for s in shm_list]
                            pd.custom.setdefault("memory_params", {})[shm_base_name] = names[shm_base_name]
                            pd.custom.setdefault("memory_index_usage", {})[shm_base_name] = [0] * coll
                            pd.custom.setdefault("memory_coll", {})[shm_base_name] = coll
                    custom.update(pd.custom)
    for qtype, q in queues.items():
        shared_resources.process_state_registry.add_queue(process_name, qtype, q)

    routing_map = bundle.get("routing_map", {})
    for target_name, target_queues in routing_map.items():
        if target_name == process_name:
            continue
        shared_resources.process_state_registry.register_process(target_name)
        shared_resources.config_store.store(
            target_name, {"process": {}, "managers": {}}
        )
        for qtype, q in (target_queues or {}).items():
            shared_resources.process_state_registry.add_queue(target_name, qtype, q)

    # Синхронизировать memory_names других процессов для consumer (processor, renderer, gui)
    for other_name, mem_data in all_process_memory.items():
        if other_name == process_name:
            continue
        pd = shared_resources.get_process_data(other_name)
        if pd:
            for k, v in mem_data.items():
                pd.custom[k] = v

    # Инициализация SRM для MemoryManager и QueueRegistry (важно для SharedMemory)
    try:
        shared_resources.initialize()
        shared_resources.reinitialize_in_child()
    except Exception as e:
        # Не критично для очередей (уже в PSR), но MemoryManager может не работать
        import warnings
        warnings.warn(f"SRM.initialize() failed: {e}", UserWarning)

    return shared_resources


def _setup_console_redirect(process_name: str, process_data, log: _ProcessLogger):
    """
    Настроить перенаправление stdout/stderr если в custom есть console_queues.

    Args:
        process_name: Имя процесса.
        process_data: ProcessData из shared_resources.
        log: Логгер.

    Returns:
        Экземпляр ConsoleRedirector или None.
    """
    if not (process_data and process_data.custom):
        return None
    custom = process_data.custom
    if "console_queues" not in custom and "console_queue" not in custom:
        return None

    try:
        import sys
        from multiprocess_framework.modules.console_module import ConsoleRedirector

        if "console_queues" in custom:
            output_queues = custom["console_queues"]
            redirector = ConsoleRedirector(output_queues, process_name)
        else:
            output_queue = custom["console_queue"]
            redirector = ConsoleRedirector(output_queue, process_name)

        sys.stdout = redirector
        sys.stderr = redirector
        log.info("Console redirect enabled")
        return redirector
    except Exception as e:
        log.warning(f"Failed to setup console redirect: {e}")
        return None


def _run_lifecycle(
    process_instance,
    stop_event: Optional[Event],
    log: _ProcessLogger,
) -> None:
    """
    Запустить жизненный цикл процесса: run() + ожидание stop_event.

    Объединяет два цикла в один: run() вызывается, затем ждём stop_event
    или should_stop(). Если run() не определён — сразу ждём.

    Args:
        process_instance: Экземпляр процесса.
        stop_event: multiprocessing.Event для остановки.
        log: Логгер.
    """
    if hasattr(process_instance, "run"):
        process_instance.run()

    while True:
        if stop_event and stop_event.is_set():
            log.info("Stop signal received")
            if hasattr(process_instance, "stop"):
                process_instance.stop()
            break
        if hasattr(process_instance, "should_stop") and process_instance.should_stop():
            break
        time.sleep(0.1)


# ---------------------------------------------------------------------------
# Вспомогательные функции для error_module
# ---------------------------------------------------------------------------

def _log_exception_via_error_manager(
    shared_resources,
    exc: Exception,
    context: str,
) -> None:
    """
    Логировать исключение через ErrorManager из shared_resources если доступен.

    Args:
        shared_resources: SharedResourcesManager или None.
        exc: Исключение.
        context: Контекстное сообщение.
    """
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
    """
    Обновить состояние процесса в shared_resources.

    Args:
        shared_resources: SharedResourcesManager или None.
        process_name: Имя процесса.
        state: Новое состояние (например, 'error').
    """
    if not shared_resources:
        return
    try:
        psr = getattr(shared_resources, "process_state_registry", None)
        if psr is not None and hasattr(psr, "update_state"):
            psr.update_state(process_name, status=state)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Основная функция
# ---------------------------------------------------------------------------

def run_process_function(
    class_path: str,
    process_name: str,
    stop_event: Optional[Event] = None,
    shared_resources_or_bundle: Optional[Union[SharedResourcesManager, Dict[str, Any]]] = None,
):
    """
    Top-level функция для запуска процесса внутри OS-процесса.

    Создаёт все объекты внутри целевого процесса (важно для Windows spawn).

    Режимы работы:
        - Bundle mode: shared_resources_or_bundle — dict с queues/config/custom.
          SharedResourcesManager создаётся внутри процесса (pickle-safe).
        - SRM mode: shared_resources_or_bundle — SharedResourcesManager (для тестов).

    Args:
        class_path: Путь к классу процесса (например, 'module.path.ClassName').
        process_name: Имя процесса.
        stop_event: Событие остановки (multiprocessing.Event).
        shared_resources_or_bundle: SharedResourcesManager ИЛИ connection bundle.
    """
    log = _ProcessLogger(process_name)
    redirector = None
    process_instance = None
    shared_resources = None

    try:
        log.info("Process starting...")

        process_class = _load_process_class(class_path, log)
        if process_class is None:
            return

        # Построить shared_resources
        if isinstance(shared_resources_or_bundle, dict):
            shared_resources = _build_shared_resources_from_bundle(
                process_name, shared_resources_or_bundle
            )
        else:
            shared_resources = shared_resources_or_bundle or SharedResourcesManager()
            process_data = shared_resources.get_process_data(process_name)
            if process_data is None:
                shared_resources.process_state_registry.register_process(process_name)

        process_data = shared_resources.get_process_data(process_name)

        # Извлечь конфиг процесса
        process_config: Dict[str, Any] = {}
        if process_data:
            if (
                hasattr(process_data, "config")
                and process_data.config
                and hasattr(process_data.config, "process")
            ):
                process_config = process_data.config.process
            elif process_data.custom:
                process_config = process_data.custom.get(
                    "process_config", process_data.custom.copy()
                )

        redirector = _setup_console_redirect(process_name, process_data, log)

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

        _run_lifecycle(process_instance, stop_event, log)
        log.info("Process finished")

    except KeyboardInterrupt:
        log.info("Interrupted by user")
    except Exception as e:
        log.error(f"Process failed: {e}")
        traceback.print_exc()
        _log_exception_via_error_manager(shared_resources, e, "process failed")
        _update_process_state(shared_resources, process_name, "error")
    finally:
        if redirector:
            import sys
            sys.stdout = redirector.original_stdout
            sys.stderr = redirector.original_stderr
            redirector.close()

        if process_instance is not None:
            try:
                if hasattr(process_instance, "shutdown"):
                    process_instance.shutdown()
                elif hasattr(process_instance, "stop"):
                    process_instance.stop()
            except Exception as e:
                log.error(f"Error during cleanup: {e}")
