import time
import threading
from typing import Dict, List, Any, Optional, Callable, Union
from enum import Enum
import statistics
from collections import defaultdict, deque
import json

class MetricType(Enum):
    COUNTER = "counter"      # Только увеличивается (количество обработанных элементов)
    GAUGE = "gauge"          # Может увеличиваться и уменьшаться (текущая память, FPS)
    TIMING = "timing"        # Измерение времени (время обработки)
    HISTOGRAM = "histogram"  # Распределение значений (размеры очередей)

class StatsCollector:
    """
    Независимый менеджер для сбора статистики и метрик.
    Отвечает только за сбор, хранение и анализ статистических данных.
    """
    
    def __init__(self, name: str):
        self.name = name
        self.is_running = False
        
        # Хранилище метрик
        self.metrics: Dict[str, Dict] = {}
        
        # Временные ряды для метрик (скользящее окно)
        self.timeseries: Dict[str, deque] = {}
        self.default_timeseries_size = 1000
        
        # Группы метрик для организации
        self.metric_groups: Dict[str, List[str]] = defaultdict(list)
        
        # Callback'и для событий (при достижении порогов)
        self.threshold_callbacks = {}
        
        # Блокировка для потокобезопасности
        self._lock = threading.RLock()
        
        # Автоматически собираемая системная статистика
        self.system_metrics_enabled = False
        
    def start(self):
        """Запуск сборщика статистики"""
        self.is_running = True
        
        # Инициализация базовых метрик
        self._init_base_metrics()
        
        self._log_event("StatsCollector started")
        
    def stop(self):
        """Остановка сборщика статистики"""
        self.is_running = False
        self._log_event("StatsCollector stopped")
    
    def _init_base_metrics(self):
        """Инициализация базовых системных метрик"""
        # Метрики производительности
        self.register_metric("performance.uptime", MetricType.GAUGE, 
                        "Время работы в секундах", 0)
        self.register_metric("performance.memory_usage", MetricType.GAUGE,
                        "Использование памяти в MB", 0)
        
        # Метрики ошибок
        self.register_metric("errors.total", MetricType.COUNTER,
                        "Общее количество ошибок", 0)
        self.register_metric("errors.rate", MetricType.GAUGE,
                        "Частота ошибок в секунду", 0)
        
        # Метрики сбора статистики
        self.register_metric("stats.metrics_total", MetricType.GAUGE,
                        "Общее количество зарегистрированных метрик", 0)
        self.register_metric("stats.timeseries_points", MetricType.GAUGE,
                        "Количество точек в временных рядах", 0)
        
        
    def register_metric(self, 
                       metric_name: str, 
                       metric_type: MetricType,
                       description: str = "",
                       initial_value: Any = 0,
                       timeseries_size: int = None) -> bool:
        """
        Регистрация новой метрики
        
        Args:
            metric_name: Уникальное имя метрики
            metric_type: Тип метрики
            description: Описание метрики
            initial_value: Начальное значение
            timeseries_size: Размер временного ряда (None = по умолчанию)
            
        Returns:
            bool: Успешно ли зарегистрирована метрика
        """
        with self._lock:
            if metric_name in self.metrics:
                self._log_event(f"Metric {metric_name} already exists", level="WARNING")
                return False
            
            self.metrics[metric_name] = {
                'type': metric_type,
                'description': description,
                'value': initial_value,
                'created_time': time.time(),
                'updated_time': time.time(),
                'count': 0 if metric_type == MetricType.COUNTER else None
            }
            
            # Инициализация временного ряда
            size = timeseries_size or self.default_timeseries_size
            self.timeseries[metric_name] = deque(maxlen=size)
            
            # Добавление в группу по префиксу
            group = metric_name.split('.')[0]
            self.metric_groups[group].append(metric_name)
            
            self._log_event(f"Registered metric: {metric_name} ({metric_type.value})")
            return True
    
    def increment_counter(self, metric_name: str, value: int = 1) -> bool:
        """
        Увеличение счетчика
        
        Args:
            metric_name: Имя метрики-счетчика
            value: Значение для увеличения
            
        Returns:
            bool: Успешно ли обновлена метрика
        """
        with self._lock:
            if metric_name not in self.metrics:
                self._log_event(f"Counter {metric_name} not found", level="WARNING")
                return False
            
            metric = self.metrics[metric_name]
            if metric['type'] != MetricType.COUNTER:
                self._log_event(f"Metric {metric_name} is not a counter", level="WARNING")
                return False
            
            metric['value'] += value
            metric['count'] += value
            metric['updated_time'] = time.time()
            
            # Добавляем в временной ряд
            self._add_to_timeseries(metric_name, metric['value'])
            
            return True
    
    def set_gauge(self, metric_name: str, value: Any) -> bool:
        """
        Установка значения gauge-метрики
        
        Args:
            metric_name: Имя метрики-gauge
            value: Новое значение
            
        Returns:
            bool: Успешно ли обновлена метрика
        """
        with self._lock:
            if metric_name not in self.metrics:
                self._log_event(f"Gauge {metric_name} not found", level="WARNING")
                return False
            
            metric = self.metrics[metric_name]
            if metric['type'] != MetricType.GAUGE:
                self._log_event(f"Metric {metric_name} is not a gauge", level="WARNING")
                return False
            
            old_value = metric['value']
            metric['value'] = value
            metric['updated_time'] = time.time()
            
            # Добавляем в временной ряд
            self._add_to_timeseries(metric_name, value)
            
            # Проверяем пороговые значения
            self._check_thresholds(metric_name, old_value, value)
            
            return True
    
    def record_timing(self, metric_name: str, duration: float) -> bool:
        """
        Запись временной метрики
        
        Args:
            metric_name: Имя временной метрики
            duration: Длительность в секундах
            
        Returns:
            bool: Успешно ли записана метрика
        """
        with self._lock:
            if metric_name not in self.metrics:
                self._log_event(f"Timing metric {metric_name} not found", level="WARNING")
                return False
            
            metric = self.metrics[metric_name]
            if metric['type'] != MetricType.TIMING:
                self._log_event(f"Metric {metric_name} is not a timing metric", level="WARNING")
                return False
            
            # Для временных метрик храним статистику
            if 'values' not in metric:
                metric['values'] = []
                metric['count'] = 0
                metric['sum'] = 0
                metric['min'] = float('inf')
                metric['max'] = float('-inf')
            
            metric['values'].append(duration)
            metric['count'] += 1
            metric['sum'] += duration
            metric['min'] = min(metric['min'], duration)
            metric['max'] = max(metric['max'], duration)
            metric['value'] = duration  # Последнее значение
            metric['updated_time'] = time.time()
            
            # Ограничиваем размер хранимых значений
            if len(metric['values']) > 1000:
                metric['values'] = metric['values'][-1000:]
            
            # Добавляем в временной ряд
            self._add_to_timeseries(metric_name, duration)
            
            return True
    
    def record_histogram(self, metric_name: str, value: float) -> bool:
        """
        Запись значения для гистограммы
        
        Args:
            metric_name: Имя метрики-гистограммы
            value: Значение для записи
            
        Returns:
            bool: Успешно ли записана метрика
        """
        with self._lock:
            if metric_name not in self.metrics:
                self._log_event(f"Histogram metric {metric_name} not found", level="WARNING")
                return False
            
            metric = self.metrics[metric_name]
            if metric['type'] != MetricType.HISTOGRAM:
                self._log_event(f"Metric {metric_name} is not a histogram", level="WARNING")
                return False
            
            # Для гистограмм храним распределение
            if 'values' not in metric:
                metric['values'] = []
                metric['count'] = 0
                metric['sum'] = 0
                metric['min'] = float('inf')
                metric['max'] = float('-inf')
            
            metric['values'].append(value)
            metric['count'] += 1
            metric['sum'] += value
            metric['min'] = min(metric['min'], value)
            metric['max'] = max(metric['max'], value)
            metric['value'] = value  # Последнее значение
            metric['updated_time'] = time.time()
            
            # Ограничиваем размер хранимых значений
            if len(metric['values']) > 1000:
                metric['values'] = metric['values'][-1000:]
            
            # Добавляем в временной ряд
            self._add_to_timeseries(metric_name, value)
            
            return True
    
    def _add_to_timeseries(self, metric_name: str, value: Any):
        """Добавление значения во временной ряд"""
        if metric_name in self.timeseries:
            timestamp = time.time()
            self.timeseries[metric_name].append((timestamp, value))
    
    def _check_thresholds(self, metric_name: str, old_value: Any, new_value: Any):
        """Проверка пороговых значений (для алертов)"""
        # Здесь можно реализовать логику проверки порогов
        # и вызова callback'ов при их достижении
        pass
    
    def get_metric_value(self, metric_name: str) -> Optional[Any]:
        """Получение текущего значения метрики"""
        with self._lock:
            metric = self.metrics.get(metric_name)
            return metric['value'] if metric else None
    
    def get_metric_stats(self, metric_name: str) -> Optional[Dict[str, Any]]:
        """Получение статистики по метрике"""
        with self._lock:
            metric = self.metrics.get(metric_name)
            if not metric:
                return None
            
            stats = {
                'name': metric_name,
                'type': metric['type'].value,
                'description': metric['description'],
                'current_value': metric['value'],
                'updated_time': metric['updated_time'],
                'created_time': metric['created_time']
            }
            
            # Добавляем специфичную статистику для разных типов
            if metric['type'] in [MetricType.TIMING, MetricType.HISTOGRAM]:
                if 'values' in metric and metric['values']:
                    values = metric['values']
                    stats.update({
                        'count': metric['count'],
                        'sum': metric['sum'],
                        'min': metric['min'],
                        'max': metric['max'],
                        'mean': statistics.mean(values) if values else 0,
                        'median': statistics.median(values) if values else 0,
                        'stddev': statistics.stdev(values) if len(values) > 1 else 0,
                        'last_10_avg': statistics.mean(values[-10:]) if len(values) >= 10 else statistics.mean(values)
                    })
            
            elif metric['type'] == MetricType.COUNTER:
                stats['total_count'] = metric['count']
            
            return stats
    
    def get_timeseries_data(self, 
                           metric_name: str, 
                           time_window: float = None,
                           max_points: int = None) -> Optional[List[tuple]]:
        """
        Получение данных временного ряда
        
        Args:
            metric_name: Имя метрики
            time_window: Окно времени в секундах (только последние N секунд)
            max_points: Максимальное количество точек
            
        Returns:
            List[tuple]: Список кортежей (timestamp, value)
        """
        with self._lock:
            if metric_name not in self.timeseries:
                return None
            
            data = list(self.timeseries[metric_name])
            
            # Фильтрация по времени
            if time_window:
                cutoff_time = time.time() - time_window
                data = [(ts, val) for ts, val in data if ts >= cutoff_time]
            
            # Ограничение количества точек
            if max_points and len(data) > max_points:
                # Берем равномерно распределенные точки
                step = len(data) // max_points
                data = data[::step][:max_points]
            
            return data
    
    def get_group_metrics(self, group_name: str) -> Dict[str, Any]:
        """Получение всех метрик группы"""
        with self._lock:
            if group_name not in self.metric_groups:
                return {}
            
            group_metrics = {}
            for metric_name in self.metric_groups[group_name]:
                group_metrics[metric_name] = self.get_metric_stats(metric_name)
            
            return group_metrics
    
    def get_all_metrics(self) -> Dict[str, Any]:
        """Получение всех метрик"""
        with self._lock:
            all_metrics = {}
            for metric_name in self.metrics:
                all_metrics[metric_name] = self.get_metric_stats(metric_name)
            return all_metrics
    
    def compute_rate(self, metric_name: str, time_window: float = 60.0) -> Optional[float]:
        """
        Вычисление скорости изменения метрики (значений в секунду)
        
        Args:
            metric_name: Имя метрики
            time_window: Окно времени для расчета
            
        Returns:
            float: Скорость изменения (значений/секунду)
        """
        with self._lock:
            data = self.get_timeseries_data(metric_name, time_window)
            if not data or len(data) < 2:
                return None
            
            first_time, first_value = data[0]
            last_time, last_value = data[-1]
            
            time_diff = last_time - first_time
            if time_diff <= 0:
                return None
            
            value_diff = last_value - first_value
            return value_diff / time_diff
    
    def create_summary(self) -> Dict[str, Any]:
        """Создание сводки по всем метрикам"""
        with self._lock:
            summary = {
                'timestamp': time.time(),
                'total_metrics': len(self.metrics),
                'metric_groups': {},
                'performance_metrics': {},
                'error_metrics': {}
            }
            
            # Группируем метрики по группам
            for group_name, metric_names in self.metric_groups.items():
                summary['metric_groups'][group_name] = {
                    'count': len(metric_names),
                    'metrics': [self.get_metric_stats(name) for name in metric_names]
                }
            
            # Выделяем ключевые метрики производительности
            performance_metrics = self.get_group_metrics('performance')
            if performance_metrics:
                summary['performance_metrics'] = {
                    'uptime': performance_metrics.get('performance.uptime', {}).get('current_value', 0),
                    'memory_usage': performance_metrics.get('performance.memory_usage', {}).get('current_value', 0)
                }
            
            # Метрики ошибок
            error_metrics = self.get_group_metrics('errors')
            if error_metrics:
                summary['error_metrics'] = {
                    'total_errors': error_metrics.get('errors.total', {}).get('current_value', 0),
                    'error_rate': error_metrics.get('errors.rate', {}).get('current_value', 0)
                }
            
            return summary
    
    def reset_metric(self, metric_name: str) -> bool:
        """Сброс метрики к начальному значению"""
        with self._lock:
            if metric_name not in self.metrics:
                return False
            
            metric = self.metrics[metric_name]
            metric_type = metric['type']
            
            if metric_type == MetricType.COUNTER:
                metric['value'] = 0
                metric['count'] = 0
            elif metric_type == MetricType.GAUGE:
                metric['value'] = 0
            elif metric_type in [MetricType.TIMING, MetricType.HISTOGRAM]:
                if 'values' in metric:
                    metric['values'] = []
                    metric['count'] = 0
                    metric['sum'] = 0
                    metric['min'] = float('inf')
                    metric['max'] = float('-inf')
                    metric['value'] = 0
            
            metric['updated_time'] = time.time()
            
            # Очищаем временной ряд
            if metric_name in self.timeseries:
                self.timeseries[metric_name].clear()
            
            self._log_event(f"Reset metric: {metric_name}")
            return True
    
    def reset_all_metrics(self):
        """Сброс всех метрик"""
        with self._lock:
            for metric_name in self.metrics:
                self.reset_metric(metric_name)
            self._log_event("All metrics reset")
    
    def _log_event(self, message: str, level: str = "INFO"):
        """Логирование событий (для интеграции с LoggerManager)"""
        print(f"[StatsCollector {level}] {message}")
    
    # Методы для интеграции с ProcessModule
    def get_status(self) -> Dict[str, Any]:
        """Получение статуса менеджера для мониторинга"""
        with self._lock:
            return {
                'running': self.is_running,
                'total_metrics': len(self.metrics),
                'metric_groups': list(self.metric_groups.keys()),
                'timeseries_size': sum(len(ts) for ts in self.timeseries.values()),
                'summary': self.create_summary()
            }
    
    def is_ready(self) -> bool:
        """Проверка готовности менеджера"""
        return self.is_running
    
    def _ensure_metric_exists(self, metric_name: str, metric_type: MetricType, description: str = "") -> bool:
        """Гарантирует существование метрики, создавая её при необходимости"""
        with self._lock:
            if metric_name not in self.metrics:
                return self.register_metric(
                    metric_name, 
                    metric_type, 
                    f"Auto-registered: {description or metric_name}"
                )
            return True

    def safe_increment_counter(self, metric_name: str, value: int = 1, description: str = "") -> bool:
        """Безопасное увеличение счетчика (автоматически создает метрику при необходимости)"""
        if not self._ensure_metric_exists(metric_name, MetricType.COUNTER, description):
            return False
        return self.increment_counter(metric_name, value)

    def safe_set_gauge(self, metric_name: str, value: Any, description: str = "") -> bool:
        """Безопасная установка gauge (автоматически создает метрику при необходимости)"""
        if not self._ensure_metric_exists(metric_name, MetricType.GAUGE, description):
            return False
        return self.set_gauge(metric_name, value)

    def safe_record_timing(self, metric_name: str, duration: float, description: str = "") -> bool:
        """Безопасная запись времени (автоматически создает метрику при необходимости)"""
        if not self._ensure_metric_exists(metric_name, MetricType.TIMING, description):
            return False
        return self.record_timing(metric_name, duration)

    def safe_record_histogram(self, metric_name: str, value: float, description: str = "") -> bool:
        """Безопасная запись гистограммы (автоматически создает метрику при необходимости)"""
        if not self._ensure_metric_exists(metric_name, MetricType.HISTOGRAM, description):
            return False
        return self.record_histogram(metric_name, value)



