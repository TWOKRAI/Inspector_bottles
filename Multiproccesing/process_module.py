import threading
import queue
import time
import logging
import logging.handlers
from enum import Enum
from typing import Dict, Any, List, Optional
import json
import inspect


class WorkerCommand(Enum):
    START = "start_worker"
    STOP = "stop_worker"
    RESTART = "restart_worker"
    SHUTDOWN = "shutdown"
    GET_PARAMS = "get_params"
    SET_PARAMS = "set_params"
    EXECUTE = "execute"
    # Новые команды для логирования и мониторинга
    ENABLE_LOGGING = "enable_logging"
    DISABLE_LOGGING = "disable_logging"
    SET_LOG_LEVEL = "set_log_level"
    SET_LOG_HANDLER = "set_log_handler"
    GET_LOGS = "get_logs"
    GET_ATTRIBUTES = "get_attributes"
    SET_ATTRIBUTE = "set_attribute"
    GET_STATS = "get_stats"
    GET_HEALTH = "get_health"



class ProcessModule:
    def __init__(self, name='Process', queue_manager=None, control_queue=None, 
                 enable_worker_management=True, auto_start_workers=False,
                 enable_logging=True, log_level=logging.INFO):
        self.name = name
        self.queue_manager = queue_manager
        self.control_queue = control_queue
        
        self.stop_process = False
        self.local_controls_parameters = {}
        self.threads = []
        
        # Управление worker'ами
        self.enable_worker_management = enable_worker_management
        self.auto_start_workers = auto_start_workers
        self.workers = {}
        
        # Очереди для команд
        self.cmd_queue = queue.Queue() if enable_worker_management else None
        self.response_queue = queue.Queue() if enable_worker_management else None
        
        # Система логирования
        self.enable_logging = enable_logging
        self.log_level = log_level
        self.log_handlers = {}
        self.log_buffer = []  # Буфер для хранения последних логов
        self.max_log_buffer_size = 1000
        
        # Статистика и мониторинг
        self.stats = {
            'start_time': time.time(),
            'processed_frames': 0,
            'errors': 0,
            'warnings': 0,
            'last_error': None,
            'performance': {}
        }
        
        # Инициализация систем
        self._init_logging()
        self._init_base_threads()
        
        self.logger.info(f"Process {self.name} initialized")


    def _init_base_threads(self):
        """Инициализация обязательных потоков"""
        self.register_thread(
            name="control_thread", 
            target=self._control_threading
        )
        
        # Если управление worker'ами отключено, используем стандартный main_thread
        if not self.enable_worker_management:
            self.register_thread(
                name="main_thread", 
                target=self._main_threading
            )
        else:
            # Регистрируем worker management thread
            self.register_thread(
                name="worker_management_thread",
                target=self._worker_management_threading
            )
            
            # Автоматически запускаем workers если нужно
            if self.auto_start_workers:
                self._register_default_workers()


    def _init_logging(self):
        """Инициализация системы логирования"""
        if not self.enable_logging:
            return
            
        # Создаем логгер
        self.logger = logging.getLogger(f"ProcessModule.{self.name}")
        self.logger.setLevel(self.log_level)
        
        # Убираем стандартные обработчики
        for handler in self.logger.handlers[:]:
            self.logger.removeHandler(handler)
        
        # Добавляем обработчик по умолчанию - буфер в памяти
        self._add_log_handler('buffer', self._create_buffer_handler())
        
        # Добавляем консольный обработчик по умолчанию
        self._add_log_handler('console', self._create_console_handler())
        
        self.logger.debug("Logging system initialized")


    def _register_default_workers(self):
        """Регистрация workers по умолчанию (может быть переопределена)"""
        # Базовый worker, который просто вызывает main()
        self.register_worker(
            name="main_worker",
            target=self._main_worker_loop,
            auto_start=True
        )


    def register_thread(self, name, target, daemon=False):
        """Регистрация нового потока"""
        thread = threading.Thread(
            name=f"{self.name}_{name}",
            target=target,
            daemon=daemon
        )
        self.threads.append(thread)
        return thread
    

    def register_worker(self, name, target, auto_start=False, daemon=True):
        """Регистрация управляемого worker'а"""
        if not self.enable_worker_management:
            raise RuntimeError("Worker management is disabled for this process")
        
        worker = {
            'thread': None,
            'stop_event': threading.Event(),
            'target': target,
            'auto_start': auto_start,
            'daemon': daemon,
            'running': False
        }
        self.workers[name] = worker
        
        # Автозапуск если требуется
        if auto_start:
            self._start_worker(name)


    def _start_worker(self, worker_name):
        """Запуск worker'а"""
        if worker_name not in self.workers:
            return False
            
        worker = self.workers[worker_name]
        if worker['running']:
            return True
            
        worker['stop_event'].clear()
        thread = threading.Thread(
            name=f"{self.name}_worker_{worker_name}",
            target=self._worker_wrapper,
            args=(worker_name,),
            daemon=worker['daemon']
        )
        worker['thread'] = thread
        worker['running'] = True
        thread.start()
        return True


    def _stop_worker(self, worker_name, timeout=5.0):
        """Остановка worker'а"""
        if worker_name not in self.workers:
            return False
            
        worker = self.workers[worker_name]
        if not worker['running']:
            return True
            
        worker['stop_event'].set()
        if worker['thread'] and worker['thread'].is_alive():
            worker['thread'].join(timeout=timeout)
            if worker['thread'].is_alive():
                return False
                
        worker['running'] = False

        return True


    def _restart_worker(self, worker_name):
        """Перезапуск worker'а"""
        self._stop_worker(worker_name)
        time.sleep(0.1)
        return self._start_worker(worker_name)


    def _worker_wrapper(self, worker_name):
        """Обертка для выполнения worker'а с обработкой исключений"""
        worker = self.workers[worker_name]
        try:
            worker['target'](worker['stop_event'])
        except Exception as e:
            print(f"Worker {worker_name} error: {e}")
            import traceback
            traceback.print_exc()
        finally:
            worker['running'] = False


    def _main_worker_loop(self, stop_event):
        """Цикл основного worker'а по умолчанию"""
        while not stop_event.is_set() and not self.should_stop():
            self.main()


    def run(self):
        """Запуск всех зарегистрированных потоков и worker'ов"""
        # Сначала запускаем автоматически стартующих worker'ов
        if self.enable_worker_management:
            for worker_name, worker in self.workers.items():
                if worker['auto_start'] and not worker['running']:
                    self._start_worker(worker_name)
        
        # Затем запускаем основные потоки
        for thread in self.threads:
            thread.start()


    def stop(self):
        """Корректная остановка всех потоков и worker'ов"""
        self.stop_process = True
        
        # Останавливаем всех worker'ов
        if self.enable_worker_management:
            for worker_name in list(self.workers.keys()):
                self._stop_worker(worker_name)
        
        # Останавливаем основные потоки
        for thread in self.threads:
            if thread.is_alive():
                thread.join(timeout=1.0)


    def _control_threading(self):
        """Поток обработки управляющих команд"""
        while not self.should_stop():
            try:
                if self.control_queue is not None:
                    controls_parameters = self.control_queue.get(timeout=1)
                    self._update_parameters(controls_parameters)
                else:
                    break
            except queue.Empty:
                pass


    def _worker_management_threading(self):
        """Поток управления worker'ами через команды"""
        while not self.should_stop():
            try:
                # Команды из внешней очереди
                if self.control_queue is not None:
                    cmd = self.control_queue.get(timeout=0.1)
                    self._handle_command(cmd)
                
                # Команды из внутренней очереди
                if self.cmd_queue is not None:
                    cmd = self.cmd_queue.get(timeout=0.1)
                    self._handle_command(cmd)
                    
            except queue.Empty:
                continue
            except Exception as e:
                print(f"Error in worker management: {e}")


    def _handle_command(self, cmd):
        """Обработка команд управления"""
        command = cmd.get('command')
        worker_name = cmd.get('worker_name')
        
        if command == WorkerCommand.START.value:
            success = self._start_worker(worker_name)
            self._send_response({'status': 'started' if success else 'error', 'worker': worker_name})
            
        elif command == WorkerCommand.STOP.value:
            success = self._stop_worker(worker_name)
            self._send_response({'status': 'stopped' if success else 'error', 'worker': worker_name})
            
        elif command == WorkerCommand.RESTART.value:
            success = self._restart_worker(worker_name)
            self._send_response({'status': 'restarted' if success else 'error', 'worker': worker_name})
            
        elif command == WorkerCommand.SHUTDOWN.value:
            self.stop()
            self._send_response({'status': 'shutdown'})
            
        elif command == WorkerCommand.GET_PARAMS.value:
            params = self._get_current_params()
            self._send_response({'status': 'success', 'parameters': params})
            
        elif command == WorkerCommand.SET_PARAMS.value:
            self._update_parameters(cmd.get('parameters', {}))
            self._send_response({'status': 'success', 'message': 'Parameters updated'})
            
        elif command == WorkerCommand.EXECUTE.value:
            # Выполнение произвольной функции
            func_name = cmd.get('function')
            args = cmd.get('args', [])
            kwargs = cmd.get('kwargs', {})
            result = self._execute_function(func_name, *args, **kwargs)
            self._send_response({'status': 'executed', 'result': result})
            
        else:
            self._send_response({'status': 'error', 'error': f'Unknown command: {command}'})

    def _send_response(self, response):
        """Отправка ответа"""
        if self.response_queue is not None:
            self.response_queue.put(response)

    def _get_current_params(self):
        """Получение текущих параметров"""
        return self.local_controls_parameters.copy()

    def _execute_function(self, func_name, *args, **kwargs):
        """Выполнение произвольной функции"""
        try:
            if hasattr(self, func_name):
                func = getattr(self, func_name)
                return func(*args, **kwargs)
            else:
                return f"Function {func_name} not found"
        except Exception as e:
            return f"Error executing {func_name}: {str(e)}"

    def _update_parameters(self, incoming_parameters):
        """Обновление внутренних параметров"""
        for key, value in incoming_parameters.items():
            if key in self.local_controls_parameters:
                self.local_controls_parameters[key] = value
        self.get_parameters()

    def get_parameters(self):
        """Метод для обработки обновленных параметров (должен быть переопределен)"""
        pass

    def _main_threading(self):
        """Основной рабочий поток (используется когда управление worker'ами отключено)"""
        while not self.should_stop():
            self.main()

    def main(self):
        """Основная логика обработки (должна быть переопределена)"""
        pass


    def should_stop(self):
        """Проверка условий остановки"""
        return (
            self.stop_process or 
            (self.queue_manager.stop_event.is_set() 
             if self.queue_manager and hasattr(self.queue_manager, 'stop_event') else False)
        )


    def send_command(self, command, **kwargs):
        """Отправка команды процессу"""
        if not self.enable_worker_management:
            raise RuntimeError("Worker management is disabled")
            
        cmd = {'command': command, **kwargs}
        self.cmd_queue.put(cmd)


    def get_response(self, timeout=1.0):
        """Получение ответа от процесса"""
        if not self.enable_worker_management:
            raise RuntimeError("Worker management is disabled")
            
        try:
            return self.response_queue.get(timeout=timeout)
        except queue.Empty:
            return None