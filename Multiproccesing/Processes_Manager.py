from multiprocessing import Process, Event
import psutil
import sys
from Multiproccesing.Queue_Manager import QueueManager


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
        self.frontend_enable = True
        self.ui_enable = False
        self.render_enable = True
        
        self.backend_enable = True
        self.capture_enable = True
        self.processing_enable = True
        self.cap_level_enable = True
        self.communication_enable = False
        self.graph_enable = True


    def import_modules(self):
        """Динамически импортирует модули процессов"""
        modules = {
            'proc_ui': 'Multiproccesing.Processes.ui_module',
            'proc_capture': 'Multiproccesing.Processes.capture_module',
            'proc_processing': 'Multiproccesing.Processes.processing_module',
            'proc_cap_level': 'Multiproccesing.Processes.operation_cap_level',
            'proc_render': 'Multiproccesing.Processes.render_module',
            'proc_communication': 'Multiproccesing.Processes.communication_module', 
            'proc_graph': 'Multiproccesing.Processes.graph_module', 
        }

        # Настройка счетчика модулей
        self.queue_manager.total_modules = len(modules)

        # Динамический импорт
        imported_modules = {}
        for name, path in modules.items():
            try:
                module = __import__(path, fromlist=[name])
                imported_modules[name] = getattr(module, 'main')
            except ImportError as e:
                print(f"Module import error: {name} from {path}: {e}")
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

        if self.frontend_enable:
            if self.ui_enable:
                # Процесс пользовательского интерфейса
                ui_process = self.create_process(
                    target_func=modules['proc_ui'],
                    args=(self.queue_manager,),
                    name='proc_ui',
                    priority='high'
                )
                self.processes.append(ui_process)
                
            if self.render_enable:
                # Процесс визуализации
                render_process = self.create_process(
                    target_func=modules['proc_render'],
                    args=(self.queue_manager, self.queue_manager.control_render),
                    name='proc_render',
                    priority='high'
                )
                self.processes.append(render_process)

        # Бэкенд-процессы
        if self.backend_enable:
            # Процесс захвата видео
            if self.capture_enable:
                capture_process = self.create_process(
                    target_func=modules['proc_capture'],
                    args=(self.queue_manager, self.queue_manager.control_capture),
                    name='proc_capture',
                    priority='high'
                )
                self.processes.append(capture_process)

            # Процесс обработки данных
            if self.processing_enable:
                processing_process = self.create_process(
                    target_func=modules['proc_processing'],
                    args=(self.queue_manager, self.queue_manager.control_processing),
                    name='proc_processing',
                    priority='high'
                )
                self.processes.append(processing_process)

            if self.cap_level_enable:
                cap_level_process_1 = self.create_process(
                    target_func=modules['proc_cap_level'],
                    args=(self.queue_manager, 
                            self.queue_manager.control_cap_level_1,
                            self.queue_manager.input_cap_level_1,
                            1,
                            ),

                    name='proc_cap_level_1',
                    priority='high'
                )
                self.processes.append(cap_level_process_1)

                cap_level_process_2 = self.create_process(
                    target_func=modules['proc_cap_level'],
                    args=(self.queue_manager, 
                            self.queue_manager.control_cap_level_2,
                            self.queue_manager.input_cap_level_2,
                            2
                            ),
                    name='proc_cap_level_2',
                    priority='high'
                )
                self.processes.append(cap_level_process_2)

                cap_level_process_3 = self.create_process(
                    target_func=modules['proc_cap_level'],
                    args=(self.queue_manager, 
                            self.queue_manager.control_cap_level_3,
                            self.queue_manager.input_cap_level_3,
                            3,
                            ),
                    name='proc_cap_level_3',
                    priority='high'
                )
                self.processes.append(cap_level_process_3)
                
                cap_level_process_4 = self.create_process(
                    target_func=modules['proc_cap_level'],
                    args=(self.queue_manager, 
                            self.queue_manager.control_cap_level_4,
                            self.queue_manager.input_cap_level_4,
                            4,
                          ),
                    name='proc_cap_level_4',
                    priority='high'
                )
                self.processes.append(cap_level_process_4)

            # Процесс связи с оборудованием
            if self.communication_enable:
                communication_process = self.create_process(
                    target_func=modules['proc_communication'], 
                    args=(self.queue_manager, self.queue_manager.control_communication),
                    name='proc_communication',
                    priority='normal'
                )
                self.processes.append(communication_process)
            
            if self.graph_enable:
                graph_process = self.create_process(
                    target_func=modules['proc_graph'], 
                    args=(self.queue_manager, self.queue_manager.control_graph),
                    name='proc_graph',
                    priority='normal'
                )
                self.processes.append(graph_process)


    def start_processes(self):
        """Запускает процессы и устанавливает приоритеты"""
        for process in self.processes:
            process.start()
            
            # Установка приоритета после запуска
            if process in self.process_priorities:
                self._set_process_priority(process, self.process_priorities[process])


    def join_processes(self):
        """Ожидает завершения процессов"""
        for process in self.processes:
            process.join()


    def stop_processes(self):
        """Корректно останавливает все процессы"""
        self.join_processes()  # Ожидание завершения