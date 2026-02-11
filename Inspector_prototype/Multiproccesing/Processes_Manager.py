from multiprocessing import Process, Event
import psutil
import sys
from .Queue_Manager import QueueManager


class MultiProcessManager:
    def __init__(self):
        # Флаг остановки всех процессов
        self.stop_event = Event()
        
        # Менеджер очередей
        self.queue_manager = QueueManager()
        
        # Список процессов
        self.processes = []
        
        # Словарь приоритетов
        self.process_priorities = {}
        
        # Конфигурационные флаги
        self.ui_sdk_enable = True  # UI SDK процесс камеры
        self.camera_enable = True  # Процесс камеры (SDK)
        self.app_enable = True  # Процесс App для отображения
        self.processing_enable = True  # Процесс обработки изображений
        
        # Количество процессов для отслеживания загрузки
        self.total_processes = 0


    def import_modules(self):
        """Динамически импортирует модули процессов"""
        modules = {
            'proc_ui_sdk': 'Services.hikvision_camera.hikvision_camera.ui_camera_test_2',
            'proc_camera': 'Services.hikvision_camera.hikvision_camera.camera_process.camera_proc_2',
            'proc_app': 'Multiproccesing.Processes.process_app',
            'proc_processing': 'Multiproccesing.Processes.process_processing',
        }

        # Подсчет количества процессов для отслеживания загрузки
        # Будет установлено в initialize_processes после подсчета активных процессов

        # Динамический импорт
        imported_modules = {}
        for name, path in modules.items():
            try:
                module = __import__(path, fromlist=[name])
                imported_modules[name] = getattr(module, 'main')
            except ImportError as e:
                print(f"Module import error: {name} from {path}: {e}")
                import traceback
                traceback.print_exc()
                sys.exit(1)
            
        return imported_modules


    def _set_process_priority(self, process, priority_name):
        """Устанавливает приоритет запущенному процессу"""
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


    def create_process(self, target_func, args=(), name=None, priority=None):
        """
        Создает и настраивает процесс
        :param target_func: целевая функция
        :param args: аргументы
        :param name: имя процесса
        :param priority: приоритет
        :return: созданный процесс
        """
        process = Process(target=target_func, args=args, name=name)
        
        # Сохраняем приоритет для установки после запуска
        if priority:
            self.process_priorities[process] = priority
        
        return process


    def initialize_processes(self):
        """Инициализирует процессы на основе конфигурации"""
        modules = self.import_modules()
        
        # Подсчитываем количество процессов перед их созданием
        self.total_processes = sum([
            self.camera_enable,
            self.ui_sdk_enable,
            self.processing_enable,
            self.app_enable
        ])
        
        # Устанавливаем количество процессов для окна загрузки
        self.queue_manager.total_modules = self.total_processes
        print(f"Total processes to initialize: {self.total_processes}")

        if self.camera_enable:
            # Процесс камеры (SDK)
            camera_process = self.create_process(
                target_func=modules['proc_camera'],
                args=(self.queue_manager,),
                name='proc_camera',
                priority='high'
            )
            self.processes.append(camera_process)
            print(f"Process 'proc_camera' initialized")

        if self.ui_sdk_enable:
            # Процесс UI SDK камеры
            ui_sdk_process = self.create_process(
                target_func=modules['proc_ui_sdk'],
                args=(self.queue_manager,),
                name='proc_ui_sdk',
                priority='high'
            )
            self.processes.append(ui_sdk_process)
            print(f"Process 'proc_ui_sdk' initialized")

        if self.processing_enable:
            # Процесс обработки изображений
            processing_process = self.create_process(
                target_func=modules['proc_processing'],
                args=(self.queue_manager, self.queue_manager.control_processing),
                name='proc_processing',
                priority='high'
            )
            self.processes.append(processing_process)
            print(f"Process 'proc_processing' initialized")

        if self.app_enable:
            # Процесс App для отображения
            app_process = self.create_process(
                target_func=modules['proc_app'],
                args=(self.queue_manager, self.stop_event),
                name='proc_app',
                priority='high'
            )
            self.processes.append(app_process)
            print(f"Process 'proc_app' initialized")


    def start_processes(self):
        """Запускает процессы и устанавливает приоритеты"""
        print(f"Starting {len(self.processes)} process(es)...")
        for process in self.processes:
            process.start()
            print(f"Process '{process.name}' started (PID: {process.pid})")
            
            # Установка приоритета после запуска
            if process in self.process_priorities:
                self._set_process_priority(process, self.process_priorities[process])


    def join_processes(self):
        """Ожидает завершения процессов"""
        print("Waiting for processes to finish...")
        for process in self.processes:
            process.join()
            print(f"Process '{process.name}' finished")


    def stop_processes(self):
        """Корректно останавливает все процессы"""
        print("Stopping all processes...")
        self.queue_manager.stop_event.set()
        self.join_processes()
