



"""
Примеры использования системы логирования.
"""

from logging_system import *

# 1. Инициализация
config = LogConfig.from_yaml("logging_config.yaml")
logger = init_logging(config)

# 2. Базовое использование
logger.info("Приложение запущено")
logger.error("Что-то пошло не так")

# 3. Разные области
logger.system("INFO", "Система запущена")
logger.business("INFO", "Пользователь совершил покупку") 
logger.performance("WARNING", "Медленный запрос к БД")
logger.audit("INFO", "Изменены настройки пользователя")

# 4. С контекстом
with log_context(user_id=123, request_id="abc-123"):
    logger.business("INFO", "Обработка запроса")
    
    # Вложенный контекст
    with log_context(stage="processing"):
        logger.debug("Начало обработки")

# 5. С декораторами
@log_call(scope=LogScope.BUSINESS, log_args=True, log_time=True)
def process_order(order_id: int, amount: float):
    """Пример функции с автоматическим логированием"""
    logger.business("INFO", f"Обработка заказа {order_id}")
    return True

@log_performance(threshold=0.5)
def heavy_calculation(data):
    """Функция с логированием медленных выполнений"""
    import time
    time.sleep(1)  # Имитация тяжелой операции
    return data * 2

# 6. Замер производительности
with Timer() as timer:
    # Тяжелая операция
    result = heavy_calculation(42)
logger.performance("INFO", f"Calculation took {timer.elapsed:.3f}s")

# 7. Получение статистики
print("Статистика логирования:", logger.get_stats())

# 8. Корректное завершение
shutdown_logging()