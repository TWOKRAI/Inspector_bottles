from Process_manager_module.Processes_Manager import ProcessManager
from Process_manager_module.main_launcher import SystemLauncher
from Process_module.process_module import ProcessModule
from Test_example.pyqt_example_3 import ChatProcess


class ProcessManager2(ProcessManager):
    def __init__(self):
        super().__init__()
        # Конфигурационные флаги
        self.frontend_enable = True
        self.backend_enable = True


    def initialize_processes(self):
        """Инициализирует процессы на основе конфигурации"""

        if self.frontend_enable:
            # Создаем процессы чатов
            chat_configs = [
                ('proc_bob', 'Bob', 'high'),
                ('proc_alice', 'Alice', 'high'),
                ('proc_mike', 'Mike', 'high')
            ]
            
            for proc_id, proc_name, priority in chat_configs:
                process = self.create_os_process(
                    process_class=ChatProcess,
                    name=proc_name,
                    priority=priority
                )
                self.os_processes.append(process)
                print(f"✅ Initialized chat process: {proc_name}")

