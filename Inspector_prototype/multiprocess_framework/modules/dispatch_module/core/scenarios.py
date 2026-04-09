"""Управление сценариями (CHAIN_MATCH) для Dispatcher."""

from typing import Any, Callable, Dict, List, Optional

from ..types.types import HandlerInfo, Scenario


class ScenarioManager:
    """
    Менеджер сценариев — CRUD + выполнение цепочек обработчиков.

    Используется внутри Dispatcher как композиция (не наследование).
    """

    def __init__(self) -> None:
        self._scenarios: Dict[str, Scenario] = {}

    @property
    def scenarios(self) -> Dict[str, Scenario]:
        return self._scenarios

    def has_scenario(self, name: str) -> bool:
        return name in self._scenarios

    def create_scenario(
        self,
        name: str,
        description: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Создать новый сценарий."""
        if name in self._scenarios:
            return False

        self._scenarios[name] = Scenario(
            name=name,
            description=description,
            metadata=metadata or {},
        )
        return True

    def delete_scenario(self, name: str) -> bool:
        """Удалить сценарий."""
        if name not in self._scenarios:
            return False
        del self._scenarios[name]
        return True

    def get_scenario_info(self, name: str) -> Optional[Dict[str, Any]]:
        """Получить информацию о сценарии."""
        if name not in self._scenarios:
            return None
        return self._scenarios[name].get_info()

    def get_all_scenarios(self) -> List[Dict[str, Any]]:
        """Получить информацию обо всех сценариях."""
        return [scenario.get_info() for scenario in self._scenarios.values()]

    def add_handler_to_scenario(
        self,
        scenario_name: str,
        handler_key: str,
        handler: Callable,
        stage: int,
        expects_full_message: bool = False,
        metadata: Optional[Dict[str, Any]] = None,
        tags: Optional[List[str]] = None,
    ) -> bool:
        """Добавить обработчик в сценарий на определенный этап."""
        if scenario_name not in self._scenarios:
            return False

        handler_info = HandlerInfo(
            key=handler_key,
            handler=handler,
            expects_full_message=expects_full_message,
            metadata=metadata or {},
            stage=stage,
            tags=set(tags) if tags else set(),
        )

        return self._scenarios[scenario_name].add_handler(handler_info, stage)

    def remove_handler_from_scenario(self, scenario_name: str, handler_key: str) -> bool:
        """Удалить обработчик из сценария."""
        if scenario_name not in self._scenarios:
            return False
        return self._scenarios[scenario_name].remove_handler(handler_key)

    def reorder_handler_in_scenario(
        self, scenario_name: str, handler_key: str, new_stage: int
    ) -> bool:
        """Изменить порядок обработчика в сценарии."""
        if scenario_name not in self._scenarios:
            return False
        return self._scenarios[scenario_name].reorder_handler(handler_key, new_stage)

    def update_scenario_metadata(self, scenario_name: str, metadata: Dict[str, Any]) -> bool:
        """Обновить метаданные сценария."""
        if scenario_name not in self._scenarios:
            return False
        self._scenarios[scenario_name].metadata = metadata
        return True

    def update_scenario_description(self, scenario_name: str, description: str) -> bool:
        """Обновить описание сценария."""
        if scenario_name not in self._scenarios:
            return False
        self._scenarios[scenario_name].description = description
        return True

    def dispatch_scenario(
        self,
        scenario_name: str,
        message: Dict[str, Any],
        data_field: str = "data",
        stop_on_error: bool = True,
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
        if scenario_name not in self._scenarios:
            return {"status": "error", "reason": f"Scenario '{scenario_name}' not found"}

        scenario = self._scenarios[scenario_name]
        results: Dict[str, Any] = {
            "status": "success",
            "scenario": scenario_name,
            "stages": [],
            "final_result": None,
        }

        current_data = message.get(data_field, message)

        for handler_info in scenario.handlers:
            try:
                handler_data = message if handler_info.expects_full_message else current_data
                stage_result = handler_info.handler(handler_data)

                results["stages"].append(
                    {
                        "stage": handler_info.stage,
                        "handler_key": handler_info.key,
                        "status": "success",
                        "result": stage_result,
                    }
                )

                if isinstance(stage_result, dict):
                    if "data" in stage_result:
                        current_data = stage_result["data"]
                    else:
                        current_data = stage_result
                elif not handler_info.expects_full_message:
                    current_data = stage_result

            except Exception as e:
                results["stages"].append(
                    {
                        "stage": handler_info.stage,
                        "handler_key": handler_info.key,
                        "status": "error",
                        "error": str(e),
                    }
                )

                if stop_on_error:
                    results["status"] = "error"
                    results["final_error"] = f"Stage {handler_info.stage} failed: {str(e)}"
                    return results

        if results["stages"]:
            last_stage = results["stages"][-1]
            if last_stage["status"] == "success":
                results["final_result"] = last_stage["result"]

        return results

    def clear(self) -> None:
        """Очистить все сценарии (для shutdown)."""
        self._scenarios.clear()
