#!/usr/bin/env python3
"""
Главный файл системы обработки видео.
Демонстрирует интеграцию всех менеджеров в реальном сценарии.
"""

import time
import queue
import threading
from datetime import datetime
from process_module import ProcessModule
from logger_manager import LoggerManager, LogLevel, LogHandlerType
from worker_manager import WorkerManager
from command_processor import CommandProcessor
from stats_collector import StatsCollector, MetricType
from health_monitor import HealthMonitor, HealthStatus, HealthCheckResult


class VideoProcessingSystem(ProcessModule):
    """
    Основная система обработки видео, использующая все менеджеры.
    Реальный пример production-системы.
    """
    
    def __init__(self, config=None):
        # Очередь для внешнего управления
        control_queue = queue.Queue()
        
        super().__init__(
            name="VideoProcessingSystem",
            control_queue=control_queue
        )
        
        self.config = config or {}
        self.is_processing = False
        
    def _init_managers(self):
        """Инициализация всех менеджеров с реальной конфигурацией"""
        
        # 1. LoggerManager - первым, т.к. другие менеджеры будут его использовать
        logger = LoggerManager(self.name)
        logger.set_global_level(LogLevel.INFO)
        
        # Настройка обработчиков логирования
        logger.add_handler(
            LogHandlerType.CONSOLE,
            "console",
            LogLevel.INFO
        )
        
        logger.add_handler(
            LogHandlerType.ROTATING_FILE,
            "file",
            LogLevel.DEBUG,
            filename="logs/video_processor.log",
            max_bytes=10*1024*1024,  # 10MB
            backup_count=5
        )
        
        # 2. Статистика
        stats = StatsCollector(self.name)
        
        # Регистрация ключевых метрик
        stats.register_metric("processing.frames.total", MetricType.COUNTER,
                            "Общее количество обработанных кадров")
        stats.register_metric("processing.fps.current", MetricType.GAUGE,
                            "Текущий FPS обработки")
        stats.register_metric("processing.frame_time.ms", MetricType.TIMING,
                            "Время обработки кадра в миллисекундах")
        stats.register_metric("processing.errors.total", MetricType.COUNTER,
                            "Общее количество ошибок обработки")
        stats.register_metric("system.memory.usage_mb", MetricType.GAUGE,
                            "Использование памяти в MB")
        
        # 3. WorkerManager
        worker_manager = WorkerManager(self.name)
        
        # 4. CommandProcessor
        command_processor = CommandProcessor(self.name, self.control_queue)
        
        # 5. HealthMonitor
        health_monitor = HealthMonitor(self.name)
        
        # Регистрируем все менеджеры
        self.register_manager("logger", logger)
        self.register_manager("stats", stats)
        self.register_manager("workers", worker_manager)
        self.register_manager("commands", command_processor)
        self.register_manager("health", health_monitor)
        
        # Настраиваем интеграцию
        self._setup_manager_integration()
        
    def _setup_manager_integration(self):
        """Настройка взаимодействия между менеджерами"""
        logger = self.get_manager("logger")
        stats = self.get_manager("stats")
        workers = self.get_manager("workers")
        commands = self.get_manager("commands")
        health = self.get_manager("health")

        self._integration_setup_done = False
        if hasattr(self, '_integration_setup_done') and self._integration_setup_done:
            return
        
        # Настройка логирования событий от других менеджеров
        def setup_logging_integration():
            # Worker events -> Logger
            def log_worker_event(event_type, worker_name, *args):
                if not hasattr(self, '_worker_events_logged'):
                    self._worker_events_logged = set()
                
                event_key = f"{event_type}_{worker_name}"
                if event_key in self._worker_events_logged:
                    return
                self._worker_events_logged.add(event_key)
                
                if event_type == 'worker_error':
                    error = args[0] if args else "Unknown error"
                    logger.error(f"Worker '{worker_name}' error: {error}")
                elif event_type == 'worker_started':
                    logger.info(f"Worker '{worker_name}' started")
                elif event_type == 'worker_stopped':
                    logger.info(f"Worker '{worker_name}' stopped")
            
            workers.event_callbacks = {key: [] for key in workers.event_callbacks}
            workers.register_callback('worker_started', log_worker_event)
            workers.register_callback('worker_stopped', log_worker_event)
            workers.register_callback('worker_error', log_worker_event)

            self._integration_setup_done = True
            
            # Command events -> Logger
            def log_command_event(event_type, command_id, command_name, *args):
                if event_type == 'command_failed':
                    error = args[0] if args else "Unknown error"
                    logger.error(f"Command '{command_name}' failed: {error}")
                elif event_type == 'unknown_command':
                    logger.warning(f"Unknown command: {command_name}")
            
            commands.register_callback('command_failed', log_command_event)
            commands.register_callback('unknown_command', log_command_event)
            
            # Health events -> Logger
            def log_health_event(old_status, new_status, message):
                if new_status == HealthStatus.UNHEALTHY:
                    logger.error(f"System unhealthy: {message}")
                elif new_status == HealthStatus.DEGRADED:
                    logger.warning(f"System degraded: {message}")
                elif new_status == HealthStatus.HEALTHY and old_status != HealthStatus.HEALTHY:
                    logger.info(f"System recovered: {message}")
            
            health.register_status_change_callback(log_health_event)
        
        # Настройка сбора статистики
        def setup_stats_integration():
            # Worker events -> Stats
            def record_worker_stats(event_type, worker_name, *args):
                if event_type == 'worker_started':
                    stats.increment_counter("workers.started_total")
                elif event_type == 'worker_stopped':
                    stats.increment_counter("workers.stopped_total")
                elif event_type == 'worker_error':
                    stats.increment_counter("workers.errors_total")
            
            workers.register_callback('worker_started', record_worker_stats)
            workers.register_callback('worker_stopped', record_worker_stats)
            workers.register_callback('worker_error', record_worker_stats)
            
            # Command events -> Stats
            def record_command_stats(event_type, command_id, command_name, *args):
                stats.increment_counter("commands.received_total")
                if event_type == 'command_completed':
                    stats.increment_counter("commands.completed_total")
                elif event_type == 'command_failed':
                    stats.increment_counter("commands.failed_total")
            
            commands.register_callback('command_received', record_command_stats)
            commands.register_callback('command_completed', record_command_stats)
            commands.register_callback('command_failed', record_command_stats)
            
            # Health events -> Stats
            def record_health_stats(old_status, new_status, message):
                stats.increment_counter("health.status_changes_total")
                # Сохраняем числовое представление статуса для графиков
                status_value = {
                    HealthStatus.HEALTHY: 0,
                    HealthStatus.DEGRADED: 1,
                    HealthStatus.UNHEALTHY: 2
                }.get(new_status, 3)
                stats.set_gauge("health.current_status", status_value)
            
            health.register_status_change_callback(record_health_stats)
        
        # Настройка обработчиков команд
        def setup_command_handlers():
            commands.register_handler("start_processing", self._handle_start_processing)
            commands.register_handler("stop_processing", self._handle_stop_processing)
            commands.register_handler("get_status", self._handle_get_status)
            commands.register_handler("get_stats", self._handle_get_stats)
            commands.register_handler("get_health", self._handle_get_health)
            commands.register_handler("set_log_level", self._handle_set_log_level)
            commands.register_handler("get_logs", self._handle_get_logs)
        
        # Настройка проверок здоровья
        def setup_health_checks():
            # Проверка менеджера worker'ов
            health.register_health_check(
                "worker_manager",
                self._create_worker_manager_health_check(),
                interval=30.0,
                critical=True,
                description="Worker manager operational status"
            )
            
            # Проверка обработки видео
            health.register_health_check(
                "video_processing",
                self._create_video_processing_health_check(),
                interval=15.0,
                critical=True,
                description="Video processing pipeline health"
            )
            
            # Проверка использования памяти
            health.register_health_check(
                "memory_usage",
                HealthMonitor.create_memory_health_check(threshold_mb=1024),  # 1GB
                interval=10.0,
                critical=False,
                description="Memory usage monitoring"
            )
            
            # Проверка командного процессора
            health.register_health_check(
                "command_processor",
                self._create_command_processor_health_check(),
                interval=20.0,
                critical=False,
                description="Command processor responsiveness"
            )
        
        # Выполняем все настройки
        setup_logging_integration()
        setup_stats_integration()
        setup_command_handlers()
        setup_health_checks()
        
        logger.info("Manager integration setup completed")
    
    def _init_threads(self):
        """Инициализация потоков системы"""
        
        # Основной поток обработки команд
        self.register_thread(
            "command_processor",
            self._command_processor_thread
        )
        
        # Поток мониторинга здоровья
        self.register_thread(
            "health_monitor", 
            self._health_monitor_thread
        )
        
        # Поток сбора системной статистики
        self.register_thread(
            "system_stats",
            self._system_stats_thread
        )
        
        # Поток для периодических задач
        self.register_thread(
            "maintenance",
            self._maintenance_thread
        )
    
    def _init_workers(self):
        """Инициализация worker'ов системы"""
        workers = self.get_manager("workers")
        logger = self.get_manager("logger")
        
        # Worker захвата видео
        workers.create_worker(
            "video_capture",
            self._video_capture_worker,
            auto_start=False,  # Запускается по команде
            daemon=True,
            source="camera_0",
            buffer_size=10
        )
        
        # Worker обработки кадров
        workers.create_worker(
            "frame_processor",
            self._frame_processor_worker, 
            auto_start=False,
            daemon=True,
            model_version="v2.1",
            processing_mode="fast"
        )
        
        # Worker анализа данных
        workers.create_worker(
            "data_analyzer",
            self._data_analyzer_worker,
            auto_start=True,  # Запускается автоматически
            daemon=True,
            analysis_interval=5.0
        )
        
        logger.info("Workers initialized")
    
    # Реализации worker'ов
    def _video_capture_worker(self, stop_event, pause_event):
        """Worker для захвата видео с камеры"""
        logger = self.get_manager("logger")
        stats = self.get_manager("stats")
        
        logger.info("Video capture worker started")
        frame_count = 0
        last_fps_time = time.time()  # ← ИНИЦИАЛИЗИРОВАТЬ ЗДЕСЬ
        
        try:
            # Имитация инициализации камеры
            logger.debug("Camera initialized")
            
            while not stop_event.is_set():
                if pause_event.is_set():
                    time.sleep(0.1)
                    continue
                
                try:
                    # Имитация захвата кадра
                    time.sleep(0.033)  # ~30 FPS
                    
                    frame_count += 1
                    stats.safe_increment_counter("processing.frames.total", description="Total frames processed")
                    
                    # Обновляем FPS каждые 10 кадров
                    if frame_count % 10 == 0:
                        current_time = time.time()
                        time_diff = current_time - last_fps_time
                        if time_diff > 0:  # ← ЗАЩИТА ОТ ДЕЛЕНИЯ НА НОЛЬ
                            fps = 10 / time_diff
                            stats.safe_set_gauge("processing.fps.current", fps, description="Current FPS")
                        last_fps_time = current_time  # ← ОБНОВЛЯТЬ ВНЕ УСЛОВИЯ
                    
                    # Логируем прогресс
                    if frame_count % 100 == 0:
                        logger.debug(f"Captured {frame_count} frames")
                        
                except Exception as e:
                    logger.error(f"Frame capture error: {e}")
                    stats.safe_increment_counter("processing.errors.total", description="Total processing errors")
                    time.sleep(0.1)
                    
        except Exception as e:
            logger.error(f"Video capture worker fatal error: {e}")
        finally:
            logger.info("Video capture worker stopped")
    
    def _frame_processor_worker(self, stop_event, pause_event):
        """Worker для обработки кадров"""
        logger = self.get_manager("logger")
        stats = self.get_manager("stats")
        
        logger.info("Frame processor worker started")
        
        while not stop_event.is_set():
            if pause_event.is_set():
                time.sleep(0.1)
                continue
            
            try:
                start_time = time.time()
                
                # Имитация обработки кадра
                # processed_frame = self._process_frame(frame)
                processing_time = 0.015 + (0.005 * (time.time() % 1))  # Случайное время 15-20ms
                time.sleep(processing_time)
                
                # Записываем метрики
                stats.record_timing("processing.frame_time.ms", processing_time * 1000)
                
            except Exception as e:
                logger.error(f"Frame processing error: {e}")
                stats.increment_counter("processing.errors.total")
                time.sleep(0.1)
        
        logger.info("Frame processor worker stopped")
    
    def _data_analyzer_worker(self, stop_event, pause_event):
        """Worker для анализа данных и метрик"""
        logger = self.get_manager("logger")
        stats = self.get_manager("stats")
        
        logger.info("Data analyzer worker started")
        
        analysis_count = 0
        while not stop_event.is_set():
            if pause_event.is_set():
                time.sleep(0.1)
                continue
            
            try:
                # Анализ и агрегация метрик
                analysis_count += 1
                
                # Пример анализа: вычисление среднего FPS за последнюю минуту
                fps_data = stats.get_timeseries_data("processing.fps.current", time_window=60)
                if fps_data:
                    fps_values = [value for _, value in fps_data]
                    avg_fps = sum(fps_values) / len(fps_values)
                    
                    # Логируем если FPS упал ниже порога
                    if avg_fps < 20:
                        logger.warning(f"Low average FPS: {avg_fps:.1f}")
                
                # Анализ ошибок
                error_count = stats.get_metric_value("processing.errors.total") or 0
                if error_count > 0 and analysis_count % 12 == 0:  # Каждую минуту
                    logger.info(f"Total processing errors: {error_count}")
                
                time.sleep(5.0)  # Анализ каждые 5 секунд
                
            except Exception as e:
                logger.error(f"Data analysis error: {e}")
                time.sleep(10.0)
        
        logger.info("Data analyzer worker stopped")
    
    # Потоки системы
    def _command_processor_thread(self):
        """Поток обработки команд"""
        commands = self.get_manager("commands")
        logger = self.get_manager("logger")
        
        logger.info("Command processor thread started")
        
        while not self.should_stop():
            try:
                # Обрабатываем команды из внешней очереди
                commands.process_queue(timeout=0.1)
                
                # Обрабатываем внутренние команды
                commands.process_internal_commands(timeout=0.1)
                
            except Exception as e:
                logger.error(f"Command processor thread error: {e}")
                time.sleep(1.0)
    
    def _health_monitor_thread(self):
        """Поток мониторинга здоровья"""
        health = self.get_manager("health")
        logger = self.get_manager("logger")
        
        logger.info("Health monitor thread started")
        
        while not self.should_stop():
            try:
                # Запускаем проверки, для которых наступило время
                results = health.run_due_health_checks()
                
                # Получаем общий статус
                overall_health = health.get_overall_health()
                
                # Если система нездорова, предпринимаем действия
                if overall_health['status'] == HealthStatus.UNHEALTHY.value:
                    self._handle_system_unhealthy(overall_health)
                
                time.sleep(1.0)
                
            except Exception as e:
                logger.error(f"Health monitor thread error: {e}")
                time.sleep(5.0)
    
    def _system_stats_thread(self):
        """Поток сбора системной статистики"""
        stats = self.get_manager("stats")
        logger = self.get_manager("logger")
        
        logger.info("System stats thread started")
        
        start_time = time.time()
        
        while not self.should_stop():
            try:
                # Обновляем uptime
                uptime = time.time() - start_time
                stats.set_gauge("system.uptime.seconds", uptime)
                
                # Сбор использования памяти (если доступно)
                try:
                    import psutil
                    process = psutil.Process()
                    memory_mb = process.memory_info().rss / 1024 / 1024
                    stats.set_gauge("system.memory.usage_mb", memory_mb)
                except ImportError:
                    pass  # psutil не установлен
                
                time.sleep(2.0)
                
            except Exception as e:
                logger.error(f"System stats thread error: {e}")
                time.sleep(10.0)
    
    def _maintenance_thread(self):
        """Поток для технического обслуживания"""
        logger = self.get_manager("logger")
        
        logger.info("Maintenance thread started")
        
        last_cleanup = time.time()
        
        while not self.should_stop():
            try:
                current_time = time.time()
                
                # Очистка старых логов каждые 10 минут
                if current_time - last_cleanup > 600:
                    self._perform_maintenance()
                    last_cleanup = current_time
                
                time.sleep(30.0)
                
            except Exception as e:
                logger.error(f"Maintenance thread error: {e}")
                time.sleep(60.0)
    
    def _perform_maintenance(self):
        """Выполнение задач технического обслуживания"""
        logger = self.get_manager("logger")
        stats = self.get_manager("stats")
        
        logger.info("Performing system maintenance")
        
        # Очистка старых данных
        stats_summary = stats.create_summary()
        logger.info(f"System stats: {stats_summary}")
        
        # Можно добавить ротацию логов, архивацию старых данных и т.д.
    
    def _handle_system_unhealthy(self, health_status):
        """Обработка нездорового состояния системы"""
        logger = self.get_manager("logger")
        workers = self.get_manager("workers")
        
        logger.error(f"System is unhealthy: {health_status['message']}")
        
        # Автоматические действия при нездоровой системе
        failing_checks = [check for check in health_status['details']['checks']['critical'] 
                         if check['last_result'] and check['last_result'].get('status') != 'healthy']
        
        for check in failing_checks:
            if 'worker' in check['name']:
                worker_name = check['name'].replace('_manager', '')
                logger.info(f"Attempting to restart worker: {worker_name}")
                workers.restart_worker(worker_name)
    
    # Обработчики команд
    def _handle_start_processing(self, command_data):
        """Обработчик команды начала обработки"""
        logger = self.get_manager("logger")
        workers = self.get_manager("workers")
        
        logger.info("Starting video processing")
        
        # Запускаем worker'ов обработки
        workers.start_worker("video_capture")
        workers.start_worker("frame_processor")
        
        self.is_processing = True
        
        return {
            "status": "started",
            "timestamp": time.time(),
            "workers": ["video_capture", "frame_processor"]
        }
    
    def _handle_stop_processing(self, command_data):
        """Обработчик команды остановки обработки"""
        logger = self.get_manager("logger")
        workers = self.get_manager("workers")
        
        logger.info("Stopping video processing")
        
        # Останавливаем worker'ов обработки
        workers.stop_worker("video_capture")
        workers.stop_worker("frame_processor")
        
        self.is_processing = False
        
        return {
            "status": "stopped", 
            "timestamp": time.time(),
            "workers": ["video_capture", "frame_processor"]
        }
    
    def _handle_get_status(self, command_data):
        """Обработчик команды получения статуса"""
        workers = self.get_manager("workers")
        health = self.get_manager("health")
        
        return {
            "timestamp": time.time(),
            "processing": self.is_processing,
            "workers": workers.get_all_workers_status(),
            "health": health.get_overall_health()
        }
    
    def _handle_get_stats(self, command_data):
        """Обработчик команды получения статистики"""
        stats = self.get_manager("stats")
        metric_name = command_data.get('metric_name')
        
        if metric_name:
            return stats.get_metric_stats(metric_name)
        else:
            return stats.get_all_metrics()
    
    def _handle_get_health(self, command_data):
        """Обработчик команды получения здоровья"""
        health = self.get_manager("health")
        check_name = command_data.get('check_name')
        
        if check_name:
            return health.get_check_status(check_name)
        else:
            return health.get_overall_health()
    
    def _handle_set_log_level(self, command_data):
        """Обработчик команды установки уровня логирования"""
        logger = self.get_manager("logger")
        level_name = command_data.get('level', 'INFO').upper()
        
        try:
            level = LogLevel[level_name]
            logger.set_global_level(level)
            return {"status": "success", "level": level_name}
        except KeyError:
            return {"status": "error", "error": f"Unknown log level: {level_name}"}
    
    def _handle_get_logs(self, command_data):
        """Обработчик команды получения логов"""
        logger = self.get_manager("logger")
        filters = command_data.get('filters', {})
        limit = command_data.get('limit', 100)
        
        logs = logger.get_logs(filters=filters, max_entries=limit)
        return {"logs": logs, "count": len(logs)}
    
    # Функции проверок здоровья
    def _create_worker_manager_health_check(self):
        def check():
            workers = self.get_manager("workers")
            if not workers:
                return HealthCheckResult(
                    status=HealthStatus.UNHEALTHY,
                    message="Worker manager not available"
                )
            
            status = workers.get_status()
            running_workers = status.get('running_workers', 0)
            total_workers = status.get('total_workers', 0)
            
            if total_workers == 0:
                return HealthCheckResult(
                    status=HealthStatus.HEALTHY,
                    message="No workers registered",
                    details=status
                )
            
            worker_status = workers.get_all_workers_status()
            failed_workers = []
            
            for name, info in worker_status.items():
                if info and info.get('status') == 'error':
                    failed_workers.append(name)
            
            if failed_workers:
                return HealthCheckResult(
                    status=HealthStatus.UNHEALTHY,
                    message=f"Workers in error state: {', '.join(failed_workers)}",
                    details={"failed_workers": failed_workers, **status}
                )
            
            if running_workers < total_workers:
                return HealthCheckResult(
                    status=HealthStatus.DEGRADED,
                    message=f"Some workers not running ({running_workers}/{total_workers})",
                    details=status
                )
            
            return HealthCheckResult(
                status=HealthStatus.HEALTHY,
                message=f"All workers operational ({running_workers}/{total_workers})",
                details=status
            )
        
        return check
    
    def _create_video_processing_health_check(self):
        def check():
            stats = self.get_manager("stats")
            
            # Проверяем FPS
            current_fps = stats.get_metric_value("processing.fps.current") or 0
            if current_fps < 15:
                return HealthCheckResult(
                    status=HealthStatus.DEGRADED,
                    message=f"Low FPS: {current_fps:.1f}",
                    details={"current_fps": current_fps, "threshold": 15}
                )
            
            # Проверяем время обработки кадра
            frame_time_stats = stats.get_metric_stats("processing.frame_time.ms")
            if frame_time_stats:
                avg_time = frame_time_stats.get('mean', 0)
                if avg_time > 50:  # 50ms
                    return HealthCheckResult(
                        status=HealthStatus.DEGRADED,
                        message=f"High frame processing time: {avg_time:.1f}ms",
                        details=frame_time_stats
                    )
            
            # Проверяем количество ошибок
            error_count = stats.get_metric_value("processing.errors.total") or 0
            if error_count > 10:
                return HealthCheckResult(
                    status=HealthStatus.DEGRADED,
                    message=f"High error count: {error_count}",
                    details={"error_count": error_count}
                )
            
            return HealthCheckResult(
                status=HealthStatus.HEALTHY,
                message="Video processing pipeline healthy",
                details={
                    "fps": current_fps,
                    "error_count": error_count
                }
            )
        
        return check
    
    def _create_command_processor_health_check(self):
        def check():
            commands = self.get_manager("commands")
            if not commands:
                return HealthCheckResult(
                    status=HealthStatus.UNKNOWN,
                    message="Command processor not available"
                )
            
            status = commands.get_status()
            
            # Проверяем историю команд на наличие недавних ошибок
            recent_commands = commands.get_recent_commands(limit=20)
            failed_commands = [cmd for cmd in recent_commands 
                             if cmd.get('status') == 'error']
            
            if len(failed_commands) > 5:
                return HealthCheckResult(
                    status=HealthStatus.DEGRADED,
                    message=f"High command failure rate: {len(failed_commands)}/20",
                    details={"recent_failures": len(failed_commands)}
                )
            
            return HealthCheckResult(
                status=HealthStatus.HEALTHY,
                message="Command processor operational",
                details=status
            )
        
        return check

