"""
Универсальный класс для отладочного логирования процессов обработки изображений
Логирует этапы обработки с изображениями и метаданными, формирует Markdown отчет
"""
import os
import time
import cv2
import numpy as np
from datetime import datetime
from typing import Optional, Dict, List, Any
from collections import defaultdict


class DebugLogger:
    """Класс для логирования этапов обработки изображений с сохранением изображений и метаданных"""
    
    def __init__(self, base_output_dir: str = "Data/debug_logs"):
        """
        Инициализация логгера
        
        Args:
            base_output_dir: Базовая директория для сохранения логов
        """
        self.base_output_dir = base_output_dir
        self.enabled = False
        self.current_frame_id = None
        self.logs = []  # Список всех логов
        self.frame_logs = defaultdict(list)  # Логи по frame_id
        self.image_counter = defaultdict(int)  # Счетчик изображений для каждого frame_id
        
        # Создаем базовую директорию если её нет
        os.makedirs(self.base_output_dir, exist_ok=True)
        
        # Выводим путь для отладки
        abs_base_dir = os.path.abspath(self.base_output_dir)
        print(f"Debug logger initialized: base directory = {abs_base_dir}")
    
    def enable(self):
        """Включить логирование"""
        self.enabled = True
    
    def disable(self):
        """Выключить логирование"""
        self.enabled = False
    
    def is_enabled(self) -> bool:
        """Проверить включено ли логирование"""
        return self.enabled
    
    def start_frame_logging(self, frame_id: int):
        """
        Начать логирование для конкретного кадра
        
        Args:
            frame_id: ID кадра для логирования
        """
        if not self.enabled:
            return
        
        self.current_frame_id = frame_id
        self.frame_logs[frame_id] = []
        self.image_counter[frame_id] = 0
    
    def log_step(self, process_name: str, image: Optional[np.ndarray] = None, 
                  metadata: Optional[Dict[str, Any]] = None, 
                  description: str = "", step_name: str = ""):
        """
        Логировать этап обработки
        
        Args:
            process_name: Имя процесса (например, 'process_processing')
            image: Изображение для сохранения (опционально)
            metadata: Метаданные этапа (опционально)
            description: Описание этапа
            step_name: Имя этапа (например, 'original', 'cropped', 'mask')
        """
        if not self.enabled or self.current_frame_id is None:
            return
        
        # Отладочная информация
        if image is not None:
            print(f"Debug logger: logging step {step_name} from {process_name}, image shape: {image.shape}")
        
        timestamp = time.time()
        log_entry = {
            'type': 'step',
            'process_name': process_name,
            'frame_id': self.current_frame_id,
            'timestamp': timestamp,
            'step_name': step_name,
            'description': description,
            'metadata': metadata or {},
            'has_image': image is not None
        }
        
        # Сохраняем изображение если есть
        image_path = None
        if image is not None:
            try:
                image_path = self._save_image(image, process_name, step_name)
                if image_path:
                    log_entry['image_path'] = image_path
                    print(f"Debug logger: image saved: {image_path}")
                else:
                    print(f"Debug logger: failed to save image for {process_name}/{step_name}")
            except Exception as e:
                print(f"Debug logger: error saving image: {e}")
                import traceback
                traceback.print_exc()
        
        self.logs.append(log_entry)
        self.frame_logs[self.current_frame_id].append(log_entry)
    
    def log_data(self, process_name: str, data_dict: Dict[str, Any], 
                 description: str = ""):
        """
        Логировать текстовые данные без изображения
        
        Args:
            process_name: Имя процесса
            data_dict: Словарь с данными
            description: Описание данных
        """
        if not self.enabled or self.current_frame_id is None:
            return
        
        timestamp = time.time()
        log_entry = {
            'type': 'data',
            'process_name': process_name,
            'frame_id': self.current_frame_id,
            'timestamp': timestamp,
            'description': description,
            'data': data_dict
        }
        
        self.logs.append(log_entry)
        self.frame_logs[self.current_frame_id].append(log_entry)
    
    def log_image_flow(self, source: str, destination: str, 
                       image: Optional[np.ndarray] = None,
                       metadata: Optional[Dict[str, Any]] = None):
        """
        Логировать передачу изображения между процессами
        
        Args:
            source: Источник (имя процесса или 'memory')
            destination: Назначение (имя процесса или 'memory')
            image: Изображение (опционально)
            metadata: Метаданные передачи
        """
        if not self.enabled or self.current_frame_id is None:
            return
        
        timestamp = time.time()
        log_entry = {
            'type': 'image_flow',
            'frame_id': self.current_frame_id,
            'timestamp': timestamp,
            'source': source,
            'destination': destination,
            'metadata': metadata or {},
            'has_image': image is not None
        }
        
        # Сохраняем изображение если есть
        if image is not None:
            flow_name = f"{source}_to_{destination}"
            image_path = self._save_image(image, 'image_flow', flow_name)
            log_entry['image_path'] = image_path
        
        self.logs.append(log_entry)
        self.frame_logs[self.current_frame_id].append(log_entry)
    
    def _save_image(self, image: np.ndarray, process_name: str, step_name: str) -> str:
        """
        Сохранить изображение в файл
        
        Args:
            image: Изображение для сохранения
            process_name: Имя процесса
            step_name: Имя этапа
            
        Returns:
            Путь к сохраненному изображению
        """
        if self.current_frame_id is None:
            return ""
        
        # Создаем директорию для кадра
        frame_dir = os.path.join(self.base_output_dir, f"frame_{self.current_frame_id}")
        images_dir = os.path.join(frame_dir, "images")
        os.makedirs(images_dir, exist_ok=True)
        
        # Генерируем имя файла
        self.image_counter[self.current_frame_id] += 1
        counter = self.image_counter[self.current_frame_id]
        
        # Очищаем имена для файловой системы
        safe_process = process_name.replace('/', '_').replace('\\', '_')
        safe_step = step_name.replace('/', '_').replace('\\', '_') if step_name else f"step_{counter}"
        
        filename = f"{counter:03d}_{safe_process}_{safe_step}.png"
        filepath = os.path.join(images_dir, filename)
        
        # Конвертируем RGB в BGR для OpenCV если нужно
        # OpenCV ожидает BGR, но изображения из процессов уже в RGB
        if len(image.shape) == 3 and image.shape[2] == 3:
            # Конвертируем RGB в BGR для сохранения
            try:
                save_image = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
            except Exception as e:
                # Если конвертация не удалась, пробуем сохранить как есть
                print(f"Warning: RGB to BGR conversion failed, saving as is: {e}")
                save_image = image
        else:
            save_image = image
        
        # Сохраняем изображение
        try:
            success = cv2.imwrite(filepath, save_image)
            if not success:
                print(f"Warning: Failed to save image to {filepath}")
                return ""
            # Проверяем, что файл действительно создан
            if not os.path.exists(filepath):
                print(f"Warning: Image file was not created: {filepath}")
                return ""
        except Exception as e:
            print(f"Error saving image to {filepath}: {e}")
            return ""
        
        # Возвращаем относительный путь для Markdown
        return f"images/{filename}"
    
    def generate_report(self, frame_id: Optional[int] = None, 
                       output_path: Optional[str] = None) -> str:
        """
        Сгенерировать Markdown отчет
        
        Args:
            frame_id: ID кадра для отчета (если None, используется current_frame_id)
            output_path: Путь для сохранения отчета (если None, генерируется автоматически)
            
        Returns:
            Путь к сохраненному отчету
        """
        if frame_id is None:
            frame_id = self.current_frame_id
        
        if frame_id is None or frame_id not in self.frame_logs:
            return ""
        
        # Создаем директорию для кадра
        frame_dir = os.path.join(self.base_output_dir, f"frame_{frame_id}")
        os.makedirs(frame_dir, exist_ok=True)
        
        # Генерируем путь к отчету
        if output_path is None:
            output_path = os.path.join(frame_dir, "report.md")
        
        # Получаем логи для этого кадра
        frame_logs = self.frame_logs[frame_id]
        
        # Группируем логи по процессам
        process_groups = defaultdict(list)
        for log in frame_logs:
            process_groups[log.get('process_name', 'unknown')].append(log)
        
        # Генерируем Markdown
        markdown_lines = []
        
        # Заголовок
        markdown_lines.append(f"# Отчет обработки изображения")
        markdown_lines.append("")
        markdown_lines.append(f"**Frame ID:** {frame_id}")
        markdown_lines.append(f"**Дата создания:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        markdown_lines.append("")
        
        # Метаданные кадра (из первого лога)
        if frame_logs:
            first_log = frame_logs[0]
            if 'metadata' in first_log and first_log['metadata']:
                markdown_lines.append("## Метаданные кадра")
                markdown_lines.append("")
                for key, value in first_log['metadata'].items():
                    if key not in ['image', 'frames']:  # Пропускаем большие объекты
                        markdown_lines.append(f"- **{key}:** {value}")
                markdown_lines.append("")
        
        # Обрабатываем каждый процесс
        process_order = ['process_processing', 'process_region_processor', 
                        'process_region_merger', 'process_overlay']
        
        # Добавляем остальные процессы в конец
        for process_name in process_groups.keys():
            if process_name not in process_order:
                process_order.append(process_name)
        
        step_counter = 1
        for process_name in process_order:
            if process_name not in process_groups:
                continue
            
            process_logs = process_groups[process_name]
            
            # Заголовок процесса
            markdown_lines.append(f"## Этап {step_counter}: {process_name}")
            step_counter += 1
            markdown_lines.append("")
            
            # Обрабатываем логи процесса
            for log in process_logs:
                timestamp_str = datetime.fromtimestamp(log['timestamp']).strftime('%H:%M:%S.%f')[:-3]
                markdown_lines.append(f"**Время:** {timestamp_str}")
                
                if log.get('description'):
                    markdown_lines.append(f"**Описание:** {log['description']}")
                
                # Метаданные
                if log.get('metadata'):
                    markdown_lines.append("")
                    markdown_lines.append("### Метаданные")
                    for key, value in log['metadata'].items():
                        if key not in ['image', 'frames']:
                            if isinstance(value, (dict, list)):
                                markdown_lines.append(f"- **{key}:** `{value}`")
                            else:
                                markdown_lines.append(f"- **{key}:** {value}")
                
                # Изображение
                if log.get('has_image') and log.get('image_path'):
                    markdown_lines.append("")
                    markdown_lines.append("### Изображение")
                    step_name = log.get('step_name', '')
                    if step_name:
                        markdown_lines.append(f"**Этап:** {step_name}")
                    markdown_lines.append(f"![{step_name or 'Изображение'}]({log['image_path']})")
                
                # Данные
                if log.get('type') == 'data' and log.get('data'):
                    markdown_lines.append("")
                    markdown_lines.append("### Данные")
                    for key, value in log['data'].items():
                        if isinstance(value, (dict, list)):
                            markdown_lines.append(f"- **{key}:** `{value}`")
                        else:
                            markdown_lines.append(f"- **{key}:** {value}")
                
                # Image flow
                if log.get('type') == 'image_flow':
                    markdown_lines.append("")
                    markdown_lines.append("### Передача изображения")
                    markdown_lines.append(f"- **Источник:** {log.get('source', 'unknown')}")
                    markdown_lines.append(f"- **Назначение:** {log.get('destination', 'unknown')}")
                    if log.get('has_image') and log.get('image_path'):
                        markdown_lines.append(f"![Передача]({log['image_path']})")
                
                markdown_lines.append("")
                markdown_lines.append("---")
                markdown_lines.append("")
        
        # Граф потока данных (текстовое представление)
        markdown_lines.append("## Граф потока данных")
        markdown_lines.append("")
        
        # Собираем информацию о передачах
        flows = [log for log in frame_logs if log.get('type') == 'image_flow']
        if flows:
            markdown_lines.append("```")
            for flow in flows:
                markdown_lines.append(f"{flow.get('source', '?')} -> {flow.get('destination', '?')}")
            markdown_lines.append("```")
        else:
            markdown_lines.append("Нет данных о передачах изображений")
        
        markdown_lines.append("")
        
        # Сохраняем отчет
        try:
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(markdown_lines))
            
            # Проверяем, что файл создан
            if os.path.exists(output_path):
                abs_path = os.path.abspath(output_path)
                print(f"Debug logger: report saved successfully to {abs_path}")
                return abs_path
            else:
                print(f"Debug logger: report file was not created at {output_path}")
                return ""
        except Exception as e:
            print(f"Debug logger: error saving report to {output_path}: {e}")
            import traceback
            traceback.print_exc()
            return ""
    
    def clear(self, frame_id: Optional[int] = None):
        """
        Очистить накопленные данные и удалить файлы
        
        Args:
            frame_id: ID кадра для очистки (если None, очищает все)
        """
        if frame_id is None:
            # Удаляем все папки с логами
            import shutil
            if os.path.exists(self.base_output_dir):
                try:
                    shutil.rmtree(self.base_output_dir)
                    os.makedirs(self.base_output_dir, exist_ok=True)
                except Exception as e:
                    print(f"Error clearing debug logs directory: {e}")
            
            self.logs.clear()
            self.frame_logs.clear()
            self.image_counter.clear()
            self.current_frame_id = None
        else:
            # Удаляем папку конкретного кадра
            frame_dir = os.path.join(self.base_output_dir, f"frame_{frame_id}")
            if os.path.exists(frame_dir):
                try:
                    import shutil
                    shutil.rmtree(frame_dir)
                except Exception as e:
                    print(f"Error clearing frame {frame_id} directory: {e}")
            
            if frame_id in self.frame_logs:
                del self.frame_logs[frame_id]
            if frame_id in self.image_counter:
                del self.image_counter[frame_id]
            # Удаляем из общего списка логов
            self.logs = [log for log in self.logs if log.get('frame_id') != frame_id]
            
            if self.current_frame_id == frame_id:
                self.current_frame_id = None

