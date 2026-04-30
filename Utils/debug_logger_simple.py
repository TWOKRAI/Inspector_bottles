"""
Упрощенный класс для отладочного логирования
Процессы сохраняют изображения сами и передают только пути через очередь
"""
import os
import time
from datetime import datetime
from typing import Optional, Dict, List, Any
from collections import defaultdict


class SimpleDebugLogger:
    """Упрощенный логгер - только собирает данные и формирует отчет"""
    
    def __init__(self, base_output_dir: str = "Data/debug_logs"):
        self.base_output_dir = os.path.abspath(base_output_dir)
        self.current_frame_id = None
        self.frame_data = defaultdict(list)  # {frame_id: [log_entries]}
        
        # Создаем базовую директорию
        os.makedirs(self.base_output_dir, exist_ok=True)
        print(f"SimpleDebugLogger initialized: {self.base_output_dir}")
    
    def start_frame(self, frame_id):
        """Начать логирование кадра (frame_id может быть строкой или int)"""
        self.current_frame_id = frame_id
        # Очищаем старые данные для этого кадра
        if frame_id in self.frame_data:
            self.frame_data[frame_id] = []
        else:
            self.frame_data[frame_id] = []
        print(f"SimpleDebugLogger: started frame {frame_id}")
    
    def add_log(self, frame_id, log_entry: Dict[str, Any]):
        """Добавить лог-запись для кадра (frame_id может быть строкой или int)"""
        if frame_id not in self.frame_data:
            self.frame_data[frame_id] = []
        self.frame_data[frame_id].append(log_entry)
    
    def generate_report(self, frame_id) -> Optional[str]:
        """Сгенерировать отчет для кадра (frame_id может быть строкой или int)"""
        if frame_id not in self.frame_data or len(self.frame_data[frame_id]) == 0:
            print(f"SimpleDebugLogger: no data for frame {frame_id}")
            return None
        
        # Создаем директорию для кадра
        frame_dir = os.path.join(self.base_output_dir, f"frame_{frame_id}")
        os.makedirs(frame_dir, exist_ok=True)
        
        report_path = os.path.join(frame_dir, "report.md")
        logs = self.frame_data[frame_id]
        
        # Группируем по процессам
        process_groups = defaultdict(list)
        for log in logs:
            process_name = log.get('process_name', 'unknown')
            process_groups[process_name].append(log)
        
        # Генерируем Markdown
        lines = []
        lines.append(f"# Отчет обработки изображения")
        lines.append("")
        lines.append(f"**Frame ID:** {frame_id}")
        lines.append(f"**Дата создания:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append("")
        
        # Порядок процессов (используем динамический поиск для region processors)
        process_order = ['process_processing']
        
        # Добавляем все process_region_processor_* процессы
        region_processors = sorted([p for p in process_groups.keys() if p.startswith('process_region_processor_')])
        process_order.extend(region_processors)
        
        # Добавляем остальные процессы
        process_order.extend(['process_region_merger', 'process_overlay'])
        
        step_num = 1
        for process_name in process_order:
            if process_name not in process_groups:
                continue
            
            lines.append(f"## Этап {step_num}: {process_name}")
            step_num += 1
            lines.append("")
            
            for log in process_groups[process_name]:
                timestamp = log.get('timestamp', time.time())
                time_str = datetime.fromtimestamp(timestamp).strftime('%H:%M:%S.%f')[:-3]
                lines.append(f"**Время:** {time_str}")
                
                if log.get('description'):
                    lines.append(f"**Описание:** {log['description']}")
                
                # Метаданные
                if log.get('metadata'):
                    lines.append("")
                    lines.append("### Метаданные")
                    for key, value in log['metadata'].items():
                        if isinstance(value, (dict, list)):
                            lines.append(f"- **{key}:** `{value}`")
                        else:
                            lines.append(f"- **{key}:** {value}")
                
                # Изображение
                image_path = log.get('image_path')
                if image_path and image_path.strip():  # Проверяем, что путь не пустой
                    lines.append("")
                    lines.append("### Изображение")
                    step_name = log.get('step_name', '')
                    if step_name:
                        lines.append(f"**Этап:** {step_name}")
                    # Используем относительный путь от report.md
                    rel_path = image_path.replace('\\', '/')
                    # Убеждаемся, что путь правильный
                    if not rel_path.startswith('images/'):
                        rel_path = f"images/{rel_path}" if not rel_path.startswith('/') else rel_path
                    # Используем HTML для уменьшения размера изображения (максимальная ширина 800px)
                    lines.append(f'<img src="{rel_path}" alt="{step_name or "Изображение"}" style="max-width: 800px; width: 100%; height: auto;" />')
                elif image_path is None or not image_path.strip():
                    # Если изображения нет, но это ожидаемо (например, для текстовых логов)
                    if log.get('metadata', {}).get('warning'):
                        lines.append("")
                        lines.append(f"⚠ **Предупреждение:** {log['metadata']['warning']}")
                
                lines.append("")
                lines.append("---")
                lines.append("")
        
        # Сохраняем отчет
        try:
            with open(report_path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(lines))
            
            abs_path = os.path.abspath(report_path)
            print(f"SimpleDebugLogger: report saved to {abs_path}")
            return abs_path
        except Exception as e:
            print(f"SimpleDebugLogger: error saving report: {e}")
            return None
    
    def clear(self, frame_id=None):
        """Очистить данные (frame_id может быть строкой, int или None)"""
        if frame_id is None:
            # Очищаем все данные и все папки
            import shutil
            for fid in list(self.frame_data.keys()):
                frame_dir = os.path.join(self.base_output_dir, f"frame_{fid}")
                if os.path.exists(frame_dir):
                    try:
                        shutil.rmtree(frame_dir)
                    except Exception as e:
                        print(f"Error clearing frame directory: {e}")
            self.frame_data.clear()
            print("SimpleDebugLogger: cleared all frames")
        else:
            if frame_id in self.frame_data:
                del self.frame_data[frame_id]
            
            # Удаляем папку кадра
            frame_dir = os.path.join(self.base_output_dir, f"frame_{frame_id}")
            if os.path.exists(frame_dir):
                import shutil
                try:
                    shutil.rmtree(frame_dir)
                    print(f"SimpleDebugLogger: cleared frame {frame_id}")
                except Exception as e:
                    print(f"Error clearing frame directory: {e}")

