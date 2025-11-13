import threading
import time
from typing import Dict, Callable, Optional, List
from enum import Enum
import traceback

class WorkerStatus(Enum):
    STOPPED = "stopped"
    RUNNING = "running"
    ERROR = "error"
    STOPPING = "stopping"

class ThreadPriority(Enum):
    SYSTEM = 0
    REALTIME = 1  
    NORMAL = 2
    BATCH = 3
    BACKGROUND = 4

class ThreadConfig:
    def __init__(self, 
                 priority: ThreadPriority = ThreadPriority.NORMAL,
                 restart_on_failure: bool = False,
                 max_restarts: int = 3,
                 dependencies: List[str] = None):
        self.priority = priority
        self.poll_interval = self._get_poll_interval(priority)
        self.restart_on_failure = restart_on_failure
        self.max_restarts = max_restarts
        self.dependencies = dependencies or []
    
    def _get_poll_interval(self, priority):
        intervals = {
            ThreadPriority.SYSTEM: 0.001,
            ThreadPriority.REALTIME: 0.01,
            ThreadPriority.NORMAL: 0.1,
            ThreadPriority.BATCH: 1.0,
            ThreadPriority.BACKGROUND: 5.0
        }
        return intervals[priority]

class WorkerManager:
    def __init__(self, name: str):
        self.name = name
        self.workers: Dict[str, Dict] = {}
        self.thread_configs: Dict[str, ThreadConfig] = {}
        
    def create_worker(self, 
                     worker_name: str,
                     target: Callable,
                     config: ThreadConfig,
                     auto_start: bool = False) -> bool:
        
        if worker_name in self.workers:
            return False
        
        # Проверяем зависимости
        for dep in config.dependencies:
            if dep not in self.workers or not self.is_worker_running(dep):
                return False
        
        stop_event = threading.Event()
        pause_event = threading.Event()
        
        thread = threading.Thread(
            name=f"{self.name}_{worker_name}",
            target=self._worker_wrapper,
            args=(worker_name, target, stop_event, pause_event),
            daemon=True
        )
        
        self.workers[worker_name] = {
            'thread': thread,
            'stop_event': stop_event,
            'pause_event': pause_event,
            'target': target,
            'config': config,
            'status': WorkerStatus.STOPPED,
            'restart_count': 0,
            'last_error': None
        }
        
        self.thread_configs[worker_name] = config
        
        if auto_start:
            return self.start_worker(worker_name)
        return True
    
    def _worker_wrapper(self, worker_name, target, stop_event, pause_event):
        worker_info = self.workers[worker_name]
        try:
            worker_info['status'] = WorkerStatus.RUNNING
            target(stop_event, pause_event)
        except Exception as e:
            worker_info['status'] = WorkerStatus.ERROR
            worker_info['last_error'] = str(e)
            traceback.print_exc()
        finally:
            worker_info['status'] = WorkerStatus.STOPPED
    
    def start_worker(self, worker_name: str) -> bool:
        worker_info = self.workers.get(worker_name)
        if not worker_info:
            return False
        
        if worker_info['status'] == WorkerStatus.RUNNING:
            return True
        
        worker_info['stop_event'].clear()
        worker_info['pause_event'].clear()
        worker_info['thread'].start()
        return True
    
    def stop_worker(self, worker_name: str, timeout: float = 5.0) -> bool:
        worker_info = self.workers.get(worker_name)
        if not worker_info:
            return False
        
        worker_info['status'] = WorkerStatus.STOPPING
        worker_info['stop_event'].set()
        
        if worker_info['thread'].is_alive():
            worker_info['thread'].join(timeout=timeout)
            
        worker_info['status'] = WorkerStatus.STOPPED
        return True
    
    def stop_all_workers(self):
        for worker_name in list(self.workers.keys()):
            self.stop_worker(worker_name)
    
    def is_worker_running(self, worker_name: str) -> bool:
        worker_info = self.workers.get(worker_name)
        return worker_info and worker_info['status'] == WorkerStatus.RUNNING
    
    def get_worker_status(self, worker_name: str) -> Optional[Dict]:
        worker_info = self.workers.get(worker_name)
        if not worker_info:
            return None
        
        return {
            'name': worker_name,
            'status': worker_info['status'].value,
            'is_alive': worker_info['thread'].is_alive(),
            'restart_count': worker_info['restart_count'],
            'last_error': worker_info['last_error']
        }
    
    def get_all_workers_status(self) -> Dict[str, Dict]:
        status = {}
        for worker_name in self.workers.keys():
            status[worker_name] = self.get_worker_status(worker_name)
        return status