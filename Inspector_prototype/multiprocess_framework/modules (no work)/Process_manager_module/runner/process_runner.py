"""
Функции-обертки для запуска процессов (Top-level для сериализации).

Отвечает за:
- Создание процессов внутри целевого процесса ОС
- Правильную сериализацию для Windows

ВАЖНО: SharedResourcesManager передается напрямую БЕЗ Manager().
Queue и Event сериализуемы сами по себе.

Конфигурация процесса берется из ProcessData через shared_resources.
ConfigManager создается локально в каждом процессе.
"""

import time
from multiprocessing import Event
from typing import Any, Dict, Optional

from ...Shared_resources_module.SharedResourcesManager import SharedResourcesManager


def _run_process_function(
    class_path, 
    process_name: str, 
    stop_event: Event = None, 
    shared_resources: Optional[SharedResourcesManager] = None
):
    """
    Top-level функция для запуска процесса.
    Создает все объекты внутри целевого процесса (важно для Windows).
    
    Args:
        class_path: Строка пути к классу процесса (например, 'module.path.ClassName')
        process_name: Имя процесса
        stop_event: Событие остановки (multiprocessing.Event)
        shared_resources: SharedResourcesManager (передается напрямую, БЕЗ Manager)
                         Содержит config_manager и process_data с конфигурацией
    """
    try:
        print(f"🔄 [{process_name}] Process starting...")
        
        # Загружаем класс процесса в дочернем процессе
        # Это важно для Windows, где объекты классов не могут быть сериализованы
        import importlib
        try:
            module_path, class_name = class_path.rsplit('.', 1)
            module = importlib.import_module(module_path)
            process_class = getattr(module, class_name)
        except (ImportError, AttributeError, ValueError) as e:
            print(f"❌ [{process_name}] Failed to load process class '{class_path}': {e}")
            import traceback
            traceback.print_exc()
            return
        
        # SharedResourcesManager передается напрямую из основного процесса
        # БЕЗ создания нового Manager() - Queue и Event сериализуемы сами по себе
        # Если shared_resources не передан, создаем новый (для обратной совместимости)
        if shared_resources is None:
            print(f"⚠️ [{process_name}] SharedResourcesManager not provided, creating new one")
            shared_resources = SharedResourcesManager()
        
        # Получаем ProcessData с конфигурацией процесса
        process_data = shared_resources.get_process_data(process_name)
        if process_data is None:
            print(f"⚠️ [{process_name}] ProcessData not found, creating default")
            # Регистрируем процесс с дефолтной конфигурацией
            shared_resources.register_process_state(process_name)
            process_data = shared_resources.get_process_data(process_name)
        
        # Получаем конфигурацию процесса из ProcessData
        # ConfigManager будет создан локально в ProcessCore
        process_config = process_data.config.process if process_data else {}
        
        # Настраиваем перенаправление stdout/stderr если есть queue соединение(я)
        redirector = None
        if process_data and process_data.custom:
            try:
                from ...Console_module.redirector import ConsoleRedirector
                import sys
                
                # Новый формат: список queues для дублирования
                if 'console_queues' in process_data.custom:
                    output_queues = process_data.custom['console_queues']
                    redirector = ConsoleRedirector(output_queues, process_name)
                    sys.stdout = redirector
                    sys.stderr = redirector
                    print(f"🖥️ [{process_name}] Console redirect enabled ({len(output_queues)} console(s))")
                # Старый формат для обратной совместимости
                elif 'console_queue' in process_data.custom:
                    output_queue = process_data.custom['console_queue']
                    redirector = ConsoleRedirector(output_queue, process_name)
                    sys.stdout = redirector
                    sys.stderr = redirector
                    print(f"🖥️ [{process_name}] Console redirect enabled (legacy format)")
            except Exception as e:
                print(f"⚠️ [{process_name}] Failed to setup console redirect: {e}")
        
        # Создаем экземпляр процесса ВНУТРИ целевого процесса
        # ConfigManager создается локально в ProcessCore
        # Конфигурация берется из process_data.config
        process_instance = process_class(
            name=process_name,
            shared_resources=shared_resources,
        )
        
        # Запускаем процесс
        process_instance.run()
        
        # Ожидаем завершения (следим за stop_event если он есть)
        while not process_instance.should_stop():
            if stop_event and stop_event.is_set():
                print(f"⚠️ [{process_name}] Stop signal received")
                process_instance.stop()
                break
            time.sleep(0.1)
        
        print(f"✅ [{process_name}] Process finished")
        
    except KeyboardInterrupt:
        print(f"⚠️ [{process_name}] Interrupted by user")
    except Exception as e:
        print(f"❌ [{process_name}] Process failed: {e}")
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
                process_instance.stop()
            except Exception as e:
                print(f"⚠️ [{process_name}] Error during cleanup: {e}")
        
        # Консоль будет закрыта автоматически при завершении процесса
