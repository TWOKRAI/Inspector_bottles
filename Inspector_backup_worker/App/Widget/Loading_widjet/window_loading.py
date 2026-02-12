# import time
# from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QProgressBar
# from PyQt5.QtGui import QPixmap
# from PyQt5.QtCore import  Qt

# from App.Widget.Loading_widjet.Threads.thread_loading import Loading


# class LoadingWindow(QWidget):
#     def __init__(self, window_manager = None):
#         super().__init__()

#         self.window_manager = window_manager

#         if not window_manager is None:
#             self.queue_manager = self.window_manager.queue_manager
#             #self.stop_event = self.window_manager.stop_event
#             self.fullscreen = self.window_manager.fullscreen
        
#         self.initUI()

#         if self.fullscreen: self.showFullScreen()

#         self.worker_loading = Loading(self.queue_manager)
#         self.worker_loading.progress_updated.connect(self.update_progress)
#         self.worker_loading.window_close.connect(self.close)
#         self.worker_loading.window_close.connect(self.window_manager.main_window.show)
#         self.worker_loading.start()


#     def initUI(self):
#         # Создаем вертикальный layout
#         vbox = QVBoxLayout()

#         # Создаем QLabel для отображения изображения
#         self.image_label = QLabel(self)
#         pixmap = QPixmap('App/Image/innotech.png')  # Замените на путь к вашему изображению
#         self.image_label.setPixmap(pixmap)
#         self.image_label.setAlignment(Qt.AlignCenter)  # Центрируем изображение

#         # Создаем QProgressBar для отображения строки загрузки
#         self.progress_bar = QProgressBar(self)
#         self.progress_bar.setRange(0, 8) 
#         self.progress_bar.setAlignment(Qt.AlignCenter)  # Центрируем строку загрузки

#         # Добавляем виджеты в вертикальный layout
#         vbox.addStretch()
#         vbox.addWidget(self.image_label)
#         vbox.addSpacing(35)
#         vbox.addWidget(self.progress_bar)
#         vbox.addStretch()

#         # Создаем горизонтальный layout для центрирования вертикального layout
#         hbox = QHBoxLayout()
#         hbox.addStretch(1)
#         hbox.addLayout(vbox)
#         hbox.addStretch(1)

#         # Устанавливаем layout для окна
#         self.setLayout(hbox)

#         # Устанавливаем параметры окна
#         self.setWindowTitle('Loading Window')
#         self.setGeometry(100, 100, 1000, 400)


#     def toggle_fullscreen(self):
#         if self.isFullScreen():
#             self.showNormal()
#         else:
#             self.showFullScreen()


#     def update_progress(self, value):
#         # Обновляем значение строки загрузки в зависимости от длины списка
#         self.progress_bar.setValue(value)


from PyQt5.QtCore import QTimer, Qt, pyqtSignal
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel, QProgressBar, QHBoxLayout, QPushButton
from PyQt5.QtGui import QPixmap

from App.Widget.Loading_widjet.Threads.thread_loading import Loading

class LoadingWindow(QWidget):
    timeout_signal = pyqtSignal()  # Сигнал при превышении времени загрузки

    def __init__(self, window_manager=None):
        super().__init__()
        self.window_manager = window_manager

        if window_manager is not None:
            self.queue_manager = window_manager.queue_manager
            self.fullscreen = window_manager.fullscreen

        self.setAttribute(Qt.WA_DeleteOnClose) 
        
        self.initUI()
        self.setup_timeout()
        
        if self.fullscreen:
            self.showFullScreen()

        self.worker_loading = Loading(self.queue_manager)
        self.worker_loading.progress_updated.connect(self.update_progress)
        self.worker_loading.window_close.connect(self.finish_loading)
        self.worker_loading.start()

    def initUI(self):
        # Основной layout
        self.main_layout = QVBoxLayout()
        
        # Загрузочное изображение
        self.image_label = QLabel(self)
        pixmap = QPixmap('App/Image/innotech.png')
        self.image_label.setPixmap(pixmap)
        self.image_label.setAlignment(Qt.AlignCenter)

        # Прогресс-бар
        self.progress_bar = QProgressBar(self)
        self.progress_bar.setRange(0, 8)
        self.progress_bar.setAlignment(Qt.AlignCenter)

        self.progress_bar_layout = QHBoxLayout()

        self.progress_bar_layout.addSpacing(210)
        self.progress_bar_layout.addWidget(self.progress_bar)
        self.progress_bar_layout.addSpacing(220)

        # Добавление виджетов
        self.main_layout.addStretch()
        self.main_layout.addWidget(self.image_label)
        self.main_layout.addSpacing(21)
        self.main_layout.addLayout(self.progress_bar_layout)
        self.main_layout.addStretch()

        # Кнопка для принудительного закрытия (изначально скрыта)
        self.force_close_btn = QPushButton("Прервать загрузку\nНажмите для выхода", self)
        self.force_close_btn.setStyleSheet("""
            QPushButton {
                background-color: rgba(200, 50, 50, 150);
                color: white;
                font-size: 24px;
                border: none;
            }
            QPushButton:hover {
                background-color: rgba(220, 70, 70, 180);
            }
        """)
        self.force_close_btn.hide()
        self.force_close_btn.clicked.connect(self.force_close)

        self.setLayout(self.main_layout)
        self.setWindowTitle('Loading Window')

    def setup_timeout(self):
        """Настройка таймера для отображения кнопки при долгой загрузке"""
        self.timeout_timer = QTimer(self)
        self.timeout_timer.setSingleShot(True)
        self.timeout_timer.timeout.connect(self.show_force_close_button)
        self.timeout_timer.start(21000)

    def show_force_close_button(self):
        """Показать кнопку принудительного закрытия"""
        self.force_close_btn.setFixedSize(self.size())
        self.force_close_btn.move(0, 0)
        self.force_close_btn.show()
        self.force_close_btn.raise_()

    def force_close(self):
        """Принудительное закрытие окна"""
        print("[DEBUG] Принудительное закрытие окна загрузки")
        self.worker_loading.stop_event.set()  # Останавливаем поток загрузки
        self.finish_loading()
        self.window_manager.close_program()

    def finish_loading(self):
        """Корректное завершение загрузки"""
        if hasattr(self, 'timeout_timer'):
            self.timeout_timer.stop()
        
        self.close()

        if self.window_manager and self.window_manager.main_window:
            self.window_manager.main_window.show()
        

    def update_progress(self, value):
        self.progress_bar.setValue(value)

    def resizeEvent(self, event):
        """Обновляем размер кнопки при изменении размера окна"""
        if hasattr(self, 'force_close_btn') and self.force_close_btn.isVisible():
            self.force_close_btn.setFixedSize(self.size())
        super().resizeEvent(event)