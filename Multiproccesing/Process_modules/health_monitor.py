import time
import threading
from typing import Dict, List, Any, Optional, Callable, Union
from enum import Enum
from dataclasses import dataclass
from collections import defaultdict

class HealthStatus(Enum):
    HEALTHY = "healthy"          # Все системы работают нормально
    DEGRADED = "degraded"        # Некоторые системы работают с ограничениями
    UNHEALTHY = "unhealthy"      # Критические системы не работают
    UNKNOWN = "unknown"          # Состояние неизвестно

@dataclass
class HealthCheckResult:
    """Результат проверки здоровья"""
    status: HealthStatus
    message: str
    timestamp: float
    details: Dict[str, Any] = None
    error: str = None

class HealthMonitor:
    """
    Независимый менеджер для мониторинга здоровья системы.
    Отвечает только за проверку состояния и агрегацию статусов.
    """
    
    def __init__(self, name: str):
        self.name = name
        self.is_running = False
        
        # Реестр проверок здоровья
        self.health_checks: Dict[str, Dict] = {}
        
        # Результаты последних проверок
        self.last_results: Dict[str, HealthCheckResult] = {}
        
        # История проверок (для анализа трендов)
        self.check_history: Dict[str, List[HealthCheckResult]] = defaultdict(list)
        self.max_history_size = 100
        
        # Конфигурация проверок
        self.check_intervals: Dict[str, float] = {}  # Интервалы для каждой проверки
        self.default_check_interval = 30.0  # Секунды
        
        # Время последнего выполнения проверок
        self.last_check_times: Dict[str, float] = {}
        
        # Callback'и для событий изменения состояния
        self.status_change_callbacks = []
        
        # Текущий агрегированный статус
        self.overall_status = HealthStatus.UNKNOWN
        self.overall_status_since = time.time()
        
        # Блокировка для потокобезопасности
        self._lock = threading.RLock()
        
        # Пороги для автоматических действий
        self.auto_restart_threshold = 3  # Количество неудачных проверок перед действием
        
    def start(self):
        """Запуск монитора здоровья"""
        self.is_running = True
        self.overall_status = HealthStatus.HEALTHY
        self.overall_status_since = time.time()
        
        # Инициализация времени последних проверок
        current_time = time.time()
        for check_name in self.health_checks:
            self.last_check_times[check_name] = current_time
        
        self._log_event("HealthMonitor started")
        
    def stop(self):
        """Остановка монитора здоровья"""
        self.is_running = False
        self._log_event("HealthMonitor stopped")
    
    def register_health_check(self, 
                            check_name: str, 
                            check_function: Callable[[], HealthCheckResult],
                            interval: float = None,
                            critical: bool = True,
                            description: str = "") -> bool:
        """
        Регистрация проверки здоровья
        
        Args:
            check_name: Уникальное имя проверки
            check_function: Функция проверки (должна возвращать HealthCheckResult)
            interval: Интервал проверки в секундах (None = по умолчанию)
            critical: Критическая ли проверка (влияет на общий статус)
            description: Описание проверки
            
        Returns:
            bool: Успешно ли зарегистрирована проверка
        """
        with self._lock:
            if check_name in self.health_checks:
                self._log_event(f"Health check {check_name} already exists", level="WARNING")
                return False
            
            self.health_checks[check_name] = {
                'function': check_function,
                'critical': critical,
                'description': description,
                'created_time': time.time(),
                'failure_count': 0,
                'success_count': 0
            }
            
            self.check_intervals[check_name] = interval or self.default_check_interval
            self.last_check_times[check_name] = 0.0  # Никогда не выполнялась
            
            self._log_event(f"Registered health check: {check_name}")
            return True
    
    def unregister_health_check(self, check_name: str) -> bool:
        """Удаление проверки здоровья"""
        with self._lock:
            if check_name in self.health_checks:
                del self.health_checks[check_name]
                del self.check_intervals[check_name]
                if check_name in self.last_check_times:
                    del self.last_check_times[check_name]
                if check_name in self.last_results:
                    del self.last_results[check_name]
                
                self._log_event(f"Unregistered health check: {check_name}")
                return True
            return False
    
    def run_health_check(self, check_name: str) -> Optional[HealthCheckResult]:
        """
        Запуск конкретной проверки здоровья
        
        Args:
            check_name: Имя проверки для запуска
            
        Returns:
            HealthCheckResult: Результат проверки или None если проверка не найдена
        """
        with self._lock:
            if check_name not in self.health_checks:
                return None
            
            check_info = self.health_checks[check_name]
            
            try:
                # Выполняем проверку
                result = check_info['function']()
                
                # ГАРАНТИРУЕМ что у результата есть timestamp
                if not hasattr(result, 'timestamp') or result.timestamp is None:
                    result.timestamp = time.time()
                    
                # Обновляем статистику
                if result.status == HealthStatus.HEALTHY:
                    check_info['success_count'] += 1
                    check_info['failure_count'] = 0
                else:
                    check_info['failure_count'] += 1
                
                # Сохраняем результат
                self.last_results[check_name] = result
                
                # Добавляем в историю
                self._add_to_history(check_name, result)
                
                # Обновляем время последней проверки
                self.last_check_times[check_name] = time.time()
                
                self._log_event(f"Health check {check_name}: {result.status.value} - {result.message}")
                
                return result
                
            except Exception as e:
                # Ошибка при выполнении проверки
                error_result = HealthCheckResult(
                    status=HealthStatus.UNHEALTHY,
                    message=f"Check execution failed: {str(e)}",
                    timestamp=time.time(),  # ← ОБЯЗАТЕЛЬНО УСТАНОВИТЬ
                    error=str(e)
                )
                
                self.last_results[check_name] = error_result
                self._add_to_history(check_name, error_result)
                
                check_info['failure_count'] += 1
                
                self._log_event(f"Health check {check_name} failed: {e}", level="ERROR")
                return error_result
    
    def run_all_health_checks(self) -> Dict[str, HealthCheckResult]:
        """
        Запуск всех проверок здоровья
        
        Returns:
            Dict: Результаты всех проверок
        """
        with self._lock:
            results = {}
            for check_name in self.health_checks:
                results[check_name] = self.run_health_check(check_name)
            return results
    
    def run_due_health_checks(self) -> Dict[str, HealthCheckResult]:
        """
        Запуск проверок, для которых наступило время
        
        Returns:
            Dict: Результаты выполненных проверок
        """
        with self._lock:
            results = {}
            current_time = time.time()
            
            for check_name, check_info in self.health_checks.items():
                interval = self.check_intervals[check_name]
                last_check_time = self.last_check_times.get(check_name, 0)
                
                if current_time - last_check_time >= interval:
                    results[check_name] = self.run_health_check(check_name)
            
            return results
    
    def get_overall_health(self) -> Dict[str, Any]:
        """
        Получение общего статуса здоровья системы
        
        Returns:
            Dict: Агрегированный статус здоровья
        """
        with self._lock:
            # Если нет проверок, статус неизвестен
            if not self.health_checks:
                return {
                    'status': HealthStatus.UNKNOWN.value,
                    'message': 'No health checks registered',
                    'timestamp': time.time()
                }
            
            # Анализируем результаты последних проверок
            critical_checks = []
            non_critical_checks = []
            unhealthy_critical = 0
            unhealthy_non_critical = 0
            
            for check_name, check_info in self.health_checks.items():
                last_result = self.last_results.get(check_name)
                
                if check_info['critical']:
                    critical_checks.append({
                        'name': check_name,
                        'description': check_info['description'],
                        'last_result': last_result,
                        'failure_count': check_info['failure_count']
                    })
                    
                    if last_result and last_result.status != HealthStatus.HEALTHY:
                        unhealthy_critical += 1
                else:
                    non_critical_checks.append({
                        'name': check_name,
                        'description': check_info['description'],
                        'last_result': last_result,
                        'failure_count': check_info['failure_count']
                    })
                    
                    if last_result and last_result.status != HealthStatus.HEALTHY:
                        unhealthy_non_critical += 1
            
            # Определяем общий статус
            old_status = self.overall_status
            
            if unhealthy_critical > 0:
                new_status = HealthStatus.UNHEALTHY
                message = f"{unhealthy_critical} critical systems unhealthy"
            elif unhealthy_non_critical > 0:
                new_status = HealthStatus.DEGRADED
                message = f"{unhealthy_non_critical} non-critical systems degraded"
            else:
                new_status = HealthStatus.HEALTHY
                message = "All systems operational"
            
            # Проверяем изменение статуса
            if new_status != old_status:
                self.overall_status = new_status
                self.overall_status_since = time.time()
                self._fire_status_change(old_status, new_status, message)
            
            return {
                'status': new_status.value,
                'message': message,
                'timestamp': time.time(),
                'status_since': self.overall_status_since,
                'details': {
                    'total_checks': len(self.health_checks),
                    'critical_checks': {
                        'total': len(critical_checks),
                        'unhealthy': unhealthy_critical
                    },
                    'non_critical_checks': {
                        'total': len(non_critical_checks),
                        'unhealthy': unhealthy_non_critical
                    },
                    'checks': {
                        'critical': critical_checks,
                        'non_critical': non_critical_checks
                    }
                }
            }
    
    def get_check_status(self, check_name: str) -> Optional[Dict[str, Any]]:
        """Получение статуса конкретной проверки"""
        with self._lock:
            if check_name not in self.health_checks:
                return None
            
            check_info = self.health_checks[check_name]
            last_result = self.last_results.get(check_name)
            
            return {
                'name': check_name,
                'description': check_info['description'],
                'critical': check_info['critical'],
                'interval': self.check_intervals[check_name],
                'last_check_time': self.last_check_times.get(check_name),
                'failure_count': check_info['failure_count'],
                'success_count': check_info['success_count'],
                'last_result': {
                    'status': last_result.status.value if last_result else None,
                    'message': last_result.message if last_result else None,
                    'timestamp': last_result.timestamp if last_result else None,
                    'error': last_result.error if last_result else None
                } if last_result else None
            }
    
    def get_failing_checks(self) -> List[Dict[str, Any]]:
        """Получение списка неудачных проверок"""
        with self._lock:
            failing = []
            for check_name, check_info in self.health_checks.items():
                last_result = self.last_results.get(check_name)
                if last_result and last_result.status != HealthStatus.HEALTHY:
                    failing.append({
                        'name': check_name,
                        'critical': check_info['critical'],
                        'last_result': last_result,
                        'failure_count': check_info['failure_count']
                    })
            return failing
    
    def get_check_history(self, check_name: str, limit: int = 50) -> Optional[List[HealthCheckResult]]:
        """Получение истории проверок"""
        with self._lock:
            if check_name not in self.check_history:
                return None
            return self.check_history[check_name][-limit:]
    
    def set_check_interval(self, check_name: str, interval: float) -> bool:
        """Установка интервала проверки"""
        with self._lock:
            if check_name not in self.health_checks:
                return False
            self.check_intervals[check_name] = interval
            return True
    
    def reset_check_stats(self, check_name: str) -> bool:
        """Сброс статистики проверки"""
        with self._lock:
            if check_name not in self.health_checks:
                return False
            
            self.health_checks[check_name]['failure_count'] = 0
            self.health_checks[check_name]['success_count'] = 0
            return True
    
    def _add_to_history(self, check_name: str, result: HealthCheckResult):
        """Добавление результата в историю"""
        self.check_history[check_name].append(result)
        
        # Ограничиваем размер истории
        if len(self.check_history[check_name]) > self.max_history_size:
            self.check_history[check_name].pop(0)
    
    def _fire_status_change(self, old_status: HealthStatus, new_status: HealthStatus, message: str):
        """Вызов callback'ов при изменении статуса"""
        for callback in self.status_change_callbacks:
            try:
                callback(old_status, new_status, message)
            except Exception as e:
                self._log_event(f"Error in status change callback: {e}", level="ERROR")
        
        self._log_event(f"Health status changed: {old_status.value} -> {new_status.value}: {message}")
    
    def register_status_change_callback(self, callback: Callable):
        """Регистрация callback'а при изменении статуса"""
        self.status_change_callbacks.append(callback)
    
    def unregister_status_change_callback(self, callback: Callable):
        """Удаление callback'а при изменении статуса"""
        if callback in self.status_change_callbacks:
            self.status_change_callbacks.remove(callback)
    
    def _log_event(self, message: str, level: str = "INFO"):
        """Логирование событий (для интеграции с LoggerManager)"""
        print(f"[HealthMonitor {level}] {message}")
    
    # Методы для интеграции с ProcessModule
    def get_status(self) -> Dict[str, Any]:
        """Получение статуса менеджера для мониторинга"""
        with self._lock:
            overall_health = self.get_overall_health()
            
            return {
                'running': self.is_running,
                'overall_health': overall_health,
                'registered_checks': len(self.health_checks),
                'failing_checks': len(self.get_failing_checks()),
                'check_intervals': self.check_intervals.copy()
            }
    
    def is_ready(self) -> bool:
        """Проверка готовности менеджера"""
        return self.is_running
    
    @staticmethod
    def create_memory_health_check(threshold_mb: float = 500.0) -> Callable[[], HealthCheckResult]:
        """Создание проверки использования памяти"""
        def memory_check():
            try:
                import psutil
                process = psutil.Process()
                memory_mb = process.memory_info().rss / 1024 / 1024
                
                if memory_mb > threshold_mb:
                    return HealthCheckResult(
                        status=HealthStatus.DEGRADED,
                        message=f"High memory usage: {memory_mb:.1f}MB",
                        timestamp=time.time(),  # ← ДОБАВИТЬ ЭТУ СТРОКУ
                        details={'memory_mb': memory_mb, 'threshold_mb': threshold_mb}
                    )
                else:
                    return HealthCheckResult(
                        status=HealthStatus.HEALTHY,
                        message=f"Memory usage OK: {memory_mb:.1f}MB",
                        timestamp=time.time(),  # ← ДОБАВИТЬ ЭТУ СТРОКУ
                        details={'memory_mb': memory_mb}
                    )
                        
            except ImportError:
                return HealthCheckResult(
                    status=HealthStatus.UNKNOWN,
                    message="psutil not available for memory check",
                    timestamp=time.time(),  # ← ДОБАВИТЬ ЭТУ СТРОКУ
                    details={'error': 'psutil missing'}
                )
            except Exception as e:
                return HealthCheckResult(
                    status=HealthStatus.UNKNOWN,
                    message=f"Memory check failed: {str(e)}",
                    timestamp=time.time(),  # ← ДОБАВИТЬ ЭТУ СТРОКУ
                    error=str(e)
                )
        
        return memory_check

    @staticmethod
    def create_cpu_health_check(threshold_percent: float = 80.0) -> Callable[[], HealthCheckResult]:
        """Создание проверки использования CPU"""
        def cpu_check():
            try:
                import psutil
                cpu_percent = psutil.cpu_percent(interval=0.5)
                
                if cpu_percent > threshold_percent:
                    return HealthCheckResult(
                        status=HealthStatus.DEGRADED,
                        message=f"High CPU usage: {cpu_percent:.1f}%",
                        timestamp=time.time(),  # ← ДОБАВИТЬ ЭТУ СТРОКУ
                        details={'cpu_percent': cpu_percent, 'threshold_percent': threshold_percent}
                    )
                else:
                    return HealthCheckResult(
                        status=HealthStatus.HEALTHY,
                        message=f"CPU usage OK: {cpu_percent:.1f}%",
                        timestamp=time.time(),  # ← ДОБАВИТЬ ЭТУ СТРОКУ
                        details={'cpu_percent': cpu_percent}
                    )
                        
            except ImportError:
                return HealthCheckResult(
                    status=HealthStatus.UNKNOWN,
                    message="psutil not available for CPU check",
                    timestamp=time.time(),  # ← ДОБАВИТЬ ЭТУ СТРОКУ
                    details={'error': 'psutil missing'}
                )
            except Exception as e:
                return HealthCheckResult(
                    status=HealthStatus.UNKNOWN,
                    message=f"CPU check failed: {str(e)}",
                    timestamp=time.time(),  # ← ДОБАВИТЬ ЭТУ СТРОКУ
                    error=str(e)
                )
        
        return cpu_check
        



