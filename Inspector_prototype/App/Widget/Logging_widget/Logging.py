# -*- coding: utf-8 -*-
"""
Виджет управления логированием и отчетами.
Отвечает только за управление логированием и генерацию debug отчетов.
"""
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel, QPushButton, QGroupBox, QMessageBox
from PyQt5.QtCore import QTimer
from queue import Empty
from App.Managers import LoggingManager


class LoggingWidget(QWidget):
    """Виджет для управления логированием и генерацией отчетов"""
    
    def __init__(self, window_manager=None, logging_manager: LoggingManager = None):
        super().__init__()
        self.window_manager = window_manager
        
        # Используем переданный LoggingManager или создаём новый
        if logging_manager:
            self.logging_manager = logging_manager
        else:
            # Создаём LoggingManager с queue_manager если доступен
            queue_manager = None
            if window_manager and hasattr(window_manager, 'queue_manager'):
                queue_manager = window_manager.queue_manager
            self.logging_manager = LoggingManager(queue_manager=queue_manager)
        
        # Подключаем сигналы
        self.logging_manager.report_generated.connect(self._on_report_generated)
        
        self.init_ui()
    
    def init_ui(self):
        layout = QVBoxLayout()
        self.setLayout(layout)
        
        # Группа для отладочного логирования
        debug_group = QGroupBox("Отладочное логирование")
        debug_layout = QVBoxLayout()
        debug_group.setLayout(debug_layout)
        
        # Описание
        info_label = QLabel("Логирует один кадр обработки и создает Markdown отчет\nс изображениями всех этапов")
        info_label.setWordWrap(True)
        debug_layout.addWidget(info_label)
        
        # Кнопка "Записать кадр и создать отчет"
        self.generate_report_button = QPushButton("📝 Записать кадр и создать отчет")
        self.generate_report_button.clicked.connect(self._on_generate_report_clicked)
        self.generate_report_button.setMinimumHeight(40)
        debug_layout.addWidget(self.generate_report_button)
        
        # Информация о сохранении
        self.status_label = QLabel("Готов к записи")
        self.status_label.setWordWrap(True)
        debug_layout.addWidget(self.status_label)
        
        # Кнопка для открытия папки с отчетами
        self.open_folder_button = QPushButton("📂 Открыть папку с отчетами")
        self.open_folder_button.clicked.connect(self._on_open_folder_clicked)
        debug_layout.addWidget(self.open_folder_button)
        
        layout.addWidget(debug_group)
    
    def _on_generate_report_clicked(self):
        """Обработчик нажатия кнопки 'Записать кадр и создать отчет'"""
        if not self.logging_manager.queue_manager:
            self.status_label.setText("❌ Ошибка: нет доступа к queue_manager")
            QMessageBox.warning(self, "Ошибка", "QueueManager не доступен. Невозможно сгенерировать отчет.")
            return
        
        try:
            # Обновляем статус
            self.status_label.setText("⏳ Получение кадра...")
            self.generate_report_button.setEnabled(False)
            
            # Используем фиксированный frame_id для одного кадра
            frame_id = "current_frame"
            
            # Отправляем команду генерации отчета через LoggingManager
            success = self.logging_manager.generate_debug_report(frame_id)
            
            if not success:
                self.status_label.setText("❌ Ошибка отправки команды генерации отчета")
                self.generate_report_button.setEnabled(True)
                return
            
            self.status_label.setText("📹 Ожидание обработки кадра...")
            
            # Ждем завершения обработки и автоматически обновляем статус
            self._check_report_status()
            
            # Таймаут на случай если отчет не будет сгенерирован
            def timeout_handler():
                if not self.generate_report_button.isEnabled():
                    self.status_label.setText("⏱ Таймаут ожидания отчета")
                    self.generate_report_button.setEnabled(True)
            
            QTimer.singleShot(10000, timeout_handler)  # 10 секунд таймаут
            
        except Exception as e:
            self.status_label.setText(f"❌ Ошибка: {str(e)}")
            self.generate_report_button.setEnabled(True)
            self.logging_manager.error(f"Ошибка создания отчета: {e}", exc_info=True)
    
    def _check_report_status(self):
        """Проверка статуса генерации отчета"""
        report_path = self.logging_manager.check_report_status()
        
        if report_path:
            # Отчет готов
            self.status_label.setText(f"✅ Отчет создан\n📄 {report_path}")
            self.generate_report_button.setEnabled(True)
            return
        
        # Если отчет еще не готов, проверяем еще раз через 0.5 секунды
        QTimer.singleShot(500, self._check_report_status)
    
    def _on_report_generated(self, report_path: str):
        """Обработчик сигнала о генерации отчета"""
        self.status_label.setText(f"✅ Отчет создан\n📄 {report_path}")
        self.generate_report_button.setEnabled(True)
    
    def _on_open_folder_clicked(self):
        """Открывает папку с отчетами в проводнике"""
        try:
            self.logging_manager.open_debug_logs_directory()
            self.status_label.setText(f"📂 Открыта папка:\n{self.logging_manager.get_debug_logs_directory()}")
        except Exception as e:
            self.status_label.setText(f"❌ Ошибка открытия папки: {str(e)}")
            self.logging_manager.error(f"Ошибка открытия папки с отчетами: {e}", exc_info=True)
    
    def set_logging_manager(self, logging_manager: LoggingManager):
        """Установить LoggingManager (для обновления после создания queue_manager)"""
        # Отключаем старые сигналы
        if self.logging_manager:
            self.logging_manager.report_generated.disconnect()
        
        self.logging_manager = logging_manager
        
        # Подключаем новые сигналы
        if logging_manager:
            logging_manager.report_generated.connect(self._on_report_generated)
