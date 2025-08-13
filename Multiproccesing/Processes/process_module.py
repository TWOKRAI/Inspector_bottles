import threading


class ProcessModule:
    def __init__(self, queue_manager):
        self.queue_manager = queue_manager
        self.stop_process = False
        self.local_controls_parameters = {}
        self.threads = [] 
        self.control_queue = None
        
        # Инициализация базовых потоков
        self._init_base_threads()
        
    def _init_base_threads(self):
        """Инициализация обязательных потоков (может быть переопределена)"""
        self.register_thread(
            name="control_thread", 
            target=self._control_threading
        )
        self.register_thread(
            name="main_thread", 
            target=self._main_threading
        )
    
    def register_thread(self, name, target, daemon=False):
        """Регистрация нового потока"""
        thread = threading.Thread(
            name=name,
            target=target,
            daemon=daemon
        )
        self.threads.append(thread)
        return thread

    def run(self):
        """Запуск всех зарегистрированных потоков"""
        for thread in self.threads:
            thread.start()

    def stop(self):
        """Корректная остановка всех потоков"""
        self.stop_process = True  # Устанавливаем флаг остановки
        
        # Ожидаем завершения всех потоков
        for thread in self.threads:
            if thread.is_alive():
                thread.join(timeout=1.0)

    def _control_threading(self):
        """Поток обработки управляющих команд"""
        while not self.should_stop():
            controls_parameters = self.queue_manager.control_capture.get(timeout=1)
            if not self.queue_manager.control_capture.empty():
                self._update_parameters(controls_parameters)

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
        """Основной рабочий поток"""
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
             if self.queue_manager.stop_event else False)
        )
