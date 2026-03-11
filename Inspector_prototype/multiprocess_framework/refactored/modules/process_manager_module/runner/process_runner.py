"""
Функции-обертки для запуска процессов (Top-level для сериализации).

Отвечает за:
- Создание процессов внутри целевого процесса ОС
- Правильную сериализацию для Windows (spawn)

Connection bundle: передаём только picklable (queues, config, custom),
избегая pickle SharedResourcesManager с RLock и др.
"""

import time
import importlib
from multiprocessing import Event
from typing import Optional, Union, Dict, Any

from multiprocess_framework.refactored.modules.shared_resources_module import SharedResourcesManager


def run_process_function(
    class_path: str,
    process_name: str,
    stop_event: Optional[Event] = None,
    shared_resources_or_bundle: Optional[Union[SharedResourcesManager, Dict[str, Any]]] = None
):
    """
    Top-level функция для запуска процесса.
    Создает все объекты внутри целевого процесса (важно для Windows spawn).
    
    Args:
        class_path: Путь к классу процесса (например, 'module.path.ClassName')
        process_name: Имя процесса
        stop_event: Событие остановки (multiprocessing.Event)
        shared_resources_or_bundle: SharedResourcesManager ИЛИ connection bundle
            (dict с keys: queues, config, custom) — только picklable, без RLock
    """
    redirector = None
    try:
        print(f"[{process_name}] Process starting...")
        
        try:
            module_path, class_name = class_path.rsplit('.', 1)
            module = importlib.import_module(module_path)
            process_class = getattr(module, class_name)
        except (ImportError, AttributeError, ValueError) as e:
            print(f"[{process_name}] Failed to load process class '{class_path}': {e}")
            import traceback
            traceback.print_exc()
            return
        
        # Connection bundle: строим SharedResourcesManager в дочернем процессе
        if isinstance(shared_resources_or_bundle, dict):
            shared_resources = SharedResourcesManager()
            bundle = shared_resources_or_bundle
            queues = bundle.get("queues", {})
            process_config = bundle.get("config", {})
            custom = dict(bundle.get("custom", {}))
            custom.setdefault("process_config", process_config)
            shared_resources.register_process_state(
                process_name,
                initial_state={"custom": custom},
                config={"process": process_config, "managers": process_config.get("managers", {})}
            )
            for qtype, q in queues.items():
                shared_resources.process_state_registry.add_queue(process_name, qtype, q)
            # Телефонная книга: добавляем очереди всех процессов из routing_map
            routing_map = bundle.get("routing_map", {})
            for target_name, target_queues in routing_map.items():
                if target_name == process_name:
                    continue
                shared_resources.register_process_state(target_name)
                for qtype, q in (target_queues or {}).items():
                    shared_resources.process_state_registry.add_queue(target_name, qtype, q)
            process_data = shared_resources.get_process_data(process_name)
        else:
            shared_resources = shared_resources_or_bundle or SharedResourcesManager()
            process_data = shared_resources.get_process_data(process_name)
            if process_data is None:
                shared_resources.register_process_state(process_name)
                process_data = shared_resources.get_process_data(process_name)
        
        process_config = {}
        if process_data:
            if hasattr(process_data, 'config') and process_data.config and hasattr(process_data.config, 'process'):
                process_config = process_data.config.process
            elif process_data.custom:
                process_config = process_data.custom.get('process_config', process_data.custom.copy())
        
        # Настраиваем перенаправление stdout/stderr если есть queue соединение(я)
        if process_data and process_data.custom and ('console_queues' in process_data.custom or 'console_queue' in process_data.custom):
            try:
                from Console_module.redirector import ConsoleRedirector
                import sys
                
                # Новый формат: список queues для дублирования
                if 'console_queues' in process_data.custom:
                    output_queues = process_data.custom['console_queues']
                    redirector = ConsoleRedirector(output_queues, process_name)
                    sys.stdout = redirector
                    sys.stderr = redirector
                    print(f"[{process_name}] Console redirect enabled ({len(output_queues)} console(s))")
                # Старый формат для обратной совместимости
                elif 'console_queue' in process_data.custom:
                    output_queue = process_data.custom['console_queue']
                    redirector = ConsoleRedirector(output_queue, process_name)
                    sys.stdout = redirector
                    sys.stderr = redirector
                    print(f"[{process_name}] Console redirect enabled (legacy format)")
            except Exception as e:
                print(f"[{process_name}] Failed to setup console redirect: {e}")
        
        # Создаем экземпляр процесса ВНУТРИ целевого процесса
        # Конфигурация берется из process_data.config
        process_instance = process_class(
            name=process_name,
            shared_resources=shared_resources,
            config=process_config
        )
        
        # Инициализация процесса
        if hasattr(process_instance, 'initialize'):
            try:
                if not process_instance.initialize():
                    print(f"[{process_name}] Process initialization failed")
                    return
            except Exception as init_err:
                print(f"[{process_name}] Process initialization error: {init_err}")
                import traceback
                traceback.print_exc()
                return
        
        # Запускаем процесс
        if hasattr(process_instance, 'run'):
            process_instance.run()
        else:
            # Если нет метода run, просто ждем остановки
            while not (hasattr(process_instance, 'should_stop') and process_instance.should_stop()):
                if stop_event and stop_event.is_set():
                    break
                time.sleep(0.1)
        
        # Ожидаем завершения (следим за stop_event если он есть)
        while True:
            if stop_event and stop_event.is_set():
                print(f"[{process_name}] Stop signal received")
                if hasattr(process_instance, 'stop'):
                    process_instance.stop()
                break
            if hasattr(process_instance, 'should_stop') and process_instance.should_stop():
                break
            time.sleep(0.1)
        
        print(f"[{process_name}] Process finished")
        
    except KeyboardInterrupt:
        print(f"[{process_name}] Interrupted by user")
    except Exception as e:
        print(f"[{process_name}] Process failed: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # Восстанавливаем оригинальные stdout/stderr
        if redirector:
            import sys
            sys.stdout = redirector.original_stdout
            sys.stderr = redirector.original_stderr
            redirector.close()
        
        # Убедимся, что процесс останавливается корректно
        if 'process_instance' in locals():
            try:
                if hasattr(process_instance, 'shutdown'):
                    process_instance.shutdown()
                elif hasattr(process_instance, 'stop'):
                    process_instance.stop()
            except Exception as e:
                print(f"[{process_name}] Error during cleanup: {e}")


# Синоним для совместимости со старым кодом
_run_process_function = run_process_function

