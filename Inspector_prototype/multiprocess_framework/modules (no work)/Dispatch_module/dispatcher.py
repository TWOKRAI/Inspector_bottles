"""
Универсальный диспетчер для обработки сообщений различного типа.

Поддерживает все стратегии одновременно с автоматическим выбором:
- EXACT_MATCH: Точное совпадение ключей (по умолчанию)
- PATTERN_MATCH: Сопоставление по регулярным выражениям
- FALLBACK_MATCH: Fallback с приоритетом эффективности
- CHAIN_MATCH: Цепочки выполнения (сценарии)

Автоматический выбор стратегии:
- По полю "strategy" в сообщении
- Если ключ не найден в обработчиках - проверка сценариев
- По умолчанию используется EXACT_MATCH
"""
from typing import Dict, Any, Callable, Optional, List

from .base import BaseDispatcher
from .types import DispatchStrategy, HandlerInfo, Scenario
from .strategies import (
    ExactMatchStrategy,
    PatternMatchStrategy,
    FallbackMatchStrategy,
    ChainMatchStrategy,
    BaseStrategy
)
from ..Base_manager_module import ObservableMixin


class Dispatcher(BaseDispatcher, ObservableMixin):
    """
    Универсальный диспетчер для обработки сообщений различного типа.
    
    Поддерживает все стратегии одновременно. Автоматически выбирает стратегию
    на основе сообщения или использует стратегию по умолчанию.
    
    Пример использования:
        dispatcher = Dispatcher("my_dispatcher")
        
        # Регистрация обработчика (по умолчанию EXACT_MATCH)
        dispatcher.register_handler("process", lambda data: {"result": data})
        
        # Использование разных стратегий в одном сообщении
        result = dispatcher.dispatch({"command": "process", "data": {...}})
        result = dispatcher.dispatch({"command": "process", "strategy": "fallback", "data": {...}})
        
        # Работа со сценариями
        dispatcher.create_scenario("image_processing", "Обработка изображений")
        dispatcher.add_handler_to_scenario("image_processing", "preprocess", handler1, stage=1)
        result = dispatcher.dispatch({"command": "image_processing", "data": {...}})
        
        # С поддержкой логирования и статистики
        dispatcher = Dispatcher(
            "my_dispatcher",
            logger_manager=logger_manager,
            statistics_manager=stats_manager
        )
    """
    
    def __init__(
        self,
        name: str,
        default_strategy: DispatchStrategy = DispatchStrategy.EXACT_MATCH,
        managers: Optional[Dict[str, Any]] = None,
        config: Optional[Dict[str, Any]] = None,
        config_manager: Optional[Any] = None,
        # Обратная совместимость со старым API
        logger_manager: Optional[Any] = None,
        error_manager: Optional[Any] = None,
        statistics_manager: Optional[Any] = None,
        enable_logging: bool = True,
        enable_error_tracking: bool = True,
        enable_statistics: bool = True
    ):
        """
        Инициализация диспетчера.
        
        Args:
            name: Уникальное имя диспетчера для идентификации
            default_strategy: Стратегия по умолчанию (используется если не указана в сообщении)
            managers: Словарь менеджеров {имя: менеджер} (новый универсальный способ)
            config: Конфигурация включения/выключения функций {имя: bool}
            config_manager: Менеджер конфигурации для динамического обновления
            logger_manager: Менеджер логирования (для обратной совместимости)
            error_manager: Менеджер обработки ошибок (для обратной совместимости)
            statistics_manager: Менеджер статистики (для обратной совместимости)
            enable_logging: Включить логирование по умолчанию (для обратной совместимости)
            enable_error_tracking: Включить отслеживание ошибок по умолчанию
            enable_statistics: Включить статистику по умолчанию
        """
        BaseDispatcher.__init__(self, name, default_strategy)
        
        # Поддержка старого API для обратной совместимости
        if managers is None:
            managers = {}
            if logger_manager:
                managers['logger'] = logger_manager
            if error_manager:
                managers['error'] = error_manager
            if statistics_manager:
                managers['statistics'] = statistics_manager
        
        if config is None:
            config = {
                'logger': enable_logging,
                'error': enable_error_tracking,
                'statistics': enable_statistics
            }
        
        ObservableMixin.__init__(
            self,
            managers=managers,
            config=config
        )
        self._default_strategy = default_strategy
        
        # Инициализация всех стратегий одновременно
        self._strategies: Dict[DispatchStrategy, BaseStrategy] = {
            DispatchStrategy.EXACT_MATCH: ExactMatchStrategy(name),
            DispatchStrategy.PATTERN_MATCH: PatternMatchStrategy(name),
            DispatchStrategy.FALLBACK_MATCH: FallbackMatchStrategy(name),
            DispatchStrategy.CHAIN_MATCH: ChainMatchStrategy(name),
        }
        
        # Хранилища для каждой стратегии
        self._handlers_storage: Dict[DispatchStrategy, Any] = {
            DispatchStrategy.EXACT_MATCH: {},  # Dict[str, HandlerInfo]
            DispatchStrategy.PATTERN_MATCH: [],  # List[HandlerInfo]
            DispatchStrategy.FALLBACK_MATCH: {},  # Dict[str, List[HandlerInfo]]
            DispatchStrategy.CHAIN_MATCH: None,  # Не используется, сценарии в отдельном хранилище
        }
        
        # Отдельное хранилище сценариев (не привязано к стратегии)
        self._scenarios: Dict[str, Scenario] = {}
        
        # Для обратной совместимости
        self.handlers = self._handlers_storage[DispatchStrategy.EXACT_MATCH]
    
    @property
    def scenarios(self) -> Dict[str, Scenario]:
        """Получить доступ к сценариям (для обратной совместимости)."""
        return self._scenarios
    
    def _get_strategy_from_message(self, message: Dict[str, Any]) -> Optional[DispatchStrategy]:
        """
        Определить стратегию из сообщения.
        
        Args:
            message: Сообщение для обработки
            
        Returns:
            DispatchStrategy если указана в сообщении, None иначе
        """
        strategy_name = message.get("strategy")
        if not strategy_name:
            return None
        
        # Преобразуем строку в enum
        try:
            if isinstance(strategy_name, str):
                strategy_name = strategy_name.lower()
                for strategy in DispatchStrategy:
                    if strategy.value == strategy_name:
                        return strategy
        except (AttributeError, ValueError):
            pass
        
        return None
    
    def register_handler(
        self,
        key: str,
        handler: Callable,
        expects_full_message: bool = False,
        metadata: Dict[str, Any] = None,
        efficiency: int = 0,
        tags: List[str] = None,
        strategy: Optional[DispatchStrategy] = None
    ) -> bool:
        """
        Регистрация обработчика.
        
        Args:
            key: Уникальный ключ обработчика
            handler: Функция-обработчик
            expects_full_message: Если True, обработчик получает всё сообщение
            metadata: Дополнительные метаданные
            efficiency: Уровень эффективности обработчика (для FALLBACK_MATCH)
            tags: Список тегов для группировки
            strategy: Стратегия для регистрации (если None - регистрируется в default_strategy)
            
        Returns:
            True если регистрация успешна, False в случае ошибки
        """
        self._log_debug(f"Registering handler: {key}", module="dispatcher")
        self._record_metric("dispatcher.handler.registration.attempts", tags={"key": key})
        
        target_strategy = strategy or self._default_strategy
        
        # CHAIN_MATCH не поддерживает прямую регистрацию
        if target_strategy == DispatchStrategy.CHAIN_MATCH:
            self._log_warning(f"Cannot register handler '{key}' directly in CHAIN_MATCH strategy", module="dispatcher")
            return False
        
        strategy_impl = self._strategies[target_strategy]
        storage = self._handlers_storage[target_strategy]
        
        try:
            result = strategy_impl.register_handler(
            key=key,
            handler=handler,
            expects_full_message=expects_full_message,
            metadata=metadata,
            efficiency=efficiency,
            tags=tags,
                handlers_storage=storage
            )
            
            # Синхронизация для обратной совместимости
            if result and target_strategy == DispatchStrategy.EXACT_MATCH:
                self.handlers = self._handlers_storage[DispatchStrategy.EXACT_MATCH]
            
            if result:
                self._log_info(f"Handler '{key}' registered successfully", module="dispatcher")
                self._record_metric("dispatcher.handler.registration.success", tags={"key": key})
            else:
                self._log_warning(f"Failed to register handler '{key}'", module="dispatcher")
                self._record_metric("dispatcher.handler.registration.failed", tags={"key": key})
            
            return result
        except Exception as e:
            self._log_error(f"Error registering handler '{key}': {str(e)}", module="dispatcher")
            self._track_error(e, {"key": key, "strategy": target_strategy.value})
            self._record_metric("dispatcher.handler.registration.errors", tags={"key": key})
            return False
    
    def _find_handler_in_strategy(
        self,
        key: str,
        strategy: DispatchStrategy
    ) -> Optional[HandlerInfo]:
        """Поиск обработчика в конкретной стратегии."""
        strategy_impl = self._strategies[strategy]
        storage = self._handlers_storage[strategy]
        
        if strategy == DispatchStrategy.CHAIN_MATCH:
            # Для CHAIN_MATCH используем scenarios
            storage = self._strategies[DispatchStrategy.CHAIN_MATCH]
        
        return strategy_impl.find_handler(key, storage)
    
    def _find_handler(self, key: str) -> Optional[HandlerInfo]:
        """
        Поиск обработчика по всем стратегиям.
        
        Порядок проверки:
        1. EXACT_MATCH (самый быстрый)
        2. FALLBACK_MATCH
        3. PATTERN_MATCH
        4. CHAIN_MATCH (сценарии)
        """
        # 1. EXACT_MATCH
        handler = self._find_handler_in_strategy(key, DispatchStrategy.EXACT_MATCH)
        if handler:
            return handler
        
        # 2. FALLBACK_MATCH
        handler = self._find_handler_in_strategy(key, DispatchStrategy.FALLBACK_MATCH)
        if handler:
            return handler
        
        # 3. PATTERN_MATCH
        handler = self._find_handler_in_strategy(key, DispatchStrategy.PATTERN_MATCH)
        if handler:
            return handler
        
        # 4. Проверка сценариев
        if key in self._scenarios:
            # Возвращаем специальный маркер для сценария
            return HandlerInfo(
                key=key,
                handler=lambda x: x,  # Заглушка, реальное выполнение в dispatch
                metadata={"is_scenario": True}
            )
        
        return None
    
    def dispatch(
        self,
        message: Dict[str, Any],
        key_field: str = "command",
        data_field: str = "data"
    ) -> Any:
        """
        Диспетчеризация с автоматическим выбором стратегии.
        
        Логика выбора:
        1. Если в сообщении есть поле "strategy" - используется указанная стратегия
        2. Если ключ не найден в обработчиках - проверка сценариев
        3. Иначе используется стратегия по умолчанию
        
        Args:
            message: Сообщение для обработки
            key_field: Поле в сообщении, содержащее ключ диспетчеризации
            data_field: Поле в сообщении, содержащее данные для обработки
            
        Returns:
            Результат работы обработчика или словарь с ошибкой
        """
        import time
        start_time = time.time()
        
        try:
            key = message.get(key_field)
            if not key:
                error_msg = f"Key field '{key_field}' not found"
                self._log_warning(error_msg, module="dispatcher")
                self._record_metric("dispatcher.dispatch.errors", tags={"error": "missing_key"})
                return {"status": "error", "reason": error_msg}
            
            self._log_debug(f"Dispatching message with key '{key}'", module="dispatcher", key=key)
            self._record_metric("dispatcher.dispatch.attempts", tags={"key": key})
            
            # 1. Проверка на явное указание сценария в сообщении
            explicit_scenario = message.get("scenario")
            if explicit_scenario and explicit_scenario in self._scenarios:
                self._log_debug(f"Executing scenario '{explicit_scenario}'", module="dispatcher")
                result = self.dispatch_scenario(explicit_scenario, message, data_field)
                duration = time.time() - start_time
                self._record_timing("dispatcher.dispatch.scenario.duration", duration, tags={"scenario": explicit_scenario})
                return result
            
            # 2. Проверка на сценарий по ключу (если ключ является сценарием)
            if key in self._scenarios:
                self._log_debug(f"Executing scenario '{key}'", module="dispatcher")
                result = self.dispatch_scenario(key, message, data_field)
                duration = time.time() - start_time
                self._record_timing("dispatcher.dispatch.scenario.duration", duration, tags={"scenario": key})
                return result
            
            # 3. Определение стратегии из сообщения
            requested_strategy = self._get_strategy_from_message(message)
            
            # 4. Поиск обработчика
            if requested_strategy:
                # Если стратегия указана явно - ищем только в ней
                handler_info = self._find_handler_in_strategy(key, requested_strategy)
            else:
                # Иначе ищем по всем стратегиям
                handler_info = self._find_handler(key)
            
            if not handler_info:
                error_msg = f"No handler for key '{key}'"
                self._log_warning(error_msg, module="dispatcher", key=key)
                self._record_metric("dispatcher.dispatch.errors", tags={"error": "handler_not_found", "key": key})
                return {"status": "error", "reason": error_msg}
            
            # 5. Выполнение обработчика
            handler_data = message if handler_info.expects_full_message else message.get(data_field, {})
            result = handler_info.handler(handler_data)
            
            duration = time.time() - start_time
            self._log_debug(f"Dispatch completed for key '{key}' in {duration:.3f}s", module="dispatcher")
            self._record_timing("dispatcher.dispatch.duration", duration, tags={"key": key})
            self._record_metric("dispatcher.dispatch.success", tags={"key": key})
            
            return result
            
        except Exception as e:
            duration = time.time() - start_time
            error_msg = f"Dispatch failed: {str(e)}"
            self._log_error(error_msg, module="dispatcher", exception=str(e))
            self._track_error(e, {"key": key, "message": str(message)})
            self._record_timing("dispatcher.dispatch.error_duration", duration)
            self._record_metric("dispatcher.dispatch.errors", tags={"error": "exception"})
            return {"status": "error", "reason": error_msg}
    
    # Методы для работы со сценариями
    
    def create_scenario(
        self,
        name: str,
        description: str = "",
        metadata: Dict[str, Any] = None
    ) -> bool:
        """Создать новый сценарий."""
        if name in self._scenarios:
            return False
        
        self._scenarios[name] = Scenario(
            name=name,
            description=description,
            metadata=metadata or {}
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
        metadata: Dict[str, Any] = None,
        tags: List[str] = None
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
            tags=set(tags) if tags else set()
        )
        
        return self._scenarios[scenario_name].add_handler(handler_info, stage)
    
    def remove_handler_from_scenario(self, scenario_name: str, handler_key: str) -> bool:
        """Удалить обработчик из сценария."""
        if scenario_name not in self._scenarios:
            return False
        return self._scenarios[scenario_name].remove_handler(handler_key)
    
    def reorder_handler_in_scenario(self, scenario_name: str, handler_key: str, new_stage: int) -> bool:
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
        if scenario_name not in self._scenarios:
            return {"status": "error", "reason": f"Scenario '{scenario_name}' not found"}
        
        scenario = self._scenarios[scenario_name]
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
                if isinstance(stage_result, dict):
                    # Если результат - словарь, передаем его целиком или поле data если есть
                    if "data" in stage_result:
                        current_data = stage_result["data"]
                    else:
                        current_data = stage_result
                elif not handler_info.expects_full_message:
                    # Если результат не словарь, передаем как есть
                    current_data = stage_result
                else:
                    # Если expects_full_message, оставляем текущие данные
                    pass
                
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
    
    # Методы для обновления обработчиков (работают с default_strategy)
    
    def update_handler_efficiency(self, key: str, new_efficiency: int) -> bool:
        """Обновление уровня эффективности обработчика."""
        strategy_impl = self._strategies[self._default_strategy]
        storage = self._handlers_storage[self._default_strategy]
        return strategy_impl.update_handler_efficiency(key, new_efficiency, storage)
    
    def update_handler_metadata(self, key: str, new_metadata: Dict[str, Any]) -> bool:
        """Обновление метаданных обработчика."""
        strategy_impl = self._strategies[self._default_strategy]
        storage = self._handlers_storage[self._default_strategy]
        return strategy_impl.update_handler_metadata(key, new_metadata, storage)
    
    def update_handler_tags(self, key: str, new_tags: List[str]) -> bool:
        """Обновление тегов обработчика."""
        strategy_impl = self._strategies[self._default_strategy]
        storage = self._handlers_storage[self._default_strategy]
        return strategy_impl.update_handler_tags(key, new_tags, storage)
    
    def update_handler_function(self, key: str, new_handler: Callable) -> bool:
        """Обновление функции-обработчика."""
        strategy_impl = self._strategies[self._default_strategy]
        storage = self._handlers_storage[self._default_strategy]
        return strategy_impl.update_handler_function(key, new_handler, storage)
    
    def update_expects_full_message(self, key: str, expects_full: bool) -> bool:
        """Обновление флага expects_full_message."""
        strategy_impl = self._strategies[self._default_strategy]
        storage = self._handlers_storage[self._default_strategy]
        return strategy_impl.update_expects_full_message(key, expects_full, storage)
    
    def overwrite_handler(
        self,
        key: str,
        handler: Callable,
        expects_full_message: bool = False,
        metadata: Dict[str, Any] = None,
        efficiency: int = 0,
        tags: List[str] = None
    ) -> bool:
        """Принудительная перезапись обработчика."""
        # Удаляем из всех стратегий
        for strategy, storage in self._handlers_storage.items():
            if strategy == DispatchStrategy.EXACT_MATCH and key in storage:
                del storage[key]
            elif strategy == DispatchStrategy.PATTERN_MATCH:
                storage[:] = [h for h in storage if h.key != key]
            elif strategy == DispatchStrategy.FALLBACK_MATCH and key in storage:
                del storage[key]
        
        # Регистрируем в default_strategy
        return self.register_handler(
            key=key,
            handler=handler,
            expects_full_message=expects_full_message,
            metadata=metadata,
            efficiency=efficiency,
            tags=tags
        )
    
    def get_handler_info(self, key: str) -> Optional[Dict]:
        """Получение информации о конкретном обработчике."""
        handler_info = self._find_handler(key)
        if not handler_info:
            return None
        
        return {
            "key": handler_info.key,
            "metadata": handler_info.metadata,
            "efficiency": handler_info.efficiency,
            "tags": list(handler_info.tags),
            "stage": handler_info.stage
        }
    
    def get_all_handlers(self) -> List[Dict]:
        """Получение информации обо всех обработчиках из всех стратегий."""
        all_handlers = []
        
        for strategy, storage in self._handlers_storage.items():
            if strategy == DispatchStrategy.CHAIN_MATCH:
                continue  # Сценарии обрабатываются отдельно
            
            strategy_impl = self._strategies[strategy]
            handlers = strategy_impl.get_all_handlers(storage)
            all_handlers.extend(handlers)
        
        return all_handlers
    
    def get_handlers_by_tag(self, tag: str) -> List[Dict]:
        """Получение обработчиков по тегу из всех стратегий."""
        all_handlers = []
        
        for strategy, storage in self._handlers_storage.items():
            if strategy == DispatchStrategy.CHAIN_MATCH:
                continue
            
            strategy_impl = self._strategies[strategy]
            handlers = strategy_impl.get_handlers_by_tag(tag, storage)
            all_handlers.extend(handlers)
        
        return all_handlers
