"""
Стратегия цепочек выполнения (сценариев).

Хранилище сценариев и их CRUD/исполнение живут в `core/scenarios.py::ScenarioManager`
(канон, ADR-DSP-001). Эта стратегия — только адаптер интерфейса BaseStrategy для
CHAIN_MATCH: Dispatcher передаёт ей хранилище ScenarioManager как `handlers_storage`.

(Раньше класс держал собственный дубль `self.scenarios` + create/delete/dispatch_scenario
и т.п. — он заполнялся ТОЛЬКО тестами, dispatch() его не использовал. Удалён по плану
comm-system §11.9; берегли ScenarioManager-версию и ScenarioBuilder.)
"""

from typing import Dict, Any, Callable, Optional, List

from .base_strategy import BaseStrategy
from ..types.types import HandlerInfo


class ChainMatchStrategy(BaseStrategy):
    """
    Стратегия цепочек выполнения (сценариев).

    Прямая регистрация не поддерживается — обработчики живут в сценариях
    ScenarioManager, которые Dispatcher передаёт сюда через `handlers_storage`.
    """

    def register_handler(
        self,
        key: str,
        handler: Callable,
        expects_full_message: bool = False,
        metadata: Dict[str, Any] = None,
        efficiency: int = 0,
        tags: List[str] = None,
        handlers_storage: Any = None,
    ) -> bool:
        """
        Регистрация обработчика.

        Для CHAIN_MATCH обработчики регистрируются через сценарии ScenarioManager,
        поэтому эта функция не используется напрямую (Dispatcher это знает).
        """
        return False

    def find_handler(self, key: str, handlers_storage: Any) -> Optional[HandlerInfo]:
        """Поиск обработчика в сценариях по переданному хранилищу (ScenarioManager)."""
        scenarios = handlers_storage if isinstance(handlers_storage, dict) else {}
        for scenario in scenarios.values():
            for handler in scenario.handlers:
                if handler.key == key:
                    return handler
        return None

    def get_all_handlers(self, handlers_storage: Any) -> List[Dict]:
        """Получить все обработчики из всех сценариев по переданному хранилищу."""
        scenarios = handlers_storage if isinstance(handlers_storage, dict) else {}
        all_handlers = []
        for scenario in scenarios.values():
            all_handlers.extend(scenario.handlers)

        return [
            {"key": h.key, "metadata": h.metadata, "efficiency": h.efficiency, "tags": list(h.tags), "stage": h.stage}
            for h in all_handlers
        ]

    def get_handlers_by_tag(self, tag: str, handlers_storage: Any) -> List[Dict]:
        """Получить обработчики по тегу из всех сценариев по переданному хранилищу."""
        scenarios = handlers_storage if isinstance(handlers_storage, dict) else {}
        all_handlers = []
        for scenario in scenarios.values():
            all_handlers.extend(scenario.handlers)

        return [
            {"key": h.key, "metadata": h.metadata, "efficiency": h.efficiency, "tags": list(h.tags), "stage": h.stage}
            for h in all_handlers
            if tag in h.tags
        ]
