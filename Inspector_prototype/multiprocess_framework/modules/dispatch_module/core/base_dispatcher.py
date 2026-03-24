"""
Лёгкий диспетчер без ObservableMixin.

Используется когда нужен минимальный диспетчер (EXACT_MATCH only) без зависимости
от BaseManager/ObservableMixin. Для production-кода используйте Dispatcher.
"""
from typing import Dict, Any, Callable, Optional, List

from ..types.types import DispatchStrategy, HandlerInfo


class BaseDispatcher:
    """
    Лёгкий конкретный диспетчер — EXACT_MATCH only, без ObservableMixin.

    Предназначен для юнит-тестов, инструментария и случаев, где зависимость
    от BaseManager избыточна. Для полной функциональности (multi-strategy,
    логирование, статистика) используйте Dispatcher.
    """

    def __init__(self, name: str, strategy: DispatchStrategy = DispatchStrategy.EXACT_MATCH):
        self.name = name
        self.strategy = strategy
        self.handlers: Dict[str, HandlerInfo] = {}

    # ------------------------------------------------------------------
    # Регистрация
    # ------------------------------------------------------------------

    def register_handler(
        self,
        key: str,
        handler: Callable,
        expects_full_message: bool = False,
        metadata: Dict[str, Any] = None,
        efficiency: int = 0,
        tags: List[str] = None
    ) -> bool:
        if key in self.handlers:
            return False
        try:
            self.handlers[key] = HandlerInfo(
                key=key,
                handler=handler,
                expects_full_message=expects_full_message,
                metadata=metadata or {},
                efficiency=efficiency,
                tags=set(tags) if tags else set()
            )
            return True
        except Exception:
            return False

    def overwrite_handler(
        self,
        key: str,
        handler: Callable,
        expects_full_message: bool = False,
        metadata: Dict[str, Any] = None,
        efficiency: int = 0,
        tags: List[str] = None
    ) -> bool:
        try:
            self.handlers[key] = HandlerInfo(
                key=key,
                handler=handler,
                expects_full_message=expects_full_message,
                metadata=metadata or {},
                efficiency=efficiency,
                tags=set(tags) if tags else set()
            )
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Обновление
    # ------------------------------------------------------------------

    def update_handler_efficiency(self, key: str, new_efficiency: int) -> bool:
        if key not in self.handlers:
            return False
        self.handlers[key].efficiency = new_efficiency
        return True

    def update_handler_metadata(self, key: str, new_metadata: Dict[str, Any]) -> bool:
        if key not in self.handlers:
            return False
        self.handlers[key].metadata = new_metadata
        return True

    def update_handler_tags(self, key: str, new_tags: List[str]) -> bool:
        if key not in self.handlers:
            return False
        self.handlers[key].tags = set(new_tags)
        return True

    def update_handler_function(self, key: str, new_handler: Callable) -> bool:
        if key not in self.handlers:
            return False
        self.handlers[key].handler = new_handler
        return True

    def update_expects_full_message(self, key: str, expects_full: bool) -> bool:
        if key not in self.handlers:
            return False
        self.handlers[key].expects_full_message = expects_full
        return True

    # ------------------------------------------------------------------
    # Диспетчеризация
    # ------------------------------------------------------------------

    def _find_handler(self, key: str) -> Optional[HandlerInfo]:
        return self.handlers.get(key)

    def dispatch(
        self,
        message: Dict[str, Any],
        key_field: str = "command",
        data_field: str = "data"
    ) -> Any:
        try:
            key = message.get(key_field)
            if not key:
                return {"status": "error", "reason": f"Key field '{key_field}' not found"}
            handler_info = self._find_handler(key)
            if not handler_info:
                return {"status": "error", "reason": f"No handler for key '{key}'"}
            handler_data = message if handler_info.expects_full_message else message.get(data_field, {})
            return handler_info.handler(handler_data)
        except Exception as e:
            return {"status": "error", "reason": f"Dispatch failed: {str(e)}"}

    # ------------------------------------------------------------------
    # Запросы
    # ------------------------------------------------------------------

    def get_handler_info(self, key: str) -> Optional[Dict]:
        if key not in self.handlers:
            return None
        h = self.handlers[key]
        return {"key": h.key, "metadata": h.metadata, "efficiency": h.efficiency,
                "tags": list(h.tags), "stage": h.stage}

    def get_all_handlers(self) -> List[Dict]:
        return [
            {"key": h.key, "metadata": h.metadata, "efficiency": h.efficiency,
             "tags": list(h.tags), "stage": h.stage}
            for h in self.handlers.values()
        ]

    def get_handlers_by_tag(self, tag: str) -> List[Dict]:
        return [
            {"key": h.key, "metadata": h.metadata, "efficiency": h.efficiency,
             "tags": list(h.tags), "stage": h.stage}
            for h in self.handlers.values() if tag in h.tags
        ]