# Демонстрация использования системы
def demo_system():
    """Демонстрация работы всей системы"""
    print("=== Video Processing System Demo ===\n")
    
    # Создаем систему
    system = VideoProcessingSystem()
    
    # Инициализируем worker'ов
    system._init_workers()
    
    # Запускаем систему
    print("Starting system...")
    system.run()
    
    # Даем системе время на запуск
    time.sleep(2)
    
    # Демонстрация команд
    print("\n1. Starting video processing...")
    result = system.get_manager("commands").process_command({
        "command": "start_processing",
        "id": "demo_001"
    })
    print(f"Result: {result}")
    
    time.sleep(3)
    
    print("\n2. Getting system status...")
    result = system.get_manager("commands").process_command({
        "command": "get_status", 
        "id": "demo_002"
    })
    print(f"Status: {result.get('health', {}).get('status', 'unknown')}")
    
    time.sleep(2)
    
    print("\n3. Getting statistics...")
    result = system.get_manager("commands").process_command({
        "command": "get_stats",
        "id": "demo_003"
    })
    stats = result.get('processing', {})
    print(f"Frames processed: {stats.get('frames_total', {}).get('current_value', 0)}")
    print(f"Current FPS: {stats.get('fps_current', {}).get('current_value', 0):.1f}")
    
    time.sleep(2)
    
    print("\n4. Getting system health...")
    result = system.get_manager("commands").process_command({
        "command": "get_health",
        "id": "demo_004"
    })
    print(f"Health: {result.get('status', 'unknown')}")
    print(f"Message: {result.get('message', 'No message')}")
    
    time.sleep(2)
    
    print("\n5. Stopping video processing...")
    result = system.get_manager("commands").process_command({
        "command": "stop_processing",
        "id": "demo_005"
    })
    print(f"Result: {result}")
    
    # Даем время на корректную остановку
    time.sleep(2)
    
    print("\n6. Stopping system...")
    system.stop()
    
    print("\n=== Demo completed ===")

if __name__ == "__main__":
    # Создаем папку для логов
    import os
    os.makedirs("logs", exist_ok=True)
    
    # Запускаем демо
    demo_system()