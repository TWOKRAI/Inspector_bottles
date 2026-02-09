from multiprocessing import Process, Event
import psutil
import sys
import time
from typing import List

from Process_manager_module.queue_registey import QueueRegistry
from Process_module.process_module import ProcessModule


class ProcessManager:
    def __init__(self):
        # Флаг остановки всех процессов
        self.stop_event = Event()
        
        # Менеджер очередей
        self.queue_registry = QueueRegistry()
        
        # Список процессов (экземпляры ProcessModule)
        self.process_instances: List[ProcessModule] = []
        
        # Список процессов ОС (multiprocessing.Process)
        self.os_processes: List[Process] = []
        
        # Словарь приоритетов
        self.process_priorities = {}
        

    def _set_process_priority(self, process: Process, priority_name: str):
        """Устанавливает приоритет запущенному процессу ОС"""
        priority_map = {
            'high': psutil.HIGH_PRIORITY_CLASS,
            'normal': psutil.NORMAL_PRIORITY_CLASS,
            'low': psutil.IDLE_PRIORITY_CLASS
        }
        
        priority_value = priority_map.get(priority_name, psutil.NORMAL_PRIORITY_CLASS)
        
        try:
            p = psutil.Process(process.pid)
            p.nice(priority_value)
            print(f"Priority set: {priority_name} for {process.name}")
        except Exception as e:
            print(f"Priority error for {process.name}: {e}")

    def _process_wrapper(self, process_class, process_name: str, process_manager: 'ProcessManager'):
        """Обертка для запуска ProcessModule в отдельном процессе ОС"""
        try:
            print(f"🔄 Starting process: {process_name}")
            
            # Создаем экземпляр ProcessModule внутри процесса ОС
            process_instance = process_class(
                name=process_name, 
                process_manager=process_manager
            )
            
            # Запускаем процесс
            process_instance.run()
            
            print(f"✅ Process finished: {process_name}")
        except Exception as e:
            print(f"❌ Process {process_name} failed: {e}")
        finally:
            # Убедимся, что процесс останавливается корректно
            if 'process_instance' in locals():
                process_instance.stop()

    def create_os_process(self, process_class, name: str, priority: str = 'normal') -> Process:
        """
        Создает и настраивает процесс ОС
        :param process_class: класс процесса (ChatProcess, RouterProcess и т.д.)
        :param name: имя процесса
        :param priority: приоритет
        :return: созданный процесс ОС
        """
        process = Process(
            target=self._process_wrapper,
            args=(process_class, name, self),
            name=name
        )
        
        # Сохраняем приоритет для установки после запуска
        self.process_priorities[name] = priority
        
        return process

    def register_process(self, process: ProcessModule):
        """Регистрация ProcessModule с приоритетом"""
        self.process_instances.append(process)
        self.register_queues(process)
        
        print(f"ProcessManager: Registered process '{process.name}'")

    def register_queues(self, process: ProcessModule):
        """Регистрация очередей процесса в менеджере очередей"""
        self.queue_registry.register_process_queues(process.name, process.queues)

    def initialize_processes(self):
        """Инициализирует процессы на основе конфигурации"""
        pass
        #if self.frontend_enable:
            # # Создаем процессы чатов
            # chat_configs = [
            #     ('proc_bob', 'Bob', 'high'),
            #     ('proc_alice', 'Alice', 'high'),
            #     ('proc_mike', 'Mike', 'high')
            # ]
            
            # for proc_id, proc_name, priority in chat_configs:
            #     process = self.create_os_process(
            #         process_class=ChatProcess,
            #         name=proc_name,
            #         priority=priority
            #     )
            #     self.os_processes.append(process)
            #     print(f"✅ Initialized chat process: {proc_name}")
        
        #if self.backend_enable:
            # Создаем процесс роутера
            # process = self.create_os_process(
            #     process_class=RouterProcess,
            #     name='Router',
            #     priority='high'
            # )
            # self.os_processes.append(process)
            #print(f"✅ Initialized router process")

    def start_processes(self):
        """Запускает процессы ОС и устанавливает приоритеты"""
        print("🚀 Starting all processes...")
        
        for process in self.os_processes:
            process.start()
            
            # Установка приоритета после запуска - ДА, ЭТО ПРАВИЛЬНО!
            # Даем процессу немного времени на инициализацию
            time.sleep(0.1)
            
            # Устанавливаем приоритет процесса ОС
            priority = self.process_priorities.get(process.name, 'normal')
            self._set_process_priority(process, priority)
            
            print(f"✅ Started OS process: {process.name} (PID: {process.pid})")

    def join_processes(self):
        """Ожидает завершения процессов ОС"""
        for process in self.os_processes:
            try:
                process.join(timeout=5)  # Таймаут 5 секунд
                if process.is_alive():
                    print(f"⚠️ Process {process.name} is still alive after join timeout")
            except Exception as e:
                print(f"Error joining process {process.name}: {e}")

    def stop_processes(self):
        """Корректно останавливает все процессы"""
        print("🛑 Stopping all processes...")
        
        # Сначала останавливаем логику процессов (если доступно)
        for process in self.process_instances:
            try:
                if hasattr(process, 'stop'):
                    process.stop()
            except Exception as e:
                print(f"Error stopping process logic {process.name}: {e}")
        
        # Затем ждем завершения процессов ОС
        self.join_processes()
        
        # Если процессы все еще живы, завершаем принудительно
        for process in self.os_processes:
            if process.is_alive():
                print(f"⚠️ Terminating process {process.name}")
                process.terminate()
        
        print("✅ All processes stopped")

    def wait_for_processes(self):
        """Ожидание завершения всех процессов"""
        try:
            # Ждем бесконечно
            while any(p.is_alive() for p in self.os_processes):
                time.sleep(0.1)
        except KeyboardInterrupt:
            print("\n🛑 Interrupted by user")
            self.stop_processes()




# import math 

# def lagrange(num):
#    d, c = math.modf(math.sqrt(num))

#     if d > 0:
#         return num - c**2 
#     else:
#         return 0 


# 1020 = 31  7  3 1