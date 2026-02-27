"""
Стратегия цепочек выполнения (сценариев).
"""
from typing import Dict, Any, Callable, Optional, List

from .base_strategy import BaseStrategy
from ..types.types import HandlerInfo, Scenario


class ChainMatchStrategy(BaseStrategy):
    """
    Стратегия цепочек выполнения (сценариев).
    
    Позволяет создавать сценарии - цепочки обработчиков, которые выполняются последовательно.
    """
    
    def __init__(self, dispatcher_name: str):
        """Инициализация стратегии с хранилищем сценариев."""
        super().__init__(dispatcher_name)
        self.scenarios: Dict[str, Scenario] = {}
    
    def register_handler(
        self,
        key: str,
        handler: Callable,
        expects_full_message: bool = False,
        metadata: Dict[str, Any] = None,
        efficiency: int = 0,
        tags: List[str] = None,
        handlers_storage: Any = None
    ) -> bool:
        """
        Регистрация обработчика.
        
        Для CHAIN_MATCH обработчики регистрируются через сценарии,
        поэтому эта функция не используется напрямую.
        """
        # Для CHAIN_MATCH обработчики добавляются через add_handler_to_scenario
        return False
    
    def find_handler(self, key: str, handlers_storage: Any) -> Optional[HandlerInfo]:
        """Поиск обработчика в сценариях."""
        for scenario in self.scenarios.values():
            for handler in scenario.handlers:
                if handler.key == key:
                    return handler
        return None
    
    def get_all_handlers(self, handlers_storage: Any) -> List[Dict]:
        """Получить все обработчики из всех сценариев."""
        all_handlers = []
        for scenario in self.scenarios.values():
            all_handlers.extend(scenario.handlers)
        
        return [
            {
                "key": h.key,
                "metadata": h.metadata,
                "efficiency": h.efficiency,
                "tags": list(h.tags),
                "stage": h.stage
            }
            for h in all_handlers
        ]
    
    def get_handlers_by_tag(self, tag: str, handlers_storage: Any) -> List[Dict]:
        """Получить обработчики по тегу из всех сценариев."""
        all_handlers = []
        for scenario in self.scenarios.values():
            all_handlers.extend(scenario.handlers)
        
        return [
            {
                "key": h.key,
                "metadata": h.metadata,
                "efficiency": h.efficiency,
                "tags": list(h.tags),
                "stage": h.stage
            }
            for h in all_handlers if tag in h.tags
        ]
    
    def create_scenario(
        self,
        name: str,
        description: str = "",
        metadata: Dict[str, Any] = None
    ) -> bool:
        """Создать новый сценарий."""
        if name in self.scenarios:
            print(f"ChainMatchStrategy {self.dispatcher_name}: Scenario '{name}' already exists.")
            return False
        
        self.scenarios[name] = Scenario(
            name=name,
            description=description,
            metadata=metadata or {}
        )
        return True
    
    def delete_scenario(self, name: str) -> bool:
        """Удалить сценарий."""
        if name not in self.scenarios:
            return False
        del self.scenarios[name]
        return True
    
    def get_scenario_info(self, name: str) -> Optional[Dict[str, Any]]:
        """Получить информацию о сценарии."""
        if name not in self.scenarios:
            return None
        return self.scenarios[name].get_info()
    
    def get_all_scenarios(self) -> List[Dict[str, Any]]:
        """Получить информацию обо всех сценариях."""
        return [scenario.get_info() for scenario in self.scenarios.values()]
    
    def add_handler_to_scenario(
        self,
        scenario_name: str,
        handler_key: str,
        handler: Callable,
        stage: int,
        expects_full_message: bool = False,
        metadata: Dict[str, Any] = None,
        tags: List[str] = None
    ) -> bool:
        """Добавить обработчик в сценарий."""
        if scenario_name not in self.scenarios:
            print(f"ChainMatchStrategy {self.dispatcher_name}: Scenario '{scenario_name}' not found.")
            return False
        
        handler_info = HandlerInfo(
            key=handler_key,
            handler=handler,
            expects_full_message=expects_full_message,
            metadata=metadata or {},
            stage=stage,
            tags=set(tags) if tags else set()
        )
        
        return self.scenarios[scenario_name].add_handler(handler_info, stage)
    
    def remove_handler_from_scenario(self, scenario_name: str, handler_key: str) -> bool:
        """Удалить обработчик из сценария."""
        if scenario_name not in self.scenarios:
            return False
        return self.scenarios[scenario_name].remove_handler(handler_key)
    
    def reorder_handler_in_scenario(self, scenario_name: str, handler_key: str, new_stage: int) -> bool:
        """Изменить порядок обработчика в сценарии."""
        if scenario_name not in self.scenarios:
            return False
        return self.scenarios[scenario_name].reorder_handler(handler_key, new_stage)
    
    def update_scenario_metadata(self, scenario_name: str, metadata: Dict[str, Any]) -> bool:
        """Обновить метаданные сценария."""
        if scenario_name not in self.scenarios:
            return False
        self.scenarios[scenario_name].metadata = metadata
        return True
    
    def update_scenario_description(self, scenario_name: str, description: str) -> bool:
        """Обновить описание сценария."""
        if scenario_name not in self.scenarios:
            return False
        self.scenarios[scenario_name].description = description
        return True
    
    def dispatch_scenario(
        self,
        scenario_name: str,
        message: Dict[str, Any],
        data_field: str = "data",
        stop_on_error: bool = True
    ) -> Dict[str, Any]:
        """
        Выполнить сценарий - цепочку обработчиков по порядку.
        
        Args:
            scenario_name: Имя сценария для выполнения
            message: Сообщение для обработки
            data_field: Поле в сообщении, содержащее данные
            stop_on_error: Остановить выполнение при ошибке
            
        Returns:
            Словарь с результатами выполнения всех этапов
        """
        if scenario_name not in self.scenarios:
            return {"status": "error", "reason": f"Scenario '{scenario_name}' not found"}
        
        scenario = self.scenarios[scenario_name]
        results = {
            "status": "success",
            "scenario": scenario_name,
            "stages": [],
            "final_result": None
        }
        
        current_data = message.get(data_field, message)
        
        for handler_info in scenario.handlers:
            try:
                handler_data = message if handler_info.expects_full_message else current_data
                stage_result = handler_info.handler(handler_data)
                
                results["stages"].append({
                    "stage": handler_info.stage,
                    "handler_key": handler_info.key,
                    "status": "success",
                    "result": stage_result
                })
                
                # Передаем результат предыдущего этапа следующему
                if isinstance(stage_result, dict) and "data" in stage_result:
                    current_data = stage_result["data"]
                elif not handler_info.expects_full_message:
                    current_data = stage_result
                
            except Exception as e:
                results["stages"].append({
                    "stage": handler_info.stage,
                    "handler_key": handler_info.key,
                    "status": "error",
                    "error": str(e)
                })
                
                if stop_on_error:
                    results["status"] = "error"
                    results["final_error"] = f"Stage {handler_info.stage} failed: {str(e)}"
                    return results
        
        # Последний результат становится финальным
        if results["stages"]:
            last_stage = results["stages"][-1]
            if last_stage["status"] == "success":
                results["final_result"] = last_stage["result"]
        
        return results