if __name__ == "__main__":
    # Создание сборщика статистики
    stats = StatsCollector("VideoProcessor")

    # Регистрация метрик
    stats.register_metric("processing.frames_processed", MetricType.COUNTER, 
                        "Количество обработанных кадров")
    stats.register_metric("processing.fps", MetricType.GAUGE, 
                        "Текущий FPS")
    stats.register_metric("processing.frame_time", MetricType.TIMING, 
                        "Время обработки кадра")
    stats.register_metric("processing.queue_size", MetricType.HISTOGRAM, 
                        "Размер очереди обработки")

    # Запуск
    stats.start()

    # Использование в процессе обработки
    def process_frame(frame):
        start_time = time.time()
        
        # Имитация обработки кадра
        time.sleep(0.01)
        
        # Запись статистики
        stats.increment_counter("processing.frames_processed")
        stats.record_timing("processing.frame_time", time.time() - start_time)
        stats.set_gauge("processing.fps", 30.5)  # Примерное значение FPS
        
        # Запись размера очереди (пример)
        queue_size = 15  # Получаем из какой-то очереди
        stats.record_histogram("processing.queue_size", queue_size)

    # Имитация обработки нескольких кадров
    for i in range(100):
        process_frame(None)
        time.sleep(0.01)

    # Получение статистики
    print("Текущий FPS:", stats.get_metric_value("processing.fps"))
    print("Статистика обработки кадров:", stats.get_metric_stats("processing.frame_time"))

    # Временные ряды
    timeseries_data = stats.get_timeseries_data("processing.fps", time_window=60)
    print("Данные FPS за последние 60 секунд:", len(timeseries_data), "точек")

    # Сводка
    summary = stats.create_summary()
    print("Общая сводка:", summary)

    # Скорость обработки
    processing_rate = stats.compute_rate("processing.frames_processed", time_window=10)
    print("Скорость обработки:", processing_rate, "кадров/сек")

    # Остановка
    stats.stop()