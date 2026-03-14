"""
Упрощенный процесс для сбора отладочных логов с использованием маркеров (Events)
При команде generate_report устанавливаются маркеры для всех процессов
Каждый процесс делает один цикл записи и сбрасывает маркер
Процесс логгера ждет сброса всех маркеров и генерирует отчет
"""
import time
import sys
import os
from queue import Empty

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../'))

from Utils.debug_logger_simple import SimpleDebugLogger


def process_debug_logger(queue_manager, control_debug_logger):
    """Процесс сбора логов с использованием маркеров"""
    print("Процесс debug logger запущен")
    
    try:
        queue_manager.process_ready_queue.put("proc_debug_logger")
    except Exception as e:
        print(f"Error sending ready signal: {e}")
    
    # Создаем упрощенный логгер
    base_dir = os.path.join(os.path.dirname(__file__), '../../Data/debug_logs')
    base_dir = os.path.abspath(base_dir)
    logger = SimpleDebugLogger(base_output_dir=base_dir)
    
    # Список всех маркеров процессов
    process_markers = [
        'debug_log_process_processing',
        'debug_log_process_region_processor_1',
        'debug_log_process_region_processor_2',
        'debug_log_process_region_merger',
        'debug_log_process_overlay',  # Последний процесс
    ]
    
    # Состояние
    waiting_for_markers = False  # Флаг ожидания сброса маркеров
    markers_set_time = None  # Время установки маркеров
    frame_id = 'current_frame'  # Фиксированный ID для одного кадра
    
    while not queue_manager.stop_event.is_set():
        # Читаем управление
        try:
            control = control_debug_logger.get_nowait()
            command = control.get('command', '')
            
            if command == 'generate_report':
                # Команда генерации отчета
                print("=" * 80)
                print("Debug logger: Starting report generation with markers")
                print("=" * 80)
                
                # Очищаем старые данные
                logger.clear(frame_id)
                logger.start_frame(frame_id)
                
                # Устанавливаем все маркеры для процессов
                markers_set = []
                for marker_name in process_markers:
                    if hasattr(queue_manager, marker_name):
                        marker = getattr(queue_manager, marker_name)
                        # Проверяем текущее состояние маркера
                        was_set = marker.is_set()
                        marker.set()  # Устанавливаем маркер
                        # Проверяем сразу после установки
                        now_set = marker.is_set()
                        markers_set.append(marker_name)
                        print(f"  ✓ Marker set: {marker_name} (was_set={was_set}, now_set={now_set})")
                        
                        # Небольшая задержка для синхронизации
                        time.sleep(0.01)
                    else:
                        print(f"  ✗ Marker NOT FOUND: {marker_name}")
                
                if not markers_set:
                    print("  ⚠ No markers found, report generation may not work")
                
                # Начинаем ожидание сброса маркеров
                waiting_for_markers = True
                markers_set_time = time.time()
                print(f"  Waiting for all markers to be cleared...")
                
            elif command == 'clear':
                frame_id_to_clear = control.get('frame_id', None)
                logger.clear(frame_id_to_clear)
                if frame_id_to_clear == frame_id:
                    waiting_for_markers = False
        except Empty:
            pass
        
        # Проверяем, все ли маркеры сброшены
        if waiting_for_markers:
            # Проверяем таймаут (10 секунд)
            if markers_set_time and (time.time() - markers_set_time) > 10.0:
                print("  ⚠ TIMEOUT: Markers were not cleared within 10 seconds")
                print("  This may indicate that processes are not receiving frames or markers are not visible")
                # Принудительно собираем данные, которые есть
                waiting_for_markers = False
                markers_set_time = None
                
                # Собираем данные из очереди (может быть пусто)
                print("  Collecting available data from queue (may be empty)...")
                logs_collected = 0
                timeout = time.time() + 2.0
                
                while time.time() < timeout:
                    try:
                        log_data = queue_manager.debug_log_queue.get_nowait()
                        log_frame_id = log_data.get('frame_id')
                        if log_frame_id == frame_id:
                            log_entry = {
                                'process_name': log_data.get('process_name', 'unknown'),
                                'step_name': log_data.get('step_name', ''),
                                'description': log_data.get('description', ''),
                                'metadata': log_data.get('metadata', {}),
                                'image_path': log_data.get('image_path'),
                                'timestamp': log_data.get('timestamp', time.time())
                            }
                            logger.add_log(frame_id, log_entry)
                            logs_collected += 1
                            print(f"    Collected log: {log_entry['process_name']} - {log_entry['step_name']}")
                    except Empty:
                        time.sleep(0.1)
                        continue
                
                print(f"  Collected {logs_collected} log entries (timeout)")
                
                # Генерируем отчет даже если данных мало
                report_path = logger.generate_report(frame_id)
                if report_path:
                    print("=" * 80)
                    print(f"✅ REPORT GENERATED (timeout): {report_path}")
                    print("=" * 80)
                    try:
                        control_debug_logger.put({
                            'command': 'report_generated',
                            'report_path': report_path
                        })
                    except Exception as e:
                        print(f"Error sending report path to UI: {e}")
                else:
                    print(f"❌ Failed to generate report for frame {frame_id} (timeout)")
                
                continue
            
            all_cleared = True
            still_set = []
            for marker_name in process_markers:
                if hasattr(queue_manager, marker_name):
                    marker = getattr(queue_manager, marker_name)
                    if marker.is_set():
                        all_cleared = False
                        still_set.append(marker_name)
            
            # Периодически выводим статус ожидания
            if markers_set_time and int(time.time() * 2) % 10 == 0:  # Каждые 5 секунд
                elapsed = time.time() - markers_set_time
                if still_set:
                    print(f"  [{elapsed:.1f}s] Still waiting for markers: {still_set}")
            
            if all_cleared:
                # Все маркеры сброшены, ждем немного чтобы все данные попали в очередь
                print("  All markers cleared, waiting for data to arrive in queue...")
                time.sleep(1.0)  # Увеличиваем задержку до 1 секунды
                
                # Собираем все данные из очереди
                print("  Collecting data from queue...")
                logs_collected = 0
                timeout = time.time() + 3.0  # Увеличиваем таймаут до 3 секунд
                empty_count = 0  # Счетчик пустых проверок
                
                while time.time() < timeout:
                    try:
                        log_data = queue_manager.debug_log_queue.get_nowait()
                        empty_count = 0  # Сброс счетчика при получении данных
                        
                        # Проверяем frame_id (должен быть 'current_frame')
                        log_frame_id = log_data.get('frame_id')
                        if log_frame_id == frame_id:
                            # Добавляем лог
                            log_entry = {
                                'process_name': log_data.get('process_name', 'unknown'),
                                'step_name': log_data.get('step_name', ''),
                                'description': log_data.get('description', ''),
                                'metadata': log_data.get('metadata', {}),
                                'image_path': log_data.get('image_path'),
                                'timestamp': log_data.get('timestamp', time.time())
                            }
                            logger.add_log(frame_id, log_entry)
                            logs_collected += 1
                            print(f"    Collected log: {log_entry['process_name']} - {log_entry['step_name']}")
                    except Empty:
                        empty_count += 1
                        # Если очередь пуста несколько раз подряд, ждем немного
                        if empty_count > 5:
                            time.sleep(0.2)
                            empty_count = 0
                        else:
                            time.sleep(0.05)
                        continue
                
                print(f"  Collected {logs_collected} log entries")
                
                # Генерируем отчет
                report_path = logger.generate_report(frame_id)
                if report_path:
                    print("=" * 80)
                    print(f"✅ REPORT GENERATED: {report_path}")
                    print("=" * 80)
                    # Отправляем путь отчета обратно в UI
                    try:
                        control_debug_logger.put({
                            'command': 'report_generated',
                            'report_path': report_path
                        })
                    except Exception as e:
                        print(f"Error sending report path to UI: {e}")
                else:
                    print(f"❌ Failed to generate report for frame {frame_id}")
                
                # Сбрасываем флаг ожидания
                waiting_for_markers = False
        
        time.sleep(0.01)


def main(queue_manager, control_debug_logger):
    """Главная функция процесса debug logger"""
    process_debug_logger(queue_manager, control_debug_logger)
