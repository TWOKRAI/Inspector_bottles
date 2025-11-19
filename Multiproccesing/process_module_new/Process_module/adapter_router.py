
# === ИНТЕГРАЦИЯ С PROCESS_MODULE ===
from typing import Dict, Any, List, Callable

from router_manager import RouterManager


class ProcessRouterAdapter:
    """
    Прагматичный адаптер для интеграции ProcessModule с RouterManager
    """
    
    def __init__(self, process_module, router_manager: RouterManager = None, logger_manager=None):
        self.process_module = process_module
        self.router_manager = router_manager or RouterManager(
            f"process_{process_module.name}", 
            logger_manager
        )
        
        # Маппинг типов сообщений на менеджеры
        self.manager_map = {
            'command': 'commands',
            'log': 'logger', 
            'worker': 'workers',
            'message': 'messages'
        }
        
        # Автоматическая настройка
        self._register_process_queues()
        self.router_manager.register_channel("process_internal", self._deliver_to_manager)

    def _register_process_queues(self):
        """Авторегистрация очередей процесса"""
        if hasattr(self.process_module, 'queues'):
            for queue_name, queue in self.process_module.queues.items():
                self.router_manager.register_receive_channel(queue_name, queue)
                self.router_manager._log("info", f"Registered process queue: {queue_name}")

    def _deliver_to_manager(self, message: Dict) -> Dict[str, Any]:
        """Умная доставка менеджерам процесса"""
        msg_type = message.get('type')
        
        manager_name = self.manager_map.get(msg_type)
        if not manager_name:
            return {'status': 'error', 'reason': f'Unknown message type: {msg_type}'}
        
        manager = self.process_module.get_manager(manager_name)
        if not manager:
            return {'status': 'error', 'reason': f'Manager not found: {manager_name}'}
        
        if not hasattr(manager, 'handle_message'):
            return {'status': 'error', 'reason': f'Manager {manager_name} has no handle_message method'}
        
        try:
            result = manager.handle_message(message)
            return {'status': 'success', 'manager': manager_name, 'result': result}
        except Exception as e:
            return {'status': 'error', 'reason': str(e)}

    # Публичные методы для делегирования к router_manager
    def send(self, message: Dict) -> Dict:
        return self.router_manager.send(message)
    
    def poll_messages(self) -> List[Dict]:
        return self.router_manager.poll_messages()
    
    def register_channel(self, name: str, handler: Callable) -> bool:
        return self.router_manager.register_channel(name, handler)

    # Управление маппингами
    def register_manager_mapping(self, msg_type: str, manager_name: str):
        self.manager_map[msg_type] = manager_name
        return True