# Создание монитора здоровья
health_monitor = HealthMonitor("VideoProcessor")

# Создание пользовательских проверок
def database_connectivity_check():
    """Проверка подключения к базе данных"""
    try:
        # Имитация проверки БД
        time.sleep(0.1)
        return HealthCheckResult(
            status=HealthStatus.HEALTHY,
            message="Database connection OK",
            details={'response_time': 0.1}
        )
    except Exception as e:
        return HealthCheckResult(
            status=HealthStatus.UNHEALTHY,
            message=f"Database connection failed: {str(e)}",
            error=str(e)
        )

def external_service_check():
    """Проверка внешнего сервиса"""
    try:
        # Имитация проверки внешнего сервиса
        time.sleep(0.05)
        return HealthCheckResult(
            status=HealthStatus.HEALTHY, 
            message="External service OK",
            details={'response_time': 0.05}
        )
    except Exception as e:
        return HealthCheckResult(
            status=HealthStatus.DEGRADED,
            message=f"External service degraded: {str(e)}",
            error=str(e)
        )



if __name__ == "__main__":
    # Регистрация проверок
    health_monitor.register_health_check(
        "database",
        database_connectivity_check,
        interval=60.0,  # Проверять каждые 60 секунд
        critical=True,
        description="Database connectivity check"
    )

    health_monitor.register_health_check(
        "external_service",
        external_service_check, 
        interval=30.0,
        critical=False,
        description="External service availability check"
    )

    # Регистрация стандартных проверок
    health_monitor.register_health_check(
        "memory",
        HealthMonitor.create_memory_health_check(threshold_mb=800.0),
        interval=10.0,
        critical=True,
        description="Memory usage check"
    )

    health_monitor.register_health_check(
        "cpu",
        HealthMonitor.create_cpu_health_check(threshold_percent=90.0),
        interval=10.0,
        critical=False, 
        description="CPU usage check"
    )

    # Callback при изменении статуса
    def on_health_status_change(old_status, new_status, message):
        print(f"HEALTH STATUS CHANGED: {old_status.value} -> {new_status.value}: {message}")

    health_monitor.register_status_change_callback(on_health_status_change)

    # Запуск монитора
    health_monitor.start()

    # Ручной запуск проверок
    print("Running initial health checks...")
    results = health_monitor.run_all_health_checks()
    for check_name, result in results.items():
        print(f"{check_name}: {result.status.value} - {result.message}")

    # Получение общего статуса
    overall = health_monitor.get_overall_health()
    print(f"Overall health: {overall['status']}")

    # Мониторинг в реальном времени
    import time
    start_time = time.time()
    while time.time() - start_time < 120:  # 2 минуты
        # Запуск проверок, для которых наступило время
        health_monitor.run_due_health_checks()
        
        # Получение текущего статуса
        current_health = health_monitor.get_overall_health()
        print(f"Current health: {current_health['status']} - {current_health['message']}")
        
        # Получение неудачных проверок
        failing = health_monitor.get_failing_checks()
        if failing:
            print(f"Failing checks: {[f['name'] for f in failing]}")
        
        time.sleep(5)

    # Остановка
    health_monitor.stop